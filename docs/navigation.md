# JOG and Menu Navigation

## Physical RC mapping

| RC time | Physical direction |
|---:|---|
| `<60 us` | DOWN |
| `60..219 us` | UP |
| `220..899 us` | RIGHT |
| `900..5199 us` | LEFT |
| neutral cutoff / timeout | NONE |

## UI context rules

The physical direction is context-aware instead of being blindly mapped to a rotary encoder.

### Normal list / file browser

- UP: previous item
- DOWN: next item
- LEFT: back
- RIGHT: select / enter
- CENTER: select / confirm

### Two-choice confirmation

- LEFT: choose left option
- RIGHT: choose right option
- CENTER: confirm highlighted option
- UP/DOWN: silent no-op for choice selection (no beep or redraw)

### Numeric / edit screens

- LEFT: decrease
- RIGHT: increase
- CENTER: confirm and leave edit mode
- UP/DOWN: silent no-op while editing (no beep or redraw)

## Hold acceleration

All four directions now share the same hold-repeat engine. A direction begins repeating after 320 ms. The repeat interval is 110 ms initially, 75 ms after one second, and 45 ms after 2.5 seconds. This applies equally to LEFT, RIGHT, UP, and DOWN.

## Center-key standby gesture

A short center-key press is emitted as ENTER only after release. Holding the center key for five seconds is reserved for logical power control:

- while awake and fully idle: enter standby;
- while in standby: wake the interface;
- during printing, pause state, queued motion, or with a hotend/bed target above zero: standby is refused and the long press is consumed.

V1 boots awake. Standby leaves the MCU powered so the key can wake the interface; the LCD/backlight is off and the red status LED remains on. Standby never clears the G-code queue. If work is queued from serial, SD or an internal command source, V1 wakes the interface automatically and then lets Marlin process the command normally.

## V1 menu behavior

V1 follows Marlin's native menu hierarchy. A setting should have one primary location rather than being mirrored into a second KP3S tree.

- Reversible boolean/numeric settings edit in place and return with CENTER.
- Exclusive choices such as an MPU address role apply, persist and return to the previous menu immediately.
- Destructive Restore Defaults uses a two-choice confirmation screen.
- BLTouch actions are available only when the runtime probe is enabled and the machine is idle.
- MPU setup, diagnostics and live data are unavailable while printing or while normal planner motion is active. If a job starts while a live IMU screen is already open, V1 exits that screen automatically so stale data is never presented as live.
- Long labels scroll only inside the field that owns them. Two-choice prompts keep left and right labels in separate half-screen fields.

## Menu hierarchy

The V1 tree is intentionally shallow and follows Marlin's native categories:

- Main: SD / files first, Motion, Probe / Level, Filament, Temperature, Configuration, Info.
- Configuration: Advanced Settings, BLTouch runtime/tools, a single Display submenu (brightness/contrast/timeout/180° inversion/language), Firmware Retract, filament runout, MPU6050 / IMU, Power-loss Recovery, EEPROM actions.
- Advanced Settings > Input Shaping: native manual shaping controls plus `Auto Resonance`.
- MPU6050 / IMU: Devices / Wiring, Bed IMU, Toolhead IMU, Diagnostics. Role-specific pages appear only when that role is assigned.
- Info > Printer Info: native Marlin information plus the KP3S V1 identity / author.

EEPROM Save / Load / Restore appears only in Configuration. Probe / Level does not duplicate storage actions. Restore Defaults and Clear Level Zero require confirmation.
