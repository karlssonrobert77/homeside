"""Support for Homeside switches."""
from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any
from datetime import timedelta

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .client import HomesideClient
from .const import DOMAIN, UPDATE_INTERVAL_NORMAL, get_none_value_default

_LOGGER = logging.getLogger(__name__)
_VARIABLES_FILE = Path(__file__).resolve().parent / "variables.json"

# Load variables.json once at module initialization to avoid blocking I/O warnings
with open(_VARIABLES_FILE, "r", encoding="utf-8") as _f:
    _VARIABLES_DATA = json.load(_f)


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
    invert: bool | None = None  # Invert the switch value


def _load_variable_configs() -> list[VariableConfig]:
    """Load variables from variables.json."""
    raw = _VARIABLES_DATA
    default_role_access = raw.get("role_access_default") or "Guest"
    
    configs: list[VariableConfig] = []
    for key, info in (raw.get("mapping") or {}).items():
        if not key or not isinstance(key, str):
            continue
        if not isinstance(info, dict):
            continue
        
        address = info.get("address")
        if not address or not isinstance(address, list):
            continue
        
        name = str(info.get("name") or key)
        enabled = bool(info.get("enabled", False))
        vtype = str(info.get("type") or "sensor")
        note = info.get("note")
        access = info.get("access")
        role_access = info.get("role_access") or default_role_access
        format_template = info.get("format")
        invert = info.get("invert")
        
        if vtype == "switch" and invert:
            _LOGGER.debug(f"Loading switch {key} with invert={invert}")
        
        configs.append(
            VariableConfig(
                key=key,
                name=name,
                enabled=enabled,
                type=vtype,
                note=note,
                access=access,
                role_access=role_access,
                address=address,
                format=format_template,
                invert=invert,
            )
        )
    
    return configs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Homeside switches from a config entry."""
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]
    device_id = hass.data[DOMAIN][entry.entry_id]["device_id"]

    variable_configs = _load_variable_configs()
    # Session-level filtering
    from .const import ROLE_HIERARCHY
    session_level = getattr(client, '_session_level', None)
    # Always set allowed_roles, even if session_level is None
    if session_level is None:
        allowed_roles = {ROLE_HIERARCHY[0]}
    else:
        allowed_roles = set(ROLE_HIERARCHY[: session_level + 1])
    # Get all switch variables that are enabled (only type=switch, respecting the type field)
    switch_configs = [
        cfg for cfg in variable_configs
        if cfg.enabled and cfg.access == "read_write" and cfg.type == "switch"
        and (not cfg.role_access or cfg.role_access in allowed_roles)
    ]
    # Separate combined from regular switches based on number of addresses
    # Regular switches: single address (writable)
    # Combined switches: multiple addresses (read-only, formatted)
    regular_switches = [cfg for cfg in switch_configs if cfg.address and len(cfg.address) == 1]
    combined_switches = [cfg for cfg in switch_configs if cfg.address and len(cfg.address) > 1]
    if not regular_switches and not combined_switches:
        return
    
    entities = []
    
    # Regular switches
    if regular_switches:
        # Verify they are actually boolean by reading values
        verified_switches = []
        for cfg in regular_switches:
            try:
                value = await client.read_point(cfg.address[0])
                if isinstance(value, bool):
                    verified_switches.append(cfg)
            except Exception as e:
                _LOGGER.debug(f"Error reading {cfg.address[0]}: {e}")
        
        if verified_switches:
            # Create coordinator for switch updates
            async def _update() -> dict[str, Any]:
                try:
                    await client.ensure_connected()
                    data = {}
                    for cfg in verified_switches:
                        try:
                            value = await client.read_point(cfg.address[0])
                            if value is not None:
                                data[cfg.name] = value
                        except Exception as e:
                            _LOGGER.debug(f"Error reading {cfg.address[0]}: {e}")
                    return data
                except ConnectionError as err:
                    _LOGGER.warning("Homeside connection error while updating switches: %s", err)
                    return {}
                except Exception as err:  # pragma: no cover - defensive
                    _LOGGER.exception("Unexpected error while updating switches: %s", err)
                    return {}

            coordinator = DataUpdateCoordinator(
                hass,
                _LOGGER,
                name="homeside_switches",
                update_method=_update,
                update_interval=timedelta(seconds=UPDATE_INTERVAL_NORMAL),
            )

            await coordinator.async_config_entry_first_refresh()

            entities.extend([
                HomesideSwitch(coordinator, client, device_id, cfg)
                for cfg in verified_switches
            ])
    
    # Combined switches (read-only)
    if combined_switches:
        for cfg in combined_switches:
            if not cfg.address:
                continue
            
            variables = cfg.address
            
            async def _update_combined(vars=variables, fmt=cfg.format, cfg_name=cfg.name) -> dict[str, Any]:
                try:
                    await client.ensure_connected()
                    values, errors = await client.read_points_with_errors(vars)

                    # Apply format template
                    if fmt and all(addr in values for addr in vars):
                        try:
                            formatted_value = fmt.format(*[values[addr] for addr in vars])
                        except (KeyError, IndexError, ValueError) as e:
                            _LOGGER.warning("Failed to format combined switch %s: %s", cfg_name, e)
                            formatted_value = None
                    else:
                        formatted_value = None

                    return {
                        "value": formatted_value,
                        "sources": {addr: values.get(addr) for addr in vars},
                        "errors": {addr: errors.get(addr) for addr in vars},
                    }
                except ConnectionError as err:
                    _LOGGER.warning("Homeside connection error while reading combined switch %s: %s", cfg_name, err)
                    return {"value": None, "sources": {addr: None for addr in vars}, "errors": {}}
                except Exception as err:  # pragma: no cover - defensive
                    _LOGGER.exception("Unexpected error while reading combined switch %s: %s", cfg_name, err)
                    return {"value": None, "sources": {addr: None for addr in vars}, "errors": {}}
            
            combined_coordinator = DataUpdateCoordinator(
                hass,
                logger=_LOGGER,
                name=f"homeside_combined_switch_{cfg.address[0].replace(':', '_')}",
                update_method=_update_combined,
                update_interval=timedelta(seconds=UPDATE_INTERVAL_NORMAL),
            )
            
            await combined_coordinator.async_refresh()
            entities.append(
                HomesideCombinedSwitch(combined_coordinator, cfg, device_id)
            )

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside switches")


class HomesideSwitch(CoordinatorEntity, SwitchEntity):
    """Representation of a Homeside switch."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        client: HomesideClient,
        device_id: str,
        config: VariableConfig,
    ) -> None:
        """Initialize the switch."""
        super().__init__(coordinator)
        self._client = client
        self._device_id = device_id
        self._config = config
        self._name = config.name
        
        if config.invert:
            _LOGGER.debug(f"Initialized switch {config.name} with invert=True")
        self._attr_name = f"Homeside {config.name}"
        self._attr_unique_id = f"homeside_{config.key.replace(":", "_").replace("/", "_")}"
        
        # Set entity category if it's a configuration switch
        if any(word in config.name.lower() for word in ["av/på", "val", "rumsgivare"]):
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def device_info(self):
        from .const import DOMAIN
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

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

    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        value = self.coordinator.data.get(self._name)
        # Try to get error info if available
        errors = getattr(self.coordinator, 'data', {}).get('errors', {}) if hasattr(self.coordinator, 'data') else {}
        error = errors.get(self._name) if errors else None
        if error and error.get("code") == 47 and value is None:
            value = get_none_value_default()
        if value is None:
            return None
        result = bool(value)
        # Invert if configured
        if self._config.invert:
            _LOGGER.debug(f"Switch {self._name}: Raw value={value}, bool={bool(value)}, inverting to {not result}")
            result = not result
        return result

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        # Invert if configured
        value_to_write = False if self._config.invert else True
        await self._client.write_point(self._config.address[0], value_to_write)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        # Invert if configured
        value_to_write = True if self._config.invert else False
        await self._client.write_point(self._config.address[0], value_to_write)
        await self.coordinator.async_request_refresh()


