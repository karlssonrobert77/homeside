"""Number platform for HomeSide integration - writable control values."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any
from datetime import timedelta

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import HomesideClient
from .const import DOMAIN, UPDATE_INTERVAL_SLOW

_LOGGER = logging.getLogger(__name__)

_VARIABLES_FILE = Path(__file__).resolve().parent / "variables.json"


@dataclass(frozen=True, kw_only=True)
class VariableConfig:
    address: str
    name: str
    enabled: bool
    type: str
    note: str | None = None
    access: str | None = None
    role_access: str | None = None


@dataclass(frozen=True, kw_only=True)
class HomesideNumberEntityDescription(NumberEntityDescription):
    key: str
    min_value: float = 0.0
    max_value: float = 100.0
    step: float = 0.5


def _load_number_configs() -> list[VariableConfig]:
    """Load writable number variables from variables.json."""
    with open(_VARIABLES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    # Skip these patterns - they're not numbers
    skip_patterns = [
        "av/på",
        "läge",
        "(val)",
        "mode",
        "on/off",
    ]
    
    configs = []
    for address, config in data.get("mapping", {}).items():
        # Only include read_write variables with type "number" or writable sensors
        access = config.get("access", "read")
        if access != "read_write":
            continue
        
        # Skip if explicitly disabled
        if not config.get("enabled", False):
            continue
        
        # Skip binary/select variables
        name = config.get("name", "").lower()
        if any(pattern in name for pattern in skip_patterns):
            continue
        
        configs.append(
            VariableConfig(
                address=address,
                name=config.get("name", f"Number {address}"),
                enabled=config.get("enabled", False),
                type="number",
                note=config.get("note"),
                access=access,
                role_access=config.get("role_access"),
            )
        )
    
    return configs


# Define min/max/step for specific variables
_NUMBER_LIMITS = {
    # Heating curve points (temperature in °C)
    "0:233": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva -30°C
    "0:242": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva -25°C
    "0:251": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva -20°C
    "0:261": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva -15°C
    "0:269": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva -10°C
    "0:278": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva -5°C
    "0:287": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva 0°C
    "0:296": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva +5°C
    "0:305": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva +10°C
    "0:314": {"min": 10.0, "max": 80.0, "step": 0.5},  # Grundkurva +15°C
    
    # Adaptation curve points
    "0:431": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva -30°C
    "0:440": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva -25°C
    "0:449": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva -20°C
    "0:458": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva -15°C
    "0:467": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva -10°C
    "0:476": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva -5°C
    "0:485": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva 0°C
    "0:495": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva +5°C
    "0:503": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva +10°C
    "0:512": {"min": -10.0, "max": 10.0, "step": 0.5},  # Adaptionskurva +15°C
    
    # X-points (outdoor temperature in °C)
    "0:545": {"min": -40.0, "max": 20.0, "step": 1.0},  # X1
    "0:554": {"min": -40.0, "max": 20.0, "step": 1.0},  # X2
    "0:563": {"min": -40.0, "max": 20.0, "step": 1.0},  # X3
    "0:572": {"min": -40.0, "max": 20.0, "step": 1.0},  # X4
    "0:581": {"min": -40.0, "max": 20.0, "step": 1.0},  # X5
    "0:590": {"min": -40.0, "max": 20.0, "step": 1.0},  # X6
    "0:599": {"min": -40.0, "max": 20.0, "step": 1.0},  # X7
    "0:609": {"min": -40.0, "max": 20.0, "step": 1.0},  # X8
    "0:617": {"min": -40.0, "max": 20.0, "step": 1.0},  # X9
    "0:626": {"min": -40.0, "max": 20.0, "step": 1.0},  # X10
    
    # System parameters
    "0:273": {"min": -5.0, "max": 5.0, "step": 0.5},    # Parallelförskjutning
    "0:332": {"min": 15.0, "max": 25.0, "step": 0.5},   # Önskad rumstemperatur
    "0:377": {"min": 10.0, "max": 50.0, "step": 1.0},   # Min framledningstemperatur
    "0:386": {"min": 30.0, "max": 80.0, "step": 1.0},   # Max framledningstemperatur
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HomeSide number entities from a config entry."""
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    # Load writable number configs
    number_configs = _load_number_configs()
    
    if not number_configs:
        _LOGGER.info("No writable number variables enabled")
        return
    
    # Create coordinator for number entities (slower update since they're controls)
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=f"{DOMAIN}_numbers",
        update_method=lambda: _async_update_numbers(client, number_configs),
        update_interval=timedelta(seconds=UPDATE_INTERVAL_SLOW),
    )
    
    await coordinator.async_config_entry_first_refresh()
    
    # Create number entities
    entities = []
    for config in number_configs:
        limits = _NUMBER_LIMITS.get(config.address, {"min": 0.0, "max": 100.0, "step": 1.0})
        
        description = HomesideNumberEntityDescription(
            key=config.address,
            name=config.name,
            min_value=limits["min"],
            max_value=limits["max"],
            step=limits["step"],
        )
        
        entities.append(HomesideNumberEntity(coordinator, client, description, config))
    
    async_add_entities(entities)
    _LOGGER.info("Added %d writable number entities", len(entities))


async def _async_update_numbers(
    client: HomesideClient,
    configs: list[VariableConfig],
) -> dict[str, Any]:
    """Fetch current values for all number entities."""
    addresses = [cfg.address for cfg in configs]
    await client.ensure_connected()
    values = await client.read_points(addresses)
    return values


class HomesideNumberEntity(NumberEntity):
    """Representation of a HomeSide number entity."""
    
    entity_description: HomesideNumberEntityDescription
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX  # Use input box instead of slider for precision
    
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        client: HomesideClient,
        description: HomesideNumberEntityDescription,
        config: VariableConfig,
    ) -> None:
        """Initialize the number entity."""
        self.coordinator = coordinator
        self._client = client
        self.entity_description = description
        self._config = config
        
        self._attr_unique_id = f"{DOMAIN}_{config.address}_number"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, client.identity.serial or "homeside")},
            "name": "HomeSide",
            "manufacturer": "Regin",
            "model": client.identity.controller_name or "Unknown",
        }
        
        # Set min/max/step from description
        self._attr_native_min_value = description.min_value
        self._attr_native_max_value = description.max_value
        self._attr_native_step = description.step
        
        # Determine appropriate icon based on variable name
        if "kurva" in config.name.lower():
            self._attr_icon = "mdi:chart-line"
        elif "temp" in config.name.lower():
            self._attr_icon = "mdi:thermometer"
        elif "förskjutning" in config.name.lower():
            self._attr_icon = "mdi:delta"
        else:
            self._attr_icon = "mdi:tune"
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        value = self.coordinator.data.get(self._config.address)
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        _LOGGER.info("Setting %s to %s", self._config.address, value)
        
        # Validate value is within bounds
        if value < self.native_min_value or value > self.native_max_value:
            _LOGGER.error(
                "Value %s out of bounds [%s, %s] for %s",
                value,
                self.native_min_value,
                self.native_max_value,
                self._config.address,
            )
            return
        
        # Write the value
        success = await self._client.write_point(self._config.address, value)
        
        if success:
            # Update coordinator immediately to reflect the change
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to write value to %s", self._config.address)
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None
    
    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
    
    async def async_update(self) -> None:
        """Update the entity."""
        await self.coordinator.async_request_refresh()
