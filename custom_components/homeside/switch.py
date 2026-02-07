"""Support for Homeside switches."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomesideDataUpdateCoordinator
from .const import DOMAIN
from .entity import HomesideEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Homeside switches from a config entry."""
    coordinator: HomesideDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Get all boolean writable variables that are enabled
    entities = []
    for variable, config in coordinator.client.variables.items():
        if (
            config.get("enabled")
            and config.get("access") == "read_write"
            and config.get("type") in ["switch", "sensor"]  # Booleans are sensors
        ):
            # Check if it's a boolean by reading the value
            value = coordinator.data.get(variable)
            if isinstance(value, bool):
                entities.append(HomesideSwitch(coordinator, variable, config))

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside switches")


class HomesideSwitch(HomesideEntity, SwitchEntity):
    """Representation of a Homeside switch."""

    def __init__(
        self,
        coordinator: HomesideDataUpdateCoordinator,
        variable: str,
        config: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, variable, config)
        
        # Set entity category if it's a configuration switch
        if any(word in config["name"].lower() for word in ["av/på", "val", "rumsgivare"]):
            self._attr_entity_category = "config"

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        value = self.coordinator.data.get(self._variable)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        success = await self.coordinator.client.write_point(self._variable, True)
        if success:
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        success = await self.coordinator.client.write_point(self._variable, False)
        if success:
            await self.coordinator.async_request_refresh()
