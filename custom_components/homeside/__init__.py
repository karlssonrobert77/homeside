from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import HomesideClient
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    host = entry.data[CONF_HOST]
    username = entry.data.get(CONF_USERNAME, "")
    password = entry.data.get(CONF_PASSWORD, "")
    session = async_get_clientsession(hass)
    client = HomesideClient(host, session, username=username, password=password)
    await client.connect()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].pop(entry.entry_id)
    client: HomesideClient = data["client"]
    await client.close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
