# HomeSide för Home Assistant

Integration för HomeSide-värmesystem. Övervakning via WebSocket.

Lägg till i HACS → Installera → Ange IP-adress.

- `sensor.homeside_tappvv` - Hot water temperature
- `sensor.homeside_vs1_framledning` - VS1 supply temperature
- `sensor.homeside_vs1_retur` - VS1 return temperature
- `sensor.homeside_utetemperatur` - Outdoor temperature
- `sensor.homeside_fjarvarme_tillopp` - District heating inlet

### Status Sensors
- `sensor.homeside_tryck` - Expansion tank pressure
- `sensor.homeside_vs1_pump_lage` - VS1 pump mode (0=Off, 1=On, 2=Auto)
- `sensor.homeside_vs1_shunt_lage` - VS1 valve mode
- `sensor.homeside_fjarvarme_shunt_lage` - District heating valve mode

### Diagnostic Sensors
- `sensor.homeside_rum_1_rssi` - Room 1 wireless signal strength
- `sensor.homeside_utegivare_rssi` - Outdoor sensor signal strength
- `sensor.homeside_duc_version` - DUC firmware version
- `sensor.homeside_exoreal_version_*` - ExoReal version components

### Binary Sensors
- `binary_sensor.homeside_sommardrift` - Summer mode status
- `binary_sensor.homeside_tradlos_mottagare` - Wireless receiver status
- `binary_sensor.homeside_utegivare_status` - Outdoor sensor status
- `binary_sensor.homeside_rum_*_av_pa` - Room sensor enable/disable
- `binary_sensor.homeside_rumsgivare_*` - Room temperature sensor status

## Controls (Requires Authentication)

### Switches
- `switch.homeside_sommardrift` - Toggle summer/winter mode
- `switch.homeside_rum_*` - Enable/disable room sensors
- `switch.homeside_*_val` - Sensor selection switches

### Select Entities
- `select.homeside_vs1_pump` - VS1 pump mode (Från/Till/Auto)
- `select.homeside_vs1_shunt` - VS1 valve mode (0%/Manuell/Auto)
- `select.homeside_fjarvarme_shunt` - District heating valve (0%/Manuell/Auto)
- `select.homeside_vv1_ventil` - Hot water valve (0%/Manuell/Auto)

### Number Entities
- `number.homeside_rumstemperatur` - Desired room temperature
- `number.homeside_parallelforskjutning` - Room temperature offset
- `number.homeside_grundkurva_*` - Heating curve points

## License

This project is licensed under the MIT License - see LICENSE file for details.

## Disclaimer

This is an unofficial integration and is not affiliated with or endorsed by the manufacturer of HomeSide heating systems. Use at your own risk.
