"""Config and options flow for Netgear LTE SMS Manager."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    CONF_AUTO_OPT_OUT,
    CONF_POLL_INTERVAL,
    CONF_WELCOME_MESSAGE,
    DEFAULT_POLL_INTERVAL,
    DEFAULT_WELCOME_MESSAGE,
    DOMAIN,
)


class NetgearLTESMSConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Single-entry config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title="Netgear LTE SMS Manager", data={})

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return OptionsFlowHandler()


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options: poll interval, auto opt-out, welcome message."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={**self.config_entry.options, **user_input},
            )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_POLL_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL
                        ),
                    ): selector.selector(
                        {
                            "number": {
                                "min": 60,
                                "max": 3600,
                                "step": 60,
                                "unit_of_measurement": "s",
                                "mode": "slider",
                            }
                        }
                    ),
                    vol.Required(
                        CONF_AUTO_OPT_OUT,
                        default=self.config_entry.options.get(CONF_AUTO_OPT_OUT, False),
                    ): selector.selector({"boolean": {}}),
                    vol.Optional(
                        CONF_WELCOME_MESSAGE,
                        default=self.config_entry.options.get(
                            CONF_WELCOME_MESSAGE, DEFAULT_WELCOME_MESSAGE
                        ),
                    ): selector.selector({"text": {"multiline": True}}),
                }
            ),
        )
