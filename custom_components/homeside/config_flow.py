from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_USERNAME,
    CONF_SHOW_DIAGNOSTIC,
    CONF_UPDATE_INTERVAL_FAST,
    CONF_UPDATE_INTERVAL_NORMAL,
    CONF_UPDATE_INTERVAL_SLOW,
    CONF_RECONNECT_DELAY,
    CONF_KEEPALIVE_INTERVAL,
    DOMAIN,
    UPDATE_INTERVAL_FAST,
    UPDATE_INTERVAL_NORMAL,
    UPDATE_INTERVAL_SLOW,
)


class HomesideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return HomesideOptionsFlow()

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
    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            # Update entry.data with new credentials (host, username, password)
            new_data = {**self.config_entry.data}
            new_data[CONF_HOST] = user_input.pop(CONF_HOST)
            
            # Handle username and password - clear both if username is empty
            username = user_input.pop(CONF_USERNAME, "")
            password = user_input.pop(CONF_PASSWORD, "")
            if username:
                new_data[CONF_USERNAME] = username
                new_data[CONF_PASSWORD] = password
            else:
                # Remove credentials if username is empty
                new_data.pop(CONF_USERNAME, None)
                new_data.pop(CONF_PASSWORD, None)
            
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data=new_data
            )
            
            # Remaining options go to entry.options
            return self.async_create_entry(title="", data=user_input)

        # Get current options or use defaults from config entry data or constants
        current_options = self.config_entry.options
        current_data = self.config_entry.data
        
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=current_data.get(CONF_HOST, "")
                ): str,
                vol.Optional(
                    CONF_USERNAME,
                    default=current_data.get(CONF_USERNAME, "")
                ): str,
                vol.Optional(
                    CONF_PASSWORD,
                    default=current_data.get(CONF_PASSWORD, "")
                ): str,
                vol.Optional(
                    CONF_SHOW_DIAGNOSTIC,
                    default=current_options.get(
                        CONF_SHOW_DIAGNOSTIC,
                        current_data.get(CONF_SHOW_DIAGNOSTIC, False)
                    ),
                ): bool,
                vol.Optional(
                    CONF_UPDATE_INTERVAL_FAST,
                    default=current_options.get(
                        CONF_UPDATE_INTERVAL_FAST,
                        UPDATE_INTERVAL_FAST
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
                vol.Optional(
                    CONF_UPDATE_INTERVAL_NORMAL,
                    default=current_options.get(
                        CONF_UPDATE_INTERVAL_NORMAL,
                        UPDATE_INTERVAL_NORMAL
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                vol.Optional(
                    CONF_UPDATE_INTERVAL_SLOW,
                    default=current_options.get(
                        CONF_UPDATE_INTERVAL_SLOW,
                        UPDATE_INTERVAL_SLOW
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=60, max=3600)),
                vol.Optional(
                    CONF_RECONNECT_DELAY,
                    default=current_options.get(
                        CONF_RECONNECT_DELAY,
                        5
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=60)),
                vol.Optional(
                    CONF_KEEPALIVE_INTERVAL,
                    default=current_options.get(
                        CONF_KEEPALIVE_INTERVAL,
                        30
                    ),
                ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=schema,
            description_placeholders={
                "fast": "Snabba värden (temp, tryck)",
                "normal": "Normala värden (pumpar, ventiler)",
                "slow": "Långsamma värden (konfiguration)",
                "reconnect": "Väntetid före återanslutning (sekunder)",
                "keepalive": "Keep-alive ping intervall (sekunder)",
            },
        )
