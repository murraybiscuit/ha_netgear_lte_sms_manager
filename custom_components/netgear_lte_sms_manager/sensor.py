"""Sensor platform for Netgear LTE SMS Manager."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, LOGGER
from .coordinator import SMSCoordinator
from .helpers import get_netgear_lte_entry, load_contacts
from .models import NetgearLTECoreMissingError


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SMSCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([SMSInboxSensor(coordinator, entry)])


class SMSInboxSensor(CoordinatorEntity[SMSCoordinator], SensorEntity):
    """Sensor exposing SMS inbox count and message list."""

    _attr_icon = "mdi:message-text-outline"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "messages"
    _attr_has_entity_name = True
    _attr_translation_key = "sms_inbox"

    def __init__(self, coordinator: SMSCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_sms_inbox_v2"
        self._attr_name = "Inbox"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Netgear LTE SMS Manager",
            manufacturer="Netgear",
            model="LTE SMS Manager",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data is None:
            return None
        return len(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict:
        messages = [msg.to_dict() for msg in self.coordinator.data] if self.coordinator.data else []
        contacts = load_contacts(self._entry.options)

        sim_number = ""
        try:
            lte_entry = get_netgear_lte_entry(self.hass)
            coordinator = lte_entry.runtime_data
            info = coordinator.data
            if info is None:
                LOGGER.debug("netgear_lte coordinator data is None (first poll pending)")
            else:
                sim_number = info.items.get("sim.phonenumber", "")
                LOGGER.debug("sim_number from coordinator: %r", sim_number)
        except NetgearLTECoreMissingError as err:
            LOGGER.debug("netgear_lte entry not available: %s", err)
        except Exception:
            LOGGER.exception("Unexpected error reading sim_number")

        return {"messages": messages, "contacts": contacts, "sim_number": sim_number}
