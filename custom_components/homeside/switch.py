"""Support for Homeside switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import HomesideClient
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Homeside switches from a config entry."""
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]

    # Get all boolean writable variables that are enabled
    entities = []
    for variable, config in client.variables.items():
        if (
            config.get("enabled")
            and config.get("access") == "read_write"
            and config.get("type") in ["switch", "sensor"]  # Booleans are sensors
        ):
            # Check if it's a boolean by reading the value
            value = await client.read_point(variable)
            if isinstance(value, bool):
                entities.append(HomesideSwitch(client, variable, config))

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside switches")


class HomesideSwitch(SwitchEntity):
    """Representation of a Homeside switch."""

    def __init__(
        self,
        client: HomesideClient,
        variable: str,
        config: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        self._client = client
        self._variable = variable
        self._config = config
        self._attr_name = f"Homeside {config['name']}"
        self._attr_unique_id = f"homeside_{variable.replace(':', '_')}"
        self._attr_should_poll = True
        self._attr_is_on = None
        self._attr_available = True
        
        # Set entity category if it's a configuration switch
        if any(word in config["name"].lower() for word in ["av/på", "val", "rumsgivare"]):
            self._attr_entity_category = "config"

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        return self._attr_is_on

    async def async_update(self) -> None:
        """Fetch new state data for this switch."""
        try:
            value = await self._client.read_point(self._variable)
            if value is not None:
                self._attr_is_on = bool(value)
                self._attr_available = True
            else:
                self._attr_available = False
        except Exception as e:
            _LOGGER.error(f"Error updating switch {self._variable}: {e}")
            self._attr_available = False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._client.write_point(self._variable, True)
        await self.async_update()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._client.write_point(self._variable, False)
        await self.async_update()
