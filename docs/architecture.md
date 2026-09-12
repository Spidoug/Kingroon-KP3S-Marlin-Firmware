# Architecture

V1 is generated from Marlin 2.1.3-b3 plus the official Kingroon KP3S configuration. `firmware/build_firmware.py` generates one maintained firmware tree.

The Nokia 5110 uses a dedicated PCD8544 bit-bang transport and runtime 180-degree rotation. The Samsung panel provides four-way navigation, CENTER, IR and LED. Mechanical Z-min remains PA11, BLTouch remains PA8 + PC4, filament runout remains PA4, and the MPU software-I2C pair remains PD8/FFC16 + PD9/FFC17.

## Menu architecture

Marlin's native menu structure is the primary V1 UI structure. V1 does not create a parallel global settings tree. Screen-related controls are intentionally consolidated into one focused Display submenu so brightness, contrast, timeout, orientation and language have a single location.

V1 adds only four kinds of UI extensions:

- one dedicated Display submenu containing native screen controls, runtime 180-degree inversion and language selection;
- a dedicated MPU6050 / IMU submenu;
- Auto Resonance inside native Input Shaping;
- BLTouch runtime enable beside native BLTouch tools, plus the V1 information screen.

This keeps one path per setting and makes native Marlin terminology and behavior predictable.

## MPU architecture

The physical I2C pair can host two MPU6050 devices using the legal AD0 addresses 0x68 and 0x69. Persistent configuration assigns each address to bed, toolhead or unused. Each physical device has independent sample state, complementary filter, bias learning, vibration state, startup state and calibration.

The IMU is deliberately separated from the normal motion-critical path. No MPU6050 I2C transaction is permitted while a print is active or paused. Normal queued motion also blocks background sensor polling, recovery, detection and reconfiguration. Resonance capture is the sole explicit motion-plus-sampling calibration operation and aborts if a print job starts.

Marlin remains the only trajectory planner. The IMU is observational during idle operation and is used explicitly during resonance calibration. X resonance uses the toolhead sensor; Y uses the bed sensor.

BLTouch bed probing and MPU gravity/orientation assessment remain separate systems.

## Runtime state ownership

Persistent state includes display rotation, BLTouch enable, MPU enable/wiring, MPU address roles, independent bed/toolhead calibration and normal Marlin tuning values. Transient print classification, JOG repeat state, live IMU filters and diagnostic screens are session state.

The EEPROM identifier is `V01`, representing the V1 layout. `M500/M501/M502` remain blocked while the printer is active.

## High-temperature hotend profile

The generated project uses a coherent 340 °C hotend profile rather than merely raising a UI number. `TEMP_SENSOR_0` is Marlin table 61 (100k B3950, 350 °C), `HEATER_0_MAXTEMP` is 350 °C, and `HOTEND_OVERSHOOT` is 10 °C, yielding a 340 °C selectable target. Native Hotend Idle Timeout is enabled at 600 seconds above 180 °C and drops nozzle / bed targets to 0 °C after inactivity. This architecture assumes matching all-metal, heater, sensor, wiring and connector hardware.

## Generated-project safety validation

`build_firmware.py` validates custom modules and critical inherited Marlin protections. Generation fails if thermal protection, cold-extrusion prevention, the high-temperature sensor / maximum-temperature profile, idle-heater protection, required endstop routes, menu-organization invariants, dual-MPU isolation rules, compact confirmation layout or other V1 requirements disappear. Generated custom headers are checked for balanced preprocessor conditionals before PlatformIO starts.