class HomesideCombinedSwitch(SwitchEntity):
    """Read-only switch that combines multiple variables into one."""
    
    _attr_has_entity_name = True
    
    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config: VariableConfig,
        device_id: str,
    ) -> None:
        """Initialize the combined switch."""
        self._coordinator = coordinator
        self._config = config
        self._device_id = device_id
        self._name = config.name
        self._attr_unique_id = f"homeside_combined_{config.key.replace(":", "_").replace("/", "_")}_switch"
        self._attr_name = f"Homeside {config.name}"
    
    @property
    def device_info(self):
        from .const import DOMAIN
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }
    
    @property
    def available(self) -> bool:
        return self._coordinator.last_update_success
    
    @property
    def is_on(self) -> bool | None:
        """Return true if switch is on."""
        data = self._coordinator.data or {}
        value = data.get("value")
        errors = data.get("errors", {})
        # If any error for a source is code 47 and value is None, use fallback
        if any((err and err.get("code") == 47 and value is None) for err in errors.values()):
            value = get_none_value_default()
        if value is None:
            return None
        # Convert to bool
        if isinstance(value, bool):
            result = value
        elif isinstance(value, str):
            result = value.lower() in ('true', '1', 'on', 'yes')
        else:
            result = bool(value)
        # Invert if configured
        if self._config.invert:
            result = not result
        return result
    
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Combined switches are read-only."""
        _LOGGER.warning("Cannot write to combined switch entity %s", self._config.name)
        return
    
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Combined switches are read-only."""
        _LOGGER.warning("Cannot write to combined switch entity %s", self._config.name)
        return
    
    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return extra attributes."""
        data = self._coordinator.data or {}
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
    
    async def async_update(self) -> None:
        """Update the entity."""
        await self._coordinator.async_request_refresh()
