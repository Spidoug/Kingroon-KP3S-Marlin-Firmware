# KP3S V1 enhanced firmware - practical capability map

This source release extends the existing KP3S V1 generator, custom Nokia 5110 menus, Samsung controller, and Marlin 2.1.3-b3 modules. It is **not** a precompiled firmware. The C++ tree and `.bin` must be produced with the pinned upstream source and PlatformIO. All newly added features must pass the generated-project validator and the actual flash-size guard before any board test.

## Build-time thermal profiles

| Choice | Table for temperature sensor 0 | Highest Marlin hotend setpoint | Hard firmware cutoff | Intended installation |
| --- | --- | ---: | ---: | --- |
| `stock` | Marlin table **1** | **235 C** | **250 C** | KP3S with the original-style matching thermistor and a hotend known to support the requested temperature |
| `high-temp` | Marlin table **61** | **340 C** | **350 C** | Verified 350 C-capable all-metal hotend, matching B3950 sensor, heating element, connectors and wiring |

The cutoff is not an operating temperature. Marlin subtracts the `HOTEND_OVERSHOOT` from `HEATER_0_MAXTEMP` to limit the selectable target. A firmware profile **does not** detect the installed hotend or prevent damage if the wrong thermistor/hotend is present. Verify hardware physically and never rely only on a software cutoff. The stock-profile 235 C limit is conservative, but even this temperature may be unsuitable for some PTFE-lined installations.

* Windows: run `firmware/BUILD_FIRMWARE.bat` and choose profile 1 or 2.
* Ubuntu: run `./firmware/BUILD_FIRMWARE.sh` or `./firmware/BUILD_FIRMWARE.sh stock`.
* Non-interactive stock generation: `python3 firmware/build_firmware.py --generate-only --hotend-profile stock`.
* Non-interactive 340 C build: `python3 firmware/build_firmware.py --build --auto-toolchain --hotend-profile high-temp --confirm-high-temp-hardware` (only after real inspection).

The Python builder and interactive launchers read the same default hotend choice from `firmware/kp3s_project_config.py` (`stock` initially). Any high-temperature build requires explicit hardware acknowledgement. These are **mutually exclusive binaries**; changing the selected thermistor is a flash-time decision, not a G-code setting.

## Added Marlin features

| Capability | Implementation | Control |
| --- | --- | --- |
| Slicer-reported progress and ETA | `SET_PROGRESS_MANUALLY`, `M73_REPORT`; native P/R options | `M73 P50 R45`, `M73` |
| Detailed/current stepper positions | `M114_DETAIL`, `M114_REALTIME` | `M114 D`, `M114 R` |
| Persisted state of mesh enable after G28 | `RESTORE_LEVELING_AFTER_G28` | `M420 V`, `M420 S0/S1`; save the actual mesh with `M500` |
| Four custom on-device G-code macros | `GCODE_MACROS`, slots 0-3, 64 printable ASCII chars | `M810`-`M813`, `M820` |
| Curved G-code moves | `ARC_SUPPORT` retained from official Marlin base | `G2/G3`; `--disable-arcs` only to recover flash space |
| Guarded serial console | Independent Python application | `firmware/kp3s_console.py` or launchers |
| Build audit artifact | `KP3S_BUILD_PROFILE.json` and `BUILD_MANIFEST.json` | Inspect generated settings and flashed-image SHA-256 |

**Macros are not stored in EEPROM in this pinned Marlin source**; they disappear after restart. Defining, persisting or running a dangerous G-code sequence is the operator's responsibility. The console treats macro creation/execution as high-risk and requires explicit approval.

`RESTORE_LEVELING_AFTER_G28` restores the previous *enabled/disabled* leveling state. It does not measure or validate the mesh, enable the BLTouch hardware, or automatically level every time. Start the printer with a verified Z endstop and confirm the BLTouch wiring/trigger before executing `G29`.

## Already present in the source baseline

The existing V1 generator also builds the Nokia 84x48 UI, Samsung IR/control/feedback, 5 languages, optional BLTouch, bilinear leveling, filament-runout/pause, dual MPU6050 support, resonance-assisted native shaping, `M900`, firmware retract, Z-babystepping, PID controls, `M500` EEPROM, SD transfer, telemetry, host actions, `M486` object cancellation, emergency parser, thermal fault protections, power-loss recovery (off by default) and idle-hotend cooling. Those functions remain in place. Feature presence is **not** hardware certification.

## Protection policies

- The generated-tree validator fails for missing thermal protections, cold-extrusion protection, endstop routing, mismatched profile or a broken 340 C thermistor table.
- The generator explicitly keeps `USE_WATCHDOG` enabled and the validation rejects a missing hardware watchdog.
- The console rejects invalid, non-finite, out-of-range inputs and requires `--execute` before sending any write command. `--yes` is needed for hazardous actions.
- Targets above 235 C require both `--profile high-temp` and `--confirm-high-temp-hardware` in the console; this is a declared human assertion, not automatic detection.
- `M112` emergency stop is transmitted immediately with a specified serial port when explicitly commanded; it cannot be guaranteed if the USB link or printer is already unresponsive. Physical power isolation remains essential.
- Existing 10-minute hotend idle timeout at/above 180 C remains unchanged. Native thermal runaway, watchdog, and temperature checks remain essential and must be verified on actual hardware.
- The application binary cannot exceed the STM32F103VE application flash region. If the build exceeds it, `--disable-arcs` is an available trade-off **only** for slicers that never output G2/G3. Do not weaken thermal protection to save space.

## Not automatically safe or validated

No claim is made that the amended Marlin C++ builds or fits until PlatformIO finishes with the pinned libraries. No physical operations were run in the authoring environment. Confirm the actual pin assignments, printer geometry, firmware memory usage, screen, motors, heating system, BLTouch, runout, SD, MPU and all emergency behavior on the target KP3S, one subsystem at a time. See `test-matrix.md`.
