# Changelog

All notable changes to this project will be documented in this file.

## [1.4.1] - 2026-02-11

### Fixed
- **Critical Startup Fixes:**
  - Fixed `ValueError` regarding `entity_category` by using proper Enum values instead of strings across all platforms
  - Fixed `NameError: 'address' is not defined` in `select.py`
  - Fixed `AttributeError: 'list' object has no attribute 'replace'` in sensor and binary_sensor (correctly handling address lists now)
- Resolved integration crash on setup

## [1.4.0] - 2026-02-11

### Added
- **Decimal Precision Support** - New decimals field for controlling displayed precision
  - Added `decimals` field to variables.json for all entities
  - Temperature sensors automatically display with 2 decimal precision (e.g., 22.46°C)
  - Uses Home Assistant's `suggested_display_precision` attribute
  - Updated test scripts to format values with specified decimals
- **Combined Sensors** - New feature to combine multiple variables into a single entity
  - Support for all platforms: sensor, binary_sensor, number, switch, select
  - Custom formatting with Python format strings
  - Example: Version sensor combining product-major-minor-build into "3-7,1,15"
  - Extra state attributes showing source values and configuration
  - Full documentation in COMBINED_SENSORS.md
- ExoReal Version sensor (`sensor.homeside_exoreal_version`)
  - Combines 0:651, 0:648, 0:47, 0:50 into formatted version string
  - Individual version component sensors disabled (available in attributes)
- Test suite for combined sensor functionality
- VariableConfig dataclass across all platforms for consistency

### Changed
- **Architecture Restructure** - Complete variables.json redesign
  - Changed from address-based keys (e.g., "0:3") to descriptive keys (e.g., "Value_MOTTAGNING_RUM_10")
  - All entries now use descriptive keys from note or name fields
  - Address field changed to list format: `"address": ["0:3"]`
  - All entries have format field (single vars use `"{0}"`, combined use templates like `"{0}-{1}.{2}.{3}"`)
  - Field renamed: `combined_from` → `address` for clarity
  - Total 201 entries standardized with consistent structure
- **Number Limits Migration** - Moved hardcoded limits to JSON
  - Migrated 34 number entity limits from _NUMBER_LIMITS dict to variables.json
  - Added min, max, step fields directly in JSON configuration
  - Updated VariableConfig to include min/max/step fields
  - Removed hardcoded _NUMBER_LIMITS dictionary
- Updated all platform files with combined sensor support:
  - sensor.py - Full combined support with decimals (already implemented)
  - binary_sensor.py - Added combined support
  - number.py - Added combined support (read-only) and limits from JSON
  - switch.py - Added VariableConfig and combined support (read-only)
  - select.py - Added VariableConfig and combined support (read-only)
- Individual version sensors (0:651, 0:648, 0:47, 0:50) disabled by default
- Standardized variable loading across all platforms
- Updated test_variables.py to display values with decimal precision and work with new architecture

### Technical Details
- Combined entities for number, switch, and select are read-only
- All combined entities use coordinator pattern for efficient updates
- Source values available in entity attributes
- Format validation with error logging
- Number limits now centralized in variables.json with fallback defaults

### Documentation
- Added COMBINED_SENSORS.md with comprehensive examples
- Updated README.md with combined sensors section
- Added test_combined_sensors.py validation script
- Added test_decimals.py validation script
- Platform-specific documentation for each entity type

## [1.3.4] - 2026-02-09

### Added
- Brand logos and icons for Home Assistant and HACS
  - icon.svg, icon.png, icon@2x.png in custom_components/homeside/
  - logo.svg, logo.png, logo@2x.png in repository root
- Visual branding with house + flame + temperature theme

## [1.0.0] - 2026-02-07

### Added
- Initial release
- Full read-only monitoring without authentication
- 5 platforms: sensor, binary_sensor, number, switch, select
- 193 mapped variables (41 enabled by default)
- Temperature monitoring (outdoor, hot water, heating system)
- Pressure monitoring (expansion tank)
- Pump and valve status indicators
- RSSI wireless signal diagnostics
- System firmware version sensors
- Mode selectors for pumps/valves (Auto/Manual/Off)
- Room sensor control switches
- Summer/winter mode toggle
- Heating curve number entities
- HACS support
- Comprehensive documentation

### Features
- **Read Access**: 39/41 enabled variables readable without authentication
- **Write Access**: All control features require credentials
- **Auto-discovery**: Variables loaded from variables.json
- **Update Intervals**: Optimized by sensor type (10s-30min)
- **Error Handling**: Proper error codes with descriptive text
- **Diagnostics**: RSSI monitoring, version tracking

### Platforms
- **Sensor**: 15+ entities (temperatures, pressure, RSSI, versions)
- **Binary Sensor**: 3+ entities (status indicators)
- **Switch**: 18+ entities (room sensors, mode selections)
- **Select**: 5 entities (pump/valve mode selectors)
- **Number**: Heating curve adjustments (requires auth)

### Technical
- WebSocket communication via EXOsocket protocol
- AES encryption for authenticated sessions
- Async/await architecture
- Proper HA entity structure
- Update coordinators per sensor group
- Configurable via UI

### Documentation
- Complete README with examples
- HACS integration guide
- Automation examples
- Troubleshooting section
- Development guidelines

## [Future]

### Planned
- Climate platform for thermostat control
- Alarm monitoring sensors
- Water leak detection integration
- Service calls for advanced operations
- More comprehensive diagnostics
- Energy monitoring
- Historical data analysis

---

[1.0.0]: https://github.com/yourusername/homeside/releases/tag/v1.0.0
