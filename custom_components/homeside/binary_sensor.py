from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any
from datetime import timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .client import HomesideClient
from .const import (
    DOMAIN,
    FAST_UPDATE_PATTERNS,
    NORMAL_UPDATE_PATTERNS,
    SLOW_UPDATE_PATTERNS,
    VERY_SLOW_UPDATE_PATTERNS,
    UPDATE_INTERVAL_FAST,
    UPDATE_INTERVAL_NORMAL,
    UPDATE_INTERVAL_SLOW,
    UPDATE_INTERVAL_VERY_SLOW,
)

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


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]
    device_id = hass.data[DOMAIN][entry.entry_id]["device_id"]

    variable_configs = _load_variable_configs()
    binary_configs = [cfg for cfg in variable_configs if cfg.enabled and cfg.type == "binary_sensor"]
    if not binary_configs:
        return

    # Separate multi-variable combined sensors from single-variable sensors
    combined_sensors = [cfg for cfg in binary_configs if len(cfg.address) > 1]
    regular_sensors = [cfg for cfg in binary_configs if len(cfg.address) == 1]

    # Group binary sensors by update interval
    fast_sensors = []
    normal_sensors = []
    slow_sensors = []
    very_slow_sensors = []
    
    for cfg in regular_sensors:
        name_lower = cfg.name.lower()
        if any(pattern in name_lower for pattern in VERY_SLOW_UPDATE_PATTERNS):
            very_slow_sensors.append(cfg)
        elif any(pattern in name_lower for pattern in SLOW_UPDATE_PATTERNS):
            slow_sensors.append(cfg)
        elif any(pattern in name_lower for pattern in FAST_UPDATE_PATTERNS):
            fast_sensors.append(cfg)
        else:
            normal_sensors.append(cfg)
    
    entities = []
    
    # Create coordinators for each update group
    sensor_groups = [
        (fast_sensors, UPDATE_INTERVAL_FAST, "fast"),
        (normal_sensors, UPDATE_INTERVAL_NORMAL, "normal"),
        (slow_sensors, UPDATE_INTERVAL_SLOW, "slow"),
        (very_slow_sensors, UPDATE_INTERVAL_VERY_SLOW, "very_slow"),
    ]
    
    for group_configs, interval, group_name in sensor_groups:
        if not group_configs:
            continue
            
        variables = [cfg.address[0] for cfg in group_configs]
        name_by_address = {cfg.address[0]: cfg.name for cfg in group_configs}
        note_by_address = {cfg.address[0]: cfg.note for cfg in group_configs}
        access_by_address = {cfg.address[0]: cfg.access for cfg in group_configs}
        role_by_address = {cfg.address[0]: cfg.role_access for cfg in group_configs}

        async def _update_variables(vars=variables, names=name_by_address, notes=note_by_address, access=access_by_address, roles=role_by_address) -> dict[str, Any]:
            await client.ensure_connected()
            values, errors = await client.read_points_with_errors(vars)
            mapped_values = {names[address]: values.get(address) for address in vars}
            mapped_errors = {names[address]: errors.get(address) for address in vars}
            mapped_notes = {names[address]: notes.get(address) for address in vars}
            mapped_access = {names[address]: access.get(address) for address in vars}
            mapped_roles = {names[address]: roles.get(address) for address in vars}
            return {
                "values": mapped_values,
                "errors": mapped_errors,
                "notes": mapped_notes,
                "access": mapped_access,
                "role_access": mapped_roles,
            }

        variables_coordinator = DataUpdateCoordinator(
            hass,
            logger=_LOGGER,
            name=f"homeside_binary_variables_{group_name}",
            update_method=_update_variables,
            update_interval=timedelta(seconds=interval),
        )

        await variables_coordinator.async_refresh()
        entities.extend(
            HomesideVariableBinarySensor(variables_coordinator, cfg.name, device_id)
            for cfg in group_configs
        )
    
    # Add combined binary sensors
    if combined_sensors:
        for cfg in combined_sensors:
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
                        _LOGGER.warning("Failed to format combined binary sensor %s: %s", cfg_name, e)
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
                name=f"homeside_combined_binary_{cfg.address.replace(':', '_')}",
                update_method=_update_combined,
                update_interval=timedelta(seconds=UPDATE_INTERVAL_NORMAL),
            )
            
            await combined_coordinator.async_refresh()
            entities.append(
                HomesideCombinedBinarySensor(combined_coordinator, cfg, device_id)
            )
    
    async_add_entities(entities)


class HomesideVariableBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        name: str,
        device_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._name = name
        self._device_id = device_id
        self._attr_unique_id = f"homeside_var_{name}"
        
        # Set entity category based on binary sensor type
        name_lower = name.lower()
        if any(word in name_lower for word in ['val', 'status']):
            # Configuration switches (selection of sensors/modes)
            self._attr_entity_category = "config"

    @property
    def name(self) -> str | None:
        return self._name

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
        data = self._coordinator.data or {}
        values = data.get("values", {})
        value = values.get(self._name)
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        return bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        data = self._coordinator.data or {}
        errors = data.get("errors", {})
        info = errors.get(self._name)
        note = (data.get("notes", {}) or {}).get(self._name)
        access = (data.get("access", {}) or {}).get(self._name)
        role_access = (data.get("role_access", {}) or {}).get(self._name)
        extra: dict[str, Any] = {}
        if note:
            extra["note"] = note
        if access:
            extra["access"] = access
        if role_access:
            extra["role_access"] = role_access
        if not info:
            return extra or None
        extra.update(
            {
                "error_code": info.get("code"),
                "error_text": info.get("text"),
            }
        )
        return extra

    async def async_update(self) -> None:
        await self._coordinator.async_request_refresh()


class HomesideCombinedBinarySensor(BinarySensorEntity):
    """Binary sensor that combines multiple variables into one."""
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        config: VariableConfig,
        device_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._config = config
        self._name = config.name
        self._device_id = device_id
        self._attr_unique_id = f"homeside_combined_binary_{config.key.replace(':', '_').replace('/', '_')}"

    @property
    def name(self) -> str | None:
        return self._name

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
        data = self._coordinator.data or {}
        value = data.get("value")
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        # Try to convert to bool
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'on', 'yes')
        return bool(value)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
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
        await self._coordinator.async_request_refresh()


def _load_variable_configs() -> list[VariableConfig]:
    if not _VARIABLES_FILE.exists():
        return []

    try:
        raw = json.loads(_VARIABLES_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOGGER.warning("Failed to read variables mapping: %s", exc)
        return []

    default_role_access = raw.get("role_access_default") or "Guest"

    configs: list[VariableConfig] = []
    for key, info in (raw.get("mapping") or {}).items():
        if not key or not isinstance(key, str):
            continue
        if not isinstance(info, dict):
            _LOGGER.debug("Skipping %s: config must be an object", key)
            continue
        
        address = info.get("address")
        if not address or not isinstance(address, list):
            _LOGGER.debug("Skipping %s: address is required and must be a list", key)
            continue
        
        name = str(info.get("name") or key)
        enabled = bool(info.get("enabled", False))
        vtype = str(info.get("type") or "sensor")
        note = info.get("note")
        access = info.get("access")
        role_access = info.get("role_access") or default_role_access
        format_template = info.get("format")
        
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
            )
        )
    return configs
