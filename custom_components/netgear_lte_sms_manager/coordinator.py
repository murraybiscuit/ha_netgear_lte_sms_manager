"""DataUpdateCoordinator for Netgear LTE SMS Manager."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import CONF_AUTO_OPT_OUT, DOMAIN, EVENT_NEW_SMS, LOGGER
from .helpers import get_netgear_lte_entry, is_opt_out_message, parse_whitelist_options
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

            if self._entry.options.get(CONF_AUTO_OPT_OUT, False) and new_messages:
                opted_out = await self._auto_opt_out(modem, new_messages)
                if opted_out:
                    messages = [m for m in messages if m.id not in opted_out]
                    current_ids -= opted_out

        self._first_poll = False
        self._last_seen_ids = current_ids
        return messages

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
            except Exception as ex:
                LOGGER.warning(
                    "Auto opt-out failed for %s (id=%d): %s", msg.sender, msg.id, ex
                )

        return opted_out
