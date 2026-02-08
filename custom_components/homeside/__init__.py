from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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
    
    # Create device in device registry
    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.entry_id)},
        name="HomeSide Värmesystem",
        manufacturer="HomeSide",
        model="HomeSide Controller",
        configuration_url=f"http://{host}",
    )

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "client": client,
        "device_id": entry.entry_id,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register update listener for options changes
    entry.async_on_unload(entry.add_update_listener(update_listener))
    
    return True


async def update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    data = hass.data[DOMAIN].pop(entry.entry_id)
    client: HomesideClient = data["client"]
    await client.close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
