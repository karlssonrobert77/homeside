"""Constants for the Homeside integration."""
import json
from pathlib import Path

DOMAIN = "homeside"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SHOW_DIAGNOSTIC = "show_diagnostic"

# Options flow configuration keys
CONF_UPDATE_INTERVAL_FAST = "update_interval_fast"
CONF_UPDATE_INTERVAL_NORMAL = "update_interval_normal"
CONF_UPDATE_INTERVAL_SLOW = "update_interval_slow"
CONF_RECONNECT_DELAY = "reconnect_delay"
CONF_KEEPALIVE_INTERVAL = "keepalive_interval"

# Load diagnostic configuration at module level to avoid blocking I/O in event loop
def _load_diagnostic_config() -> dict:
    """Load diagnostic configuration from JSON file at module import time."""
    try:
        diagnostics_file = Path(__file__).resolve().parent / "diagnostics_config.json"
        with open(diagnostics_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"sensors": {}, "update_interval": 1800}

_DIAGNOSTIC_CONFIG = _load_diagnostic_config()
_DIAGNOSTIC_SENSORS_CACHE = _DIAGNOSTIC_CONFIG.get("sensors", {})
_DIAGNOSTIC_UPDATE_INTERVAL_CACHE = _DIAGNOSTIC_CONFIG.get("update_interval", 1800)

# Cache for none_value_default to avoid reading file multiple times
_NONE_VALUE_DEFAULT_CACHE = None


def get_none_value_default() -> int | float:
    """Get the default value for None returns from variables.json.
    
    This value is used when a variable read fails with error code 47 (dataconversion error).
    Cached after first read to avoid repeated file I/O.
    """
    global _NONE_VALUE_DEFAULT_CACHE
    
    if _NONE_VALUE_DEFAULT_CACHE is not None:
        return _NONE_VALUE_DEFAULT_CACHE
    
    try:
        variables_file = Path(__file__).resolve().parent / "variables.json"
        with open(variables_file, "r", encoding="utf-8") as f:
            root = json.load(f)
            _NONE_VALUE_DEFAULT_CACHE = root.get("none_value_default", 0)
            return _NONE_VALUE_DEFAULT_CACHE
    except Exception:
        # Fallback to 0 if file can't be read
        _NONE_VALUE_DEFAULT_CACHE = 0
        return 0

WS_PATH = "/_EXOsocket/"

PLATFORMS = ["sensor", "binary_sensor", "number", "switch", "select"]

# Update intervals in seconds
UPDATE_INTERVAL_FAST = 10  # Temperatures, pressures, active values
UPDATE_INTERVAL_NORMAL = 30  # Pump status, valve status, room sensors
UPDATE_INTERVAL_SLOW = 300  # Configuration, version info, calibration
UPDATE_INTERVAL_VERY_SLOW = 3600  # Static info like serial numbers


def get_diagnostic_update_interval() -> int:
    """Get diagnostic update interval from pre-loaded config.
    
    Config is loaded at module import time to avoid blocking I/O in event loop.
    
    Returns:
        Update interval in seconds (default: 1800)
    """
    return _DIAGNOSTIC_UPDATE_INTERVAL_CACHE


# Lazy-load diagnostic update interval (for backward compatibility)
UPDATE_INTERVAL_DIAGNOSTIC = None


def _ensure_diagnostic_interval_loaded():
    """Ensure UPDATE_INTERVAL_DIAGNOSTIC is loaded."""
    global UPDATE_INTERVAL_DIAGNOSTIC
    if UPDATE_INTERVAL_DIAGNOSTIC is None:
        UPDATE_INTERVAL_DIAGNOSTIC = get_diagnostic_update_interval()

# Session level to role mapping (shared with CLI)
SESSION_LEVEL_ROLES = {
    0: "None",
    1: "Guest",
    2: "Operator",
    3: "Service",
    4: "Admin",
}

# Role hierarchy - each level can access itself and all lower levels (shared with CLI)
ROLE_HIERARCHY = ["None", "Guest", "Operator", "Service", "Admin"]

