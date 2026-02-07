"""Support for Homeside select entities."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .client import HomesideClient
from .const import DOMAIN

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
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]

    # Create select entities for mode variables
    entities = []
    for variable, mode_def in MODE_DEFINITIONS.items():
        config = client.variables.get(variable)
        if config and config.get("enabled"):
            entities.append(HomesideSelect(client, variable, config, mode_def))

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside select entities")


class HomesideSelect(SelectEntity):
    """Representation of a Homeside select entity (mode selector)."""

    def __init__(
        self,
        client: HomesideClient,
        variable: str,
        config: dict[str, Any],
        mode_def: dict[str, list],
    ) -> None:
        """Initialize the select entity."""
        self._client = client
        self._variable = variable
        self._config = config
        self._mode_def = mode_def
        self._attr_name = f"Homeside {config['name']}"
        self._attr_unique_id = f"homeside_{variable.replace(':', '_')}"
        self._attr_options = mode_def["options"]
        self._attr_entity_category = "config"
        self._attr_should_poll = True
        self._attr_current_option = None
        self._attr_available = True

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        return self._attr_current_option

    async def async_update(self) -> None:
        """Fetch new state data for this select."""
        try:
            value = await self._client.read_point(self._variable)
            if value is not None:
                try:
                    idx = self._mode_def["values"].index(int(value))
                    self._attr_current_option = self._mode_def["options"][idx]
                    self._attr_available = True
                except (ValueError, IndexError):
                    self._attr_current_option = None
                    self._attr_available = False
            else:
                self._attr_available = False
        except Exception as e:
            _LOGGER.error(f"Error updating select {self._variable}: {e}")
            self._attr_available = False

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        try:
            idx = self._mode_def["options"].index(option)
            value = self._mode_def["values"][idx]
            
            await self._client.write_point(self._variable, value)
            await self.async_update()
        except ValueError:
            _LOGGER.error(f"Invalid option {option} for {self._variable}")
