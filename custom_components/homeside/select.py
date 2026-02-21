from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any
from datetime import timedelta

from homeassistant.components.select import SelectEntity
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
    options: list[str] | None = None
    values: list[int] | None = None


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
        options = info.get("options")
        values = info.get("values")
        
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
                options=options,
                values=values,
            )
        )
    
    return configs


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Homeside selects from a config entry."""
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
    # Create select entities from variables with type="select"
    select_configs = [
        cfg for cfg in variable_configs
        if cfg.enabled and cfg.type == "select" and cfg.options and cfg.values
        and (not cfg.role_access or cfg.role_access in allowed_roles)
    ]
    
    if not select_configs:
        return
    
    entities = []
    
    # Create coordinator for select updates
    async def _update() -> dict[str, Any]:
        try:
            await client.ensure_connected()
            data = {}
            for cfg in select_configs:
                try:
                    value = await client.read_point(cfg.address[0])
                    if value is not None:
                        data[cfg.name] = value
                except Exception as e:
                    _LOGGER.debug(f"Error reading {cfg.address[0]}: {e}")
            return data
        except ConnectionError as err:
            _LOGGER.warning("Homeside connection error while updating selects: %s", err)
            return {}
        except Exception as err:  # pragma: no cover - defensive
            _LOGGER.exception("Unexpected error while updating selects: %s", err)
            return {}

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="homeside_selects",
        update_method=_update,
        update_interval=timedelta(seconds=UPDATE_INTERVAL_NORMAL),
    )

    await coordinator.async_config_entry_first_refresh()

    entities = [
        HomesideSelect(coordinator, client, device_id, cfg)
        for cfg in select_configs
    ]

    async_add_entities(entities)
    _LOGGER.info(f"Added {len(entities)} Homeside select entities")


class HomesideSelect(CoordinatorEntity, SelectEntity):
    """Representation of a Homeside select entity (mode selector)."""

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        client: HomesideClient,
        device_id: str,
        config: VariableConfig,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self._client = client
        self._device_id = device_id
        self._config = config
        self._name = config.name
        self._attr_name = f"Homeside {config.name}"
        self._attr_unique_id = f"homeside_{config.key.replace(":", "_").replace("/", "_")}"
        self._attr_options = config.options or []

    @property
    def device_info(self):
        from .const import DOMAIN
        return {
            "identifiers": {(DOMAIN, self._device_id)},
        }

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        value = self.coordinator.data.get(self._name)
        # Try to get error info if available
        errors = getattr(self.coordinator, 'data', {}).get('errors', {}) if hasattr(self.coordinator, 'data') else {}
        error = errors.get(self._name) if errors else None
        if error and error.get("code") == 47 and value is None:
            value = get_none_value_default()
        if value is None:
            return None
        # Map numeric value to option string
        try:
            idx = self._config.values.index(int(value))
            return self._config.options[idx]
        except (ValueError, IndexError, AttributeError):
            return None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        try:
            idx = self._config.options.index(option)
            value = self._config.values[idx]
            
            await self._client.write_point(self._config.address[0], value)
            await self.coordinator.async_request_refresh()
        except (ValueError, AttributeError):
            _LOGGER.error(f"Invalid option {option} for {self._config.address[0]}")
