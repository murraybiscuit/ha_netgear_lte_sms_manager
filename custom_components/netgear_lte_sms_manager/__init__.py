"""Netgear LTE SMS Manager integration for Home Assistant."""

from __future__ import annotations

from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN, LOGGER
from .coordinator import SMSCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.SENSOR]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    LOGGER.info("Setting up Netgear LTE SMS Manager")
    async_setup_services(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    poll_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    coordinator = SMSCoordinator(hass, entry, poll_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def _async_options_updated(
    hass: HomeAssistant, entry: config_entries.ConfigEntry
) -> None:
    coordinator: SMSCoordinator | None = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    new_interval = entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    if coordinator is None or int(coordinator.update_interval.total_seconds()) != new_interval:
        await hass.config_entries.async_reload(entry.entry_id)
    else:
        coordinator.async_update_listeners()