# Sensor update groups by variable name patterns
FAST_UPDATE_PATTERNS = [
    "temp",
    "temperatur",
    "tryck",
    "pressure",
    "bar",
    "framledning",
    "retur",
    "tapp",
]

NORMAL_UPDATE_PATTERNS = [
    "pump",
    "ventil",
    "valve",
    "shunt",
    "status",
    "drift",
    "läge",
    "rum",
    "room",
    "mottagning",
    "rssi",
]

SLOW_UPDATE_PATTERNS = [
    "kalibrering",
    "calibration",
    "kurv",
    "curve",
    "börvärde",
    "setpoint",
    "sommardrift",
    "val",
    "gräns",
    "limit",
]

VERY_SLOW_UPDATE_PATTERNS = [
    "version",
    "serial",
    "id",
    "fc-nr",
    "latitud",
    "longitud",
    "sekund",
]

def get_diagnostic_sensors() -> dict:
    """Get diagnostic sensor configurations from pre-loaded config.
    
    Config is loaded at module import time to avoid blocking I/O in event loop.
    
    Returns:
        Dictionary with diagnostic sensor configurations
    """
    return _DIAGNOSTIC_SENSORS_CACHE


# Lazy-load diagnostic sensors (for backward compatibility)
DIAGNOSTIC_SENSORS = None


def _ensure_diagnostic_sensors_loaded():
    """Ensure DIAGNOSTIC_SENSORS is loaded."""
    global DIAGNOSTIC_SENSORS
    if DIAGNOSTIC_SENSORS is None:
        DIAGNOSTIC_SENSORS = get_diagnostic_sensors()

# EXOsocket Error Codes
ERROR_CODES = {
    0: "OK",
    1: "Wrong data type",
    2: "Illegal Text variable load number",
    3: "Illegal load number",
    4: "Illegal Task load number",
    5: "It does not exist",
    6: "It already exists",
    7: "The DPac does not exist",
    8: "The DPac is used by Task(s)",
    9: "The Task does not exist",
    10: "The Task already exists",
    11: "Wrong loading order",
    12: "The Task is already installed",
    13: "The Task is running",
    14: "The Task is already running",
    15: "The Task is not running",
    16: "The Task is not installed",
    17: "The command StepT is not allowed",
    18: "The Text variable already exists",
    19: "The variable does not exist",
    20: "The memory of the controller is full",
    21: "(The text is empty)",
    22: "The text string is too long. It has been truncated!",
    23: "Illegal access level",
    24: "Illegal access level",
    25: "Illegal parameter value",
    26: "Wrong password",
    27: "Reserved error code (0x1B)",
    28: "Access denied",
    29: "The maximum length is too large",
    30: "Internal error on hardware device",
    31: "Reserved error code (0x1F)",
    32: "The procedure Task is used by other Task(s)",
    33: "The Text variable memory is full",
    34: "The Task is not in step mode",
    35: "(The data is empty)",
    36: "Reserved error code (0x24)",
    37: "Illegal address",
    38: "Illegal command",
    39: "Wrong message length",
    40: "Data too large",
    41: "Address outside range",
    42: "Wrong file format",
    43: "Not allowed",
    44: "Internal error (inconsitent tables)",
    45: "It is busy for the moment",
    46: "Too many break points",
    47: "Dataconversion error",
    100: "Data invalid",
    193: "No Answer",
    194: "Internal error",
    195: "The configured communication channel does not exist",
    196: "Wrong checksum or incorrect answer syntax",
    197: "The configured serial port does not exist",
    198: "Can not get access to the configured serial port",
    199: "The configured serial port is used by something else",
    200: "CTS not received",
    201: "No response from the configured IP address",
    202: "The device with the configured IP address does not support EXOline communication",
    203: "Serious TCP/IP error. Check the network installation and configuration",
    204: "No configured route for this EXOline address",
    205: "The modem is not connected",
    206: "End-of-Message not received",
    207: "Received message is too long",
    208: "Parity or format error",
    209: "The serial port is jammed",
}
