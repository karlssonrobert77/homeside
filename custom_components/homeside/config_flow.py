from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_SHOW_DIAGNOSTIC, DOMAIN


class HomesideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return HomesideOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            # If no username provided, clear password as well
            if not user_input.get(CONF_USERNAME):
                user_input[CONF_USERNAME] = ""
                user_input[CONF_PASSWORD] = ""
            return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_USERNAME, default="", description={"suggested_value": ""}): str,
                vol.Optional(CONF_PASSWORD, default="", description={"suggested_value": ""}): str,
                vol.Optional(CONF_SHOW_DIAGNOSTIC, default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="user", 
            data_schema=schema,
            description_placeholders={
                "note": "Lämna användarnamn och lösenord tomt för skrivskyddad åtkomst (read-only)"
            }
        )


class HomesideOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_SHOW_DIAGNOSTIC,
                    default=self.config_entry.options.get(
                        CONF_SHOW_DIAGNOSTIC,
                        self.config_entry.data.get(CONF_SHOW_DIAGNOSTIC, False)
                    ),
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "note": "Visa debug/diagnostik-information (versioner, RSSI, heap memory, etc.)"
            },
        )
