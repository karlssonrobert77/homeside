"""Support for Homeside select entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HomesideDataUpdateCoordinator
from .const import DOMAIN
from .entity import HomesideEntity

_LOGGER = logging.getLogger(__name__)

# Mode definitions for pumps and valves
MODE_DEFINITIONS = {
    "0:487": {  # VV1 Tappvatten ventil indikering
        "options": ["0%", "Manuell", "Auto"],
        "values": [0, 1, 2],
    },
    "0:488": {  # VV1 Tappvatten (found in UI)
        "options": ["0%", "Manuell", "Auto"],
        "values": [0, 1, 2],
    },
    "0:494": {  # Fjärrvärme shuntventil läge
        "options": ["0%", "Manuell", "Auto"],
        "values": [0, 1, 2],
    },
    "0:565": {  # VS1 värmesystem shuntventil läge
        "options": ["0%", "Manuell", "Auto"],
        "values": [0, 1, 2],
    },
    "0:608": {  # VS1 värmesystem pump läge
        "options": ["Från", "Till", "Auto"],
        "values": [0, 1, 2],
    },
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Homeside selects from a config entry."""
    coordinator: HomesideDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Create select entities for mode variables
    entities = []
    for variable, mode_def in MODE_DEFINITIONS.items():
        config = coordinator.client.variables.get(variable)
        if config and config.get("enabled"):
            entities.append(HomesideSelect(coordinator, variable, config, mode_def))

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside select entities")


class HomesideSelect(HomesideEntity, SelectEntity):
    """Representation of a Homeside select entity (mode selector)."""

    def __init__(
        self,
        coordinator: HomesideDataUpdateCoordinator,
        variable: str,
        config: dict[str, Any],
        mode_def: dict[str, list],
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator, variable, config)
        self._mode_def = mode_def
        self._attr_options = mode_def["options"]
        self._attr_entity_category = "config"

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = self.coordinator.data.get(self._variable)
        if value is None:
            return None
        
        # Map numeric value to option string
        try:
            idx = self._mode_def["values"].index(int(value))
            return self._mode_def["options"][idx]
        except (ValueError, IndexError):
            return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        try:
            idx = self._mode_def["options"].index(option)
            value = self._mode_def["values"][idx]
            
            success = await self.coordinator.client.write_point(self._variable, value)
            if success:
                await self.coordinator.async_request_refresh()
        except ValueError:
            _LOGGER.error(f"Invalid option {option} for {self._variable}")
