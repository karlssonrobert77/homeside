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
    address: str
    name: str
    enabled: bool
    type: str
    note: str | None = None
    access: str | None = None
    role_access: str | None = None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client: HomesideClient = hass.data[DOMAIN][entry.entry_id]["client"]

    variable_configs = _load_variable_configs()
    binary_configs = [cfg for cfg in variable_configs if cfg.enabled and cfg.type == "binary_sensor"]
    if not binary_configs:
        return

    # Group binary sensors by update interval
    fast_sensors = []
    normal_sensors = []
    slow_sensors = []
    very_slow_sensors = []
    
    for cfg in binary_configs:
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
            
        variables = [cfg.address for cfg in group_configs]
        name_by_address = {cfg.address: cfg.name for cfg in group_configs}
        note_by_address = {cfg.address: cfg.note for cfg in group_configs}
        access_by_address = {cfg.address: cfg.access for cfg in group_configs}
        role_by_address = {cfg.address: cfg.role_access for cfg in group_configs}

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
            HomesideVariableBinarySensor(variables_coordinator, cfg.name)
            for cfg in group_configs
        )
    
    async_add_entities(entities)


class HomesideVariableBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        name: str,
    ) -> None:
        self._coordinator = coordinator
        self._name = name
        self._attr_unique_id = f"homeside_var_{name}"

    @property
    def name(self) -> str | None:
        return self._name

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
    for address, info in (raw.get("mapping") or {}).items():
        if not address or not isinstance(address, str):
            continue
        if ":" not in address:
            _LOGGER.debug("Skipping %s: address must be device:item format", address)
            continue
        if not isinstance(info, dict):
            _LOGGER.debug("Skipping %s: config must be an object", address)
            continue
        name = str(info.get("name") or address)
        enabled = bool(info.get("enabled", False))
        vtype = str(info.get("type") or "sensor")
        note = info.get("note")
        access = info.get("access")
        role_access = info.get("role_access") or default_role_access
        configs.append(
            VariableConfig(
                address=address,
                name=name,
                enabled=enabled,
                type=vtype,
                note=note,
                access=access,
                role_access=role_access,
            )
        )
    return configs
