# Kingroon KP3S V1 - Command and function validation matrix

This matrix separates **executed simulation** from **physical-machine verification required**. The 106 Python tests cover the generator, serial host, thermal profile selector and guarded command console. They do not imply that C++ modules, electronics, heaters or axes were operated.

## Host commands exercised using a virtual Marlin responder

| Command / operation | Offline check | Remaining requirement |
| --- | --- | --- |
| `M115` firmware identity/capabilities | Pass, including incorrect identity and missing capabilities | Real serial firmware response |
| `M27` idle/progress check | Pass, including unexpected, busy and completed status | Real SD/paused-job behavior |
| `M27 C` current SD filename | Pass; selected/paused files block upload | Confirm response from built firmware |
| `M28 B1` binary transfer mode | Pass in simulator | Real serial switch and sync |
| Binary SYNC/QUERY/OPEN/WRITE/CLOSE/ABORT | Pass: checksum, packet sizes, buffer, malformed ACK/resend, errors and close transition | Hardware serial transfer, corrupted link and SD write |
| `M23` select SD file | Pass: 8.3 conversion, success and failure | Real SD filesystem selection |
| `M24` start/resume print | Pass: sequencing, failed start, fast job completion, resume command | Actual print motion and resume |
| `M25` pause | Pass: monitored command dispatch | Actual paused motion state |
| `M524` abort | Pass: monitored command dispatch | Actual job cancellation |
| `M105` temperature status | Pass: monitored command dispatch | Verify both physical sensors |
| `M114` current position | Pass: monitored command dispatch | Compare real coordinates |
| `M155 S2` / `M155 S0` | Pass: telemetry enable/disable dispatch | Actual temperature auto-reports |
| `M154 S2` / `M154 S0` | Pass: telemetry enable/disable dispatch | Actual position auto-reports |
| `M27 S2` / `M27 S0` | Pass: telemetry enable/disable dispatch | Actual SD progress reports |
| `--upload-only` | Pass: no M23/M24 sent | Upload using physical board and SD |
| `--no-monitor`, `--list-ports`, serial CLI validation | Pass in mocks | USB/serial enumeration and permissions |

## Generator functions and Python utilities

| Group | Verification status |
| --- | --- |
| Input validators, cache paths, extraction traversal protection | Executed against fixtures; pass |
| Text and preprocessor anchor transformations | Executed against controlled files; pass |
| Native Marlin language supplement insertion | Executed against synthetic language namespaces; pass |
| Release-tree safety / menu / text invariants | Original static audit executed; pass |
| Firmware image size checks and SHA-256 | Executed against synthetic files; pass |
| Toolchain selection/version and build command dispatch | Simulated; pass |
| Full `patch_configuration()` on pinned Marlin C++ | Not executed: source not bundled |
| Full `verify_project()` on generated Marlin | Not executed: generation blocked by external dependencies |
| PlatformIO compiler, linker and board firmware output | Not executed |
| Actual download and dependency installation | Not executed; offline mocks only |


## Enhanced offline tests and still-pending firmware checks

| Function / command | Executed offline | What remains |
| --- | --- | --- |
| `--hotend-profile stock/high-temp` / temperature ceilings | Profile validation, CLI refusal for unsafe input, default/confirmation tests | Generate both real Marlin trees, compile, verify sensor and hotend |
| `--enable-arcs` / `--disable-arcs` | Argparse dispatch and expected config markers | Build and run G2/G3 jobs; check binary size |
| `M73`, `M114 D/R`, `M810-M813`, `M820` | Feature directives verified against exact pinned upstream source options; console dispatch tests | Compile and exercise each on real KP3S |
| `M420 V/S0/S1`, `G28` | Guarded command dispatch | Rehome after verifying mesh saved state and correct Z/endstops |
| `M104`, `M140`, `M106/M107`, `M220/M221`, `M900`, `M593`, `M290 P0`, `M86` | Strict parameter limits and expected command strings exercised | Actual heat, flow, fan and motion outcomes under supervision |
| `M303 E0`, `M112`, `M500/501/502`, `M524` | Confirmation gates, error handling, identity test and emergency-wire mock | Real physical response, timeout and safe shutdown behavior |
| Macros and G-code injection | Reject oversized, multiline, invalid-slot and invalid-ASCII macros; always require confirmation | Review each script before running; Marlin macro RAM behavior |
| Firmware JSON build manifest | Artifact fields verified in mocked builder and source | Actual binary and hash from a successful PlatformIO compilation |

