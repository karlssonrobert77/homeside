from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN


class HomesideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_HOST], data=user_input)

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Optional(CONF_USERNAME, default=""): str,
                vol.Optional(CONF_PASSWORD, default=""): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema)
