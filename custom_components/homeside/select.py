"""Support for Homeside select entities."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import HomesideClient
from .const import DOMAIN, UPDATE_INTERVAL_NORMAL

_LOGGER = logging.getLogger(__name__)
_VARIABLES_FILE = Path(__file__).resolve().parent / "variables.json"

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


def _load_variables() -> dict[str, dict]:
    """Load variables from variables.json."""
    if not _VARIABLES_FILE.exists():
        return {}
    try:
        raw = json.loads(_VARIABLES_FILE.read_text(encoding="utf-8"))
        return raw.get("mapping", {})
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Failed to read variables mapping: %s", exc)
        return {}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Homeside selects from a config entry."""
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]

    variables = _load_variables()
    
    # Create select entities for mode variables
    select_variables = []
    for variable, mode_def in MODE_DEFINITIONS.items():
        config = variables.get(variable)
        if config and config.get("enabled"):
            select_variables.append((variable, config, mode_def))

    if not select_variables:
        return

    # Create coordinator for select updates
    async def _update() -> dict[str, Any]:
        await client.ensure_connected()
        data = {}
        for variable, _, _ in select_variables:
            try:
                value = await client.read_point(variable)
                if value is not None:
                    data[variable] = value
            except Exception as e:
                _LOGGER.debug(f"Error reading {variable}: {e}")
        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="homeside_selects",
        update_method=_update,
        update_interval=timedelta(seconds=UPDATE_INTERVAL_NORMAL),
    )

    await coordinator.async_config_entry_first_refresh()

    entities = [
        HomesideSelect(coordinator, variable, config, mode_def)
        for variable, config, mode_def in select_variables
    ]

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside select entities")


class HomesideSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Homeside select entity (mode selector)."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        variable: str,
        config: dict[str, Any],
        mode_def: dict[str, list],
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._variable = variable
        self._config = config
        self._mode_def = mode_def
        self._attr_name = f"Homeside {config['name']}"
        self._attr_unique_id = f"homeside_{variable.replace(':', '_')}"
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
            
            await self.coordinator.client.write_point(self._variable, value)
            await self.coordinator.async_request_refresh()
        except ValueError:
            _LOGGER.error(f"Invalid option {option} for {self._variable}")

