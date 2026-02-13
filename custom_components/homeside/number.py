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
    key: str  # Descriptive key from variables.json
    name: str
    enabled: bool
    type: str
    note: str | None = None
    access: str | None = None
    role_access: str | None = None
    address: list[str]  # Address(es) for this entity
    format: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None


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
    for key, config in data.get("mapping", {}).items():
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
                key=key,
                name=config.get("name", f"Number {key}"),
                enabled=config.get("enabled", False),
                type="number",
                note=config.get("note"),
                access=access,
                role_access=config.get("role_access"),
                address=config.get("address"),
                format=config.get("format"),
                min=config.get("min"),
                max=config.get("max"),
                step=config.get("step"),
            )
        )
    
    return configs


# Default limits for number entities (used if not specified in variables.json)
_DEFAULT_LIMITS = {"min": 0.0, "max": 100.0, "step": 1.0}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HomeSide number entities from a config entry."""
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]
    device_id = hass.data[DOMAIN][entry.entry_id]["device_id"]
    
    # Load writable number configs
    number_configs = _load_number_configs()
    # Session-level filtering
    from .const import ROLE_HIERARCHY
    session_level = getattr(client, '_session_level', None)
    allowed_roles = set()
    if session_level is not None:
        allowed_roles = set(ROLE_HIERARCHY[: session_level + 1])
    number_configs = [
        cfg for cfg in number_configs
        if not cfg.role_access or cfg.role_access in allowed_roles
    ]
    if not number_configs:
        _LOGGER.info("No writable number variables enabled")
        return
    
    # Separate combined from regular numbers
    combined_numbers = [cfg for cfg in number_configs if cfg.address]
    regular_numbers = [cfg for cfg in number_configs if not cfg.address]
    
    entities = []
    
    # Regular writable numbers
    if regular_numbers:
        # Create coordinator for number entities (slower update since they're controls)
        coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_numbers",
            update_method=lambda: _async_update_numbers(client, regular_numbers),
            update_interval=timedelta(seconds=UPDATE_INTERVAL_SLOW),
        )
        
        await coordinator.async_config_entry_first_refresh()
        
        # Create number entities
        for config in regular_numbers:
            # Use limits from config, or default if not specified
            min_val = config.min if config.min is not None else _DEFAULT_LIMITS["min"]
            max_val = config.max if config.max is not None else _DEFAULT_LIMITS["max"]
            step_val = config.step if config.step is not None else _DEFAULT_LIMITS["step"]
            
            description = HomesideNumberEntityDescription(
                key=config.address[0],
                name=config.name,
                min_value=min_val,
                max_value=max_val,
                step=step_val,
            )
            
            entities.append(HomesideNumberEntity(coordinator, client, description, config, device_id))
    
    # Combined numbers (read-only)
    if combined_numbers:
        for cfg in combined_numbers:
            if not cfg.address:
                continue
            
            variables = cfg.address
            
            async def _update_combined(vars=variables, fmt=cfg.format, cfg_name=cfg.name) -> dict[str, Any]:
                await client.ensure_connected()
                values, errors = await client.read_points_with_errors(vars)
                
                # Apply format template
                if fmt and all(addr in values for addr in vars):
                    try:
                        formatted_value = fmt.format(*[values[addr] for addr in vars])
                    except (KeyError, IndexError, ValueError) as e:
                        _LOGGER.warning("Failed to format combined number %s: %s", cfg_name, e)
                        formatted_value = None
                else:
                    formatted_value = None
                
                return {
                    "value": formatted_value,
                    "sources": {addr: values.get(addr) for addr in vars},
                    "errors": {addr: errors.get(addr) for addr in vars},
                }
            
            combined_coordinator = DataUpdateCoordinator(
                hass,
                logger=_LOGGER,
                name=f"homeside_combined_number_{cfg.address[0].replace(':', '_')}",
                update_method=_update_combined,
                update_interval=timedelta(seconds=UPDATE_INTERVAL_SLOW),
            )
            
            await combined_coordinator.async_refresh()
            entities.append(
                HomesideCombinedNumberEntity(combined_coordinator, cfg, device_id)
            )
    
    async_add_entities(entities)
    _LOGGER.info("Added %d number entities", len(entities))


async def _async_update_numbers(
    client: HomesideClient,
    configs: list[VariableConfig],
) -> dict[str, Any]:
    """Fetch current values for all number entities."""
    addresses = [cfg.address[0] for cfg in configs]
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
        device_id: str,
    ) -> None:
        """Initialize the number entity."""
        self.coordinator = coordinator
        self._client = client
        self.entity_description = description
        self._config = config
        self._device_id = device_id
        
        self._attr_unique_id = f"{DOMAIN}_{config.address[0]}_number"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
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
        value = self.coordinator.data.get(self._config.address[0])
        # Try to get error info if available
        errors = getattr(self.coordinator, 'data', {}).get('errors', {}) if hasattr(self.coordinator, 'data') else {}
        error = errors.get(self._config.address[0]) if errors else None
        # Load none_value_default from variables.json root
        none_value_default = 0
        try:
            import json
            from pathlib import Path
            variables_file = Path(__file__).resolve().parent / "variables.json"
            with open(variables_file, "r", encoding="utf-8") as f:
                root = json.load(f)
                none_value_default = root.get("none_value_dafault", 0)
        except Exception:
            pass
        if error and error.get("code") == 47 and value is None:
            value = none_value_default
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        extra = {}
        # Add readonly attribute if session_level is None/Guest
        try:
            readonly = False
            if hasattr(self._client, '_session_level') and self._client._session_level is not None and self._client._session_level <= 1:
                readonly = True
            extra["readonly"] = readonly
        except Exception:
            pass
        return extra or None
    
    async def async_set_native_value(self, value: float) -> None:
        """Set new value."""
        _LOGGER.info("Setting %s to %s", self._config.address[0], value)
        
        # Validate value is within bounds
        if value < self.native_min_value or value > self.native_max_value:
            _LOGGER.error(
                "Value %s out of bounds [%s, %s] for %s",
                value,
                self.native_min_value,
                self.native_max_value,
                self._config.address[0],
            )
            return
        
        # Write the value
        success = await self._client.write_point(self._config.address[0], value)
        
        if success:
            # Update coordinator immediately to reflect the change
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Failed to write value to %s", self._config.address[0])
    
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


class HomesideCombinedNumberEntity(NumberEntity):
    """Read-only number entity that combines multiple variables into one."""
    
    _attr_has_entity_name = True
    _attr_mode = NumberMode.BOX
    
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config: VariableConfig,
        device_id: str,
    ) -> None:
        """Initialize the combined number entity."""
        self.coordinator = coordinator
        self._config = config
        self._device_id = device_id
        
        self._attr_unique_id = f"{DOMAIN}_combined_{config.key.replace(":", "_").replace("/", "_")}_number"
        self._attr_name = config.name
        self._attr_device_info = {
            "identifiers": {(DOMAIN, device_id)},
        }
        
        # Combined numbers are read-only
        self._attr_native_min_value = 0.0
        self._attr_native_max_value = 100.0
        self._attr_native_step = 1.0
        
        # Icon
        if "version" in config.name.lower():
            self._attr_icon = "mdi:information"
        else:
            self._attr_icon = "mdi:numeric"
    
    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        data = self.coordinator.data or {}
        value = data.get("value")
        errors = data.get("errors", {})
        # Load none_value_default from variables.json root
        none_value_default = 0
        try:
            import json
            from pathlib import Path
            variables_file = Path(__file__).resolve().parent / "variables.json"
            with open(variables_file, "r", encoding="utf-8") as f:
                root = json.load(f)
                none_value_default = root.get("none_value_dafault", 0)
        except Exception:
            pass
        # If any error for a source is code 47 and value is None, use fallback
        if any((err and err.get("code") == 47 and value is None) for err in errors.values()):
            value = none_value_default
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None
    
    async def async_set_native_value(self, value: float) -> None:
        """Combined numbers are read-only."""
        _LOGGER.warning("Cannot write to combined number entity %s", self._config.name)
        return
    
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        data = self.coordinator.data or {}
        sources = data.get("sources", {})
        errors = data.get("errors", {})
        
        extra: dict[str, Any] = {}
        
        if sources:
            extra["sources"] = sources
        
        if self._config.address:
            extra["address"] = self._config.address
        
        if self._config.format:
            extra["format"] = self._config.format
        
        if self._config.note:
            extra["note"] = self._config.note
        
        if self._config.access:
            extra["access"] = self._config.access
        if self._config.role_access:
            extra["role_access"] = self._config.role_access
        
        if any(errors.values()):
            extra["errors"] = {k: v for k, v in errors.items() if v}
        
        return extra or None
    
    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.coordinator.last_update_success
    
    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
    
    async def async_update(self) -> None:
        """Update the entity."""
        await self.coordinator.async_request_refresh()