No firmware binary was produced by these offline checks. Tests do not validate thermistor accuracy, electrical isolation, cooling, board flash compatibility or mechanical collision safety.

## Physical commands and menu functions awaiting real hardware

All tests in this section are **PENDING**, not passed.

| Subsystem | Recommended supervised validation | Risk / prerequisite |
| --- | --- | --- |
| Motherboard and bootloader | Board revision, STM32 marking, pinout and correct flashing filename | Wrong image can make the printer unbootable |
| Power-up and Nokia 5110 LCD | Startup, status, brightness, rotation, timeout, multilingual menus, navigation | Confirm screen and Samsung controller pin compatibility |
| Samsung UE5000 controls | Every button/action, long press, encoder/joystick, feedback LEDs and menus | Look for reversed or stuck inputs |
| Hotend thermistor + bed thermistor | `M105` ambient plausibility before enabling heaters; sensor change response | Wrong thermistor table can defeat protection |
| Hotend heater and bed heater | Low safe target tests, controlled PID setup, thermal fault protection, fan control | Do not exceed verified hardware ratings or test unattended |
| Endstops | `M119` check each switch individually before any homing | Wrong endstop polarity can cause crashes |
| X/Y/Z/E motors | Direction, steps, travel limits, movement and extrusion behavior; `G28` only after endstop checks | Keep axes clear of obstructions |
| BLTouch | Detection, deploy/stow, trigger logic, enable/disable, probe offset and `G29` | Must match actual wiring and Z geometry |
| Filament runout | Trip/recover during a supervised test print | Must match switch polarity and position |
| MPU6050 (0x68, 0x69) | Both addresses, SDA/SCL configuration, roles, levels, vibration, temperature offsets, calibration | Inspect shared I2C electrical levels and bus wiring |
| Input Shaping / Auto Resonance | Manual parameters and automatic X/Y resonance calibration | Mechanical movement and accelerometer validation required |
| EEPROM and persistence | `M500`, `M501`, `M502`, saved display orientation, BLTouch state and MPU settings | Back up EEPROM; confirm write guard during printing |
| SD and USB printing | `M20`, `M23`, `M24`, `M25`, `M27`, `M524`, monitoring reconnects | Start with a short, supervised safe file |
| Generic serial printing | Stream typical `G0/G1`, `M104`, `M106/M107`, temperatures and print-state classification | Real parser, queue and machine timing required |
| Shutdown, power recovery and fault behavior | Power cycling, controlled fault response and `M112` emergency stop | Keep access to power disconnect and recovery firmware |
| End-to-end long print | Pause/resume/cancel, fan and thermal stability, motion accuracy, logging | Only after previous gates pass |

## Safe practical sequence

1. Identify and photograph the motherboard, display, thermistor/hotend and any optional probe or MPU wiring. Confirm the configured board and full temperature hardware profile before building.
2. Build the real Marlin C++ firmware on a host that can download the pinned dependencies. Resolve all warnings and compiler/linker errors. Check the generated BIN and SHA-256.
3. Prepare a recovery path and flash only a board-matched image. On first boot, keep heaters disabled and mechanically dangerous motions avoided until sensors and endstops have been checked.
4. Execute the hardware validation table under direct supervision, starting with read-only status commands and low-risk electrical tests.
5. Only then perform test prints and more advanced calibration. Preserve logs of actual responses and any differences between simulation and hardware.
