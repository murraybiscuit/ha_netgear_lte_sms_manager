"""Netgear LTE SMS Manager integration for Home Assistant."""

from __future__ import annotations

import shutil
from pathlib import Path

from homeassistant import config_entries
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from homeassistant.components import panel_custom

from .const import CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN, LOGGER
from .coordinator import SMSCoordinator
from .services import async_setup_services

PLATFORMS = [Platform.SENSOR]

_PANEL_JS = "netgear-sms-panel.js"
_PANEL_WWW_DIR = "netgear-sms-manager"
_PANEL_ENTITY = "sensor.netgear_lte_sms_manager_inbox"


def _deploy_panel_js(hass: HomeAssistant) -> None:
    """Copy panel JS from custom_components/www to /config/www on install/update."""
    src = Path(__file__).parent / "www" / _PANEL_JS
    if not src.exists():
        LOGGER.warning("Panel JS not found at %s — skipping deploy", src)
        return

    dst_dir = Path(hass.config.path("www", _PANEL_WWW_DIR))
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / _PANEL_JS

    if not dst.exists() or src.read_bytes() != dst.read_bytes():
        shutil.copy2(src, dst)
        LOGGER.info("Deployed %s to %s", _PANEL_JS, dst)
    else:
        LOGGER.debug("Panel JS already up to date at %s", dst)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    LOGGER.info("Setting up Netgear LTE SMS Manager")

    await hass.async_add_executor_job(_deploy_panel_js, hass)

    await panel_custom.async_register_panel(
        hass,
        webcomponent_name="netgear-sms-panel",
        sidebar_title="SMS Manager",
        sidebar_icon="mdi:message-text-outline",
        frontend_url_path="netgear-sms-manager",
        config={"entity": _PANEL_ENTITY},
        require_admin=False,
        js_url=f"/local/{_PANEL_WWW_DIR}/{_PANEL_JS}",
    )

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
