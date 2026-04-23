"""DataUpdateCoordinator for Netgear LTE SMS Manager."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    AUTO_CLEANUP_KEEP,
    AUTO_CLEANUP_THRESHOLD,
    CONF_AUTO_CLEANUP,
    CONF_AUTO_OPT_OUT,
    CONF_LLM_MATCHING,
    DEFAULT_AUTO_CLEANUP,
    DOMAIN,
    EVENT_AUTO_OPT_OUT,
    EVENT_COMMAND_EXECUTED,
    EVENT_NEW_SMS,
    LOGGER,
)
from .helpers import (
    build_help_reply,
    get_netgear_lte_entry,
    is_help_message,
    is_opt_out_message,
    keyword_match,
    load_commands,
    load_contacts,
    normalize_number,
    parse_whitelist_options,
)
from .models import (
    EternalEgyptVersionError,
    ModemCommunicationError,
    ModemConnection,
    NetgearLTECoreMissingError,
    SMSMessage,
)

_CONFIRMATION_TTL = timedelta(minutes=5)


class SMSCoordinator(DataUpdateCoordinator[list[SMSMessage]]):
    """Polls the modem inbox on a schedule and fires events for new messages."""

    def __init__(self, hass, entry: ConfigEntry, poll_interval: int) -> None:
        super().__init__(
            hass,
            LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=poll_interval),
        )
        self._entry = entry
        self._last_seen_ids: set[int] = set()
        self._first_poll = True
        # sender_digits → (command_dict, expires_at) for LLM-matched pending confirmations
        self._pending_confirmations: dict[str, tuple[dict, datetime]] = {}

    async def _async_update_data(self) -> list[SMSMessage]:
        try:
            core_entry = get_netgear_lte_entry(self.hass)
            modem = ModemConnection(core_entry.runtime_data.modem)
            messages = await modem.get_sms_list()
        except NetgearLTECoreMissingError as ex:
            LOGGER.error("netgear_lte core missing: %s", ex)
            raise UpdateFailed(f"netgear_lte core missing: {ex}") from ex
        except (EternalEgyptVersionError, ModemCommunicationError) as ex:
            LOGGER.error("SMS fetch failed: %s", ex)
            raise UpdateFailed(f"Modem error: {ex}") from ex
        except Exception as ex:
            LOGGER.exception("Unexpected error fetching SMS inbox")
            raise UpdateFailed(f"Unexpected: {type(ex).__name__}: {ex}") from ex

        current_ids = {m.id for m in messages}

        if not self._first_poll:
            new_ids = current_ids - self._last_seen_ids
            new_messages = [m for m in messages if m.id in new_ids]

            for msg in new_messages:
                self.hass.bus.async_fire(
                    EVENT_NEW_SMS,
                    {
                        "sms_id": msg.id,
                        "sender": msg.sender,
                        "message": msg.message,
                        "timestamp": msg.timestamp,
                    },
                )
                LOGGER.debug("New SMS from %s (id=%d)", msg.sender, msg.id)

            try:
                await self._dispatch_commands(modem, new_messages)
            except Exception:
                LOGGER.exception("Unexpected error in _dispatch_commands — continuing poll")

            if self._entry.options.get(CONF_AUTO_OPT_OUT, False) and new_messages:
                opted_out = await self._auto_opt_out(modem, new_messages)
                if opted_out:
                    messages = [m for m in messages if m.id not in opted_out]
                    current_ids -= opted_out

            if self._entry.options.get(CONF_AUTO_CLEANUP, DEFAULT_AUTO_CLEANUP):
                messages = await self._auto_cleanup_inbox(modem, messages)
                current_ids = {m.id for m in messages}

        self._first_poll = False
        self._last_seen_ids = current_ids
        return messages

    async def _dispatch_commands(
        self, modem: ModemConnection, new_messages: list[SMSMessage]
    ) -> None:
        """Match new messages from trusted contacts against commands and execute."""
        commands = load_commands(self._entry.options)
        if not commands:
            return

        contacts = load_contacts(self._entry.options)
        trusted_numbers = {normalize_number(c["number"]) for c in contacts}

        for msg in new_messages:
            if normalize_number(msg.sender) not in trusted_numbers:
                continue

            sender_digits = normalize_number(msg.sender)

            # --- LLM confirmation round-trip ---
            pending = self._pending_confirmations.get(sender_digits)
            if pending is not None:
                pending_cmd, expires = pending
                if datetime.now(timezone.utc) <= expires:
                    reply_text = msg.message.strip().lower()
                    if reply_text in ("yes", "y", "confirm"):
                        del self._pending_confirmations[sender_digits]
                        LOGGER.info(
                            "LLM command '%s' confirmed by %s",
                            pending_cmd["name"],
                            sender_digits,
                        )
                        await self._execute_command(modem, pending_cmd, sender_digits, msg.message)
                        continue
                    if reply_text in ("no", "n", "cancel"):
                        del self._pending_confirmations[sender_digits]
                        try:
                            await modem.send_sms(sender_digits, "Command cancelled.")
                        except Exception as ex:
                            LOGGER.warning("Cancel reply to %s failed: %s", sender_digits, ex)
                        continue
                else:
                    del self._pending_confirmations[sender_digits]

            # --- HELP ---
            if is_help_message(msg.message):
                reply = build_help_reply(commands)
                try:
                    await modem.send_sms(sender_digits, reply)
                    LOGGER.info("Sent HELP reply to %s", sender_digits)
                except Exception as ex:
                    LOGGER.warning("HELP reply to %s failed: %s", sender_digits, ex)
                continue

            # --- Keyword match (execute immediately) ---
            command = keyword_match(msg.message, commands)
            LOGGER.debug(
                "keyword_match result for '%s': %s",
                msg.message,
                command["name"] if command else None,
            )

            if command is not None:
                await self._execute_command(modem, command, sender_digits, msg.message)
                continue

            # --- LLM match (requires confirmation) ---
            llm_enabled = self._entry.options.get(CONF_LLM_MATCHING, False)
            if llm_enabled:
                LOGGER.debug("Invoking LLM classify for: %s", msg.message)
                command = await self._llm_classify(msg.message, commands)
                if command is not None:
                    LOGGER.debug("LLM matched '%s', awaiting confirmation from %s", command["name"], sender_digits)
                    expires = datetime.now(timezone.utc) + _CONFIRMATION_TTL
                    self._pending_confirmations[sender_digits] = (command, expires)
                    try:
                        await modem.send_sms(
                            sender_digits,
                            f"Did you mean: {command['name']}? Reply YES to confirm or NO to cancel.",
                        )
                    except Exception as ex:
                        LOGGER.warning("Confirmation prompt to %s failed: %s", sender_digits, ex)
                        del self._pending_confirmations[sender_digits]
                    continue

            # --- No match ---
            disabled = keyword_match(msg.message, commands, include_disabled=True)
            if disabled:
                try:
                    await modem.send_sms(
                        sender_digits,
                        f"Command '{disabled['name']}' is currently disabled. Reply HELP for available commands.",
                    )
                except Exception as ex:
                    LOGGER.warning("Disabled-command reply to %s failed: %s", sender_digits, ex)

    async def _execute_command(
        self,
        modem: ModemConnection,
        command: dict,
        sender_digits: str,
        original_message: str,
    ) -> None:
        """Execute a matched command and send the reply SMS."""
        domain, service = command["service"].split(".", 1)
        service_data = {"entity_id": command["entity_id"], **command.get("service_data", {})}

        success = True
        try:
            await self.hass.services.async_call(domain, service, service_data, blocking=False)
            LOGGER.info("Command '%s' executed for %s", command["name"], sender_digits)
            reply = command.get("reply_ok", "")
        except Exception as ex:
            LOGGER.warning("Command '%s' failed for %s: %s", command["name"], sender_digits, ex)
            success = False
            reply = command.get("reply_fail", "")

        self.hass.bus.async_fire(
            EVENT_COMMAND_EXECUTED,
            {
                "command": command["name"],
                "sender": sender_digits,
                "message": original_message,
                "success": success,
            },
        )

        if reply:
            try:
                await modem.send_sms(sender_digits, reply)
            except Exception as ex:
                LOGGER.warning("Reply to %s failed: %s", sender_digits, ex)

    async def _llm_classify(self, text: str, commands: list[dict]) -> dict | None:
        """Call Ollama directly to classify text against enabled commands."""
        enabled = [c for c in commands if c.get("enabled", True) is not False]
        LOGGER.debug("_llm_classify: %d enabled commands", len(enabled))
        if not enabled:
            return None

        ollama_entries = self.hass.config_entries.async_entries("ollama")
        if not ollama_entries:
            LOGGER.debug("_llm_classify: no Ollama config entry found, skipping")
            return None

        ollama_entry = ollama_entries[0]
        base_url = ollama_entry.data.get("url", "http://localhost:11434")
        model = "llama3.2:3b"
        for subentry in ollama_entry.subentries.values():
            if subentry.subentry_type == "conversation":
                model = subentry.data.get("model", model)
                break

        numbered = list(enumerate(enabled, start=1))
        choices = "\n".join(f"{i}. {c['name']}" for i, c in numbered)
        max_n = len(numbered)
        prompt = (
            f"Which number best matches the message below? Reply with ONLY a single digit (1-{max_n}), or 0 if none match.\n\n"
            f"Options:\n{choices}\n\n"
            f"Message: \"{text}\"\n\nAnswer:"
        )

        try:
            LOGGER.debug("_llm_classify: POST %s/api/generate model=%s", base_url, model)
            session = async_get_clientsession(self.hass)
            async with session.post(
                f"{base_url}/api/generate",
                json={"model": model, "prompt": prompt, "stream": False},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    LOGGER.debug("_llm_classify: Ollama returned HTTP %d: %s", resp.status, body[:200])
                    return None
                data = await resp.json()
                response = data.get("response", "").strip()
                LOGGER.debug("_llm_classify: raw response=%r", response)

                m = re.search(r"\d+", response)
                if not m:
                    return None
                choice = int(m.group())
                if choice == 0 or choice > max_n:
                    return None
                return numbered[choice - 1][1]
        except Exception as ex:
            LOGGER.debug("LLM classification failed: %s", ex)

        return None

    async def _auto_cleanup_inbox(
        self, modem: ModemConnection, messages: list[SMSMessage]
    ) -> list[SMSMessage]:
        """Delete oldest messages when inbox approaches the modem limit."""
        if len(messages) < AUTO_CLEANUP_THRESHOLD:
            return messages

        contacts = load_contacts(self._entry.options)
        trusted_numbers = {normalize_number(c["number"]) for c in contacts}

        # Sort oldest-first; prefer deleting untrusted messages first
        untrusted = [m for m in messages if normalize_number(m.sender) not in trusted_numbers]
        trusted = [m for m in messages if normalize_number(m.sender) in trusted_numbers]
        ordered = sorted(untrusted, key=lambda m: m.id) + sorted(trusted, key=lambda m: m.id)

        to_delete = ordered[:max(0, len(messages) - AUTO_CLEANUP_KEEP)]
        if not to_delete:
            return messages

        deleted_ids: set[int] = set()
        for msg in to_delete:
            try:
                await modem.delete_sms(msg.id)
                deleted_ids.add(msg.id)
            except Exception as ex:
                LOGGER.warning("Auto-cleanup: failed to delete sms %d: %s", msg.id, ex)

        if deleted_ids:
            LOGGER.info("Auto-cleanup: deleted %d messages, inbox trimmed to %d", len(deleted_ids), len(messages) - len(deleted_ids))

        return [m for m in messages if m.id not in deleted_ids]

    async def _auto_opt_out(
        self, modem: ModemConnection, new_messages: list[SMSMessage]
    ) -> set[int]:
        """Reply STOP and delete any new message that contains opt-out instructions."""
        options = self._entry.options
        parsed = parse_whitelist_options(options)
        whitelist: set[str] = parsed.get("phone_numbers", set())
        for c in parsed.get("contacts", {}).values():
            if c.get("number"):
                whitelist.add(c["number"])

        opted_out: set[int] = set()
        for msg in new_messages:
            if msg.sender in whitelist:
                continue
            if not is_opt_out_message(msg.message):
                continue
            try:
                sender_digits = normalize_number(msg.sender)
                await modem.send_sms(sender_digits, "STOP")
                await modem.delete_sms(msg.id)
                opted_out.add(msg.id)
                LOGGER.info(
                    "Auto opted out: sent STOP to %s, deleted message %d",
                    sender_digits,
                    msg.id,
                )
                self.hass.bus.async_fire(
                    EVENT_AUTO_OPT_OUT,
                    {"sender": sender_digits, "sms_id": msg.id, "message": msg.message},
                )
            except Exception as ex:
                LOGGER.warning(
                    "Auto opt-out failed for %s (id=%d): %s", msg.sender, msg.id, ex
                )

        return opted_out
