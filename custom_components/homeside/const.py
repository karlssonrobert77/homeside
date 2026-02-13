DOMAIN = "homeside"

CONF_HOST = "host"
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SHOW_DIAGNOSTIC = "show_diagnostic"

WS_PATH = "/_EXOsocket/"

PLATFORMS = ["sensor", "binary_sensor", "number", "switch", "select"]

# Update intervals in seconds
UPDATE_INTERVAL_FAST = 10  # Temperatures, pressures, active values
UPDATE_INTERVAL_NORMAL = 30  # Pump status, valve status, room sensors
UPDATE_INTERVAL_SLOW = 300  # Configuration, version info, calibration
UPDATE_INTERVAL_VERY_SLOW = 3600  # Static info like serial numbers
UPDATE_INTERVAL_DIAGNOSTIC = 1800  # System diagnostics (30 minutes)

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

# Diagnostic sensor configurations
DIAGNOSTIC_SENSORS = {
    "heap_available": {
        "name": "Heap Memory Available",
        "unit": "bytes",
        "icon": "mdi:memory",
        "device_class": None,
        "state_class": "measurement",
    },
    "heap_used": {
        "name": "Heap Memory Used",
        "unit": "bytes",
        "icon": "mdi:memory",
        "device_class": None,
        "state_class": "measurement",
    },
    "heap_max": {
        "name": "Heap Memory Max Used",
        "unit": "bytes",
        "icon": "mdi:memory",
        "device_class": None,
        "state_class": "measurement",
    },
    "heap_errors": {
        "name": "Heap Memory Errors",
        "unit": "errors",
        "icon": "mdi:alert-circle",
        "device_class": None,
        "state_class": "total_increasing",
    },
    "exoline_sessions_active": {
        "name": "EXOline Active Sessions",
        "unit": "sessions",
        "icon": "mdi:connection",
        "device_class": None,
        "state_class": "measurement",
    },
    "external_connection": {
        "name": "External Connection IP",
        "unit": None,
        "icon": "mdi:wan",
        "device_class": None,
        "state_class": None,
    },
    "modbus_sessions_active": {
        "name": "Modbus Active Sessions",
        "unit": "sessions",
        "icon": "mdi:connection",
        "device_class": None,
        "state_class": "measurement",
    },
    "bacnet_version": {
        "name": "BACnet Version",
        "unit": None,
        "icon": "mdi:information",
        "device_class": None,
        "state_class": None,
    },
    "bacnet_device_id": {
        "name": "BACnet Device ID",
        "unit": None,
        "icon": "mdi:identifier",
        "device_class": None,
        "state_class": None,
    },
}

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
