# Firmware V1

V1 is a single clean implementation generated from Marlin 2.1.3-b3.

## Menu organization

V1 uses Marlin's native hierarchy as the primary navigation model. Features are not duplicated under a separate KP3S setup tree.

### Main menu

SD / file selection is forced to the top of the main menu so the normal workflow is power-on → choose file → print. Language is not duplicated here; it lives inside the dedicated Display submenu under Configuration.

### Configuration

The native Marlin order is preserved and V1 additions are placed beside the feature they belong to:

- Native `Advanced Settings` remains the main motion / temperature / extrusion tuning area.
- `BLTouch On` sits beside Marlin's native BLTouch tools.
- `Display` is the single screen-settings submenu. It contains native brightness / contrast / timeout controls, `Rotate LCD 180`, and `Language`. The inversion flips the complete Nokia UI by 180 degrees, applies immediately, and is EEPROM-backed. It is editable only while the machine is idle. Language selection returns to `Display` after applying.
- Native Firmware Retract and filament runout controls remain in `Configuration`.
- `MPU6050 / IMU` sits beside the sensor controls.
- Native Power-loss Recovery remains in its standard location.
- EEPROM Save / Load appear only here; Restore Defaults requires confirmation.
- Firmware identity is consolidated into Marlin's native `Info > Printer Info` screen; Configuration contains only configurable items.

### Advanced Settings > Input Shaping

Marlin's manual shaping frequency and damping controls remain unchanged. V1 adds `Auto Resonance` inside this menu so automatic measurement and manual shaping settings live together.

### BLTouch

`BLTouch On` is placed directly beside Marlin's native BLTouch tools. When disabled, G29 and probe deployment remain blocked. The native Probe / Level screen shows `BLTouch OFF`, hides automatic `Level Bed` and the Probe Offset Wizard, but keeps manual bed tramming available. While the machine is busy, the runtime toggle and BLTouch actions are unavailable.

### MPU6050 / IMU

The root contains only four logical destinations:

- `Devices / Wiring` — enable state, SDA/SCL swap and roles for 0x68 / 0x69.
- `Bed IMU` — appears only after a Bed role is assigned and the MPU subsystem is enabled.
- `Toolhead IMU` — appears only after a Toolhead role is assigned and the MPU subsystem is enabled.
- `Diagnostics` — device detection and I2C bus test; appears only while the MPU subsystem is enabled.

Each role menu contains `Level`, `Vibration`, `Temperature` and `Calibration`. Calibration contains level-zero and temperature-offset controls. Choosing an MPU role applies, saves and returns immediately because role assignment is a selection, not a repeatable action.

## MPU influence on printing

The software-I2C MPU subsystem performs **zero sensor transactions while a print is active or paused**. Background acquisition is also suspended whenever normal planner motion is queued, keeping sensor latency, retries and bus recovery out of the motion-critical path.

Polling, recovery, detection and reconfiguration resume only after the printer returns to a motion-idle state.

The resonance assistant remains an explicit calibration operation. X requires the MPU assigned to the toolhead; Y requires the MPU assigned to the bed. Accepted frequencies are applied through Marlin's native Input Shaping.

## Compact display text

Long menu and edit labels retain the selected-item marquee inside their reserved field. Two-choice confirmation screens use isolated half-screen fields on the Nokia 84x48 display, so labels such as Cancel / Print cannot draw over one another. Long choices are clipped to their own field and only the selected choice scrolls.
## High-temperature hotend

V1 uses a dedicated high-temperature hotend profile with a maximum selectable target of **340 °C**. The generated Marlin configuration uses `TEMP_SENSOR_0 61`, `HEATER_0_MAXTEMP 350` and `HOTEND_OVERSHOOT 10`. This combination is intentional: Marlin subtracts the overshoot reserve from the hard maximum when calculating the highest permitted target, giving 350 - 10 = 340 °C.

This profile requires real high-temperature hardware: an all-metal hotend, heater cartridge, thermistor, wiring and connectors rated for at least 350 °C. Marlin table 61 is for a 100k B3950 Formbot / Vivedino-style 350 °C thermistor. The original KP3S table-1 sensor is not valid for this range.

Native `Hotend Idle Timeout` is enabled with a 10-minute timeout above 180 °C. If extrusion remains inactive for that period, the firmware commands nozzle and bed targets to 0 °C. The setting remains visible through Marlin's native Configuration menu.

After installing or changing the high-temperature hotend hardware, validate ambient temperature readings and run PID autotune at a representative operating temperature before printing.

