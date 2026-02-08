"""Support for Homeside switches."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
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
    """Set up Homeside switches from a config entry."""
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]
    device_id = hass.data[DOMAIN][entry.entry_id]["device_id"]

    variables = _load_variables()
    
    # Get all boolean writable variables that are enabled
    switch_variables = []
    for variable, config in variables.items():
        if (
            config.get("enabled")
            and config.get("access") == "read_write"
            and config.get("type") in ["switch", "sensor"]  # Booleans are sensors
        ):
            # Check if it's a boolean by reading the value
            value = await client.read_point(variable)
            if isinstance(value, bool):
                switch_variables.append((variable, config))

    if not switch_variables:
        return

    # Create coordinator for switch updates
    async def _update() -> dict[str, Any]:
        await client.ensure_connected()
        data = {}
        for variable, config in switch_variables:
            try:
                value = await client.read_point(variable)
                if value is not None:
                    data[config['name']] = value
            except Exception as e:
                _LOGGER.debug(f"Error reading {variable}: {e}")
        return data

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="homeside_switches",
        update_method=_update,
        update_interval=timedelta(seconds=UPDATE_INTERVAL_NORMAL),
    )

    await coordinator.async_config_entry_first_refresh()

    entities = [
        HomesideSwitch(coordinator, client, device_id, variable, config)
        for variable, config in switch_variables
    ]

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside switches")


class HomesideSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Homeside switch."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        client: HomesideClient,
        device_id: str,
        variable: str,
        config: dict[str, Any],
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._client = client
        self._device_id = device_id
        self._variable = variable
        self._config = config
        self._name = config['name']
        self._attr_name = f"Homeside {config['name']}"
        self._attr_unique_id = f"homeside_{variable.replace(':', '_')}"
        
        # Set entity category if it's a configuration switch
        if any(word in config["name"].lower() for word in ["av/på", "val", "rumsgivare"]):
            self._attr_entity_category = "config"

    @property
    def device_info(self):
        from .const import DOMAIN
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        value = self.coordinator.data.get(self._name)
        if value is None:
            return None
        return bool(value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self._client.write_point(self._variable, True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self._client.write_point(self._variable, False)
        await self.coordinator.async_request_refresh()
