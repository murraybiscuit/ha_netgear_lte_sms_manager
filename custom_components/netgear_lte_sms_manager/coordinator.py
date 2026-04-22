"""DataUpdateCoordinator for Netgear LTE SMS Manager."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_AUTO_OPT_OUT,
    DOMAIN,
    EVENT_AUTO_OPT_OUT,
    EVENT_COMMAND_EXECUTED,
    EVENT_NEW_SMS,
    LOGGER,
)
from .helpers import (
    get_netgear_lte_entry,
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

            command = keyword_match(msg.message, commands)
            if command is None:
                continue

            domain, service = command["service"].split(".", 1)
            service_data = {"entity_id": command["entity_id"], **command.get("service_data", {})}

            success = True
            try:
                await self.hass.services.async_call(domain, service, service_data, blocking=False)
                LOGGER.info("Command '%s' executed for %s", command["name"], msg.sender)
                reply = command.get("reply_ok", "")
            except Exception as ex:
                LOGGER.warning("Command '%s' failed for %s: %s", command["name"], msg.sender, ex)
                success = False
                reply = command.get("reply_fail", "")

            self.hass.bus.async_fire(
                EVENT_COMMAND_EXECUTED,
                {
                    "command": command["name"],
                    "sender": msg.sender,
                    "message": msg.message,
                    "success": success,
                },
            )

            if reply:
                try:
                    await modem.send_sms(msg.sender, reply)
                except Exception as ex:
                    LOGGER.warning("Reply to %s failed: %s", msg.sender, ex)

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
                await modem.send_sms(msg.sender, "STOP")
                await modem.delete_sms(msg.id)
                opted_out.add(msg.id)
                LOGGER.info(
                    "Auto opted out: sent STOP to %s, deleted message %d",
                    msg.sender,
                    msg.id,
                )
                self.hass.bus.async_fire(
                    EVENT_AUTO_OPT_OUT,
                    {"sender": msg.sender, "sms_id": msg.id, "message": msg.message},
                )
            except Exception as ex:
                LOGGER.warning(
                    "Auto opt-out failed for %s (id=%d): %s", msg.sender, msg.id, ex
                )

        return opted_out
