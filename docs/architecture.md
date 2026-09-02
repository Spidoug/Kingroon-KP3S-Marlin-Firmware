# Architecture

V1 is generated from Marlin 2.1.3-b3 plus the official Kingroon KP3S configuration. `firmware/build_firmware.py` generates the V1 Marlin tree directly; the repository does not ship alternate firmware branches.

The Nokia 5110 uses a dedicated PCD8544 bit-bang transport and runtime 180-degree rotation. The Samsung panel provides four-way navigation, CENTER, IR and LED. Logical standby remains firmware-only and is guarded against printing, queued motion and active heater targets. It is not a command-discard state: if new G-code becomes queued while asleep, the panel/runtime state wakes before normal queue execution.

Hardware roles remain fixed: mechanical Z-min PA11, BLTouch PA8 + PC4, filament PA4, MPU physical pair PD8/FFC16 + PD9/FFC17. The MPU's logical SDA/SCL roles can be swapped and persisted from the LCD.

## Motion architecture

Marlin remains the only trajectory planner. The MPU has two motion roles:

- continuous observation: fused level and vibration telemetry;
- explicit calibration: a resonance assistant measures a short broadband ring-down and sets the native Marlin Input Shaping frequency when confidence is sufficient.

The resonance assistant never starts while the printer is active. It temporarily disables shaping only for the tested idle calibration move, restores the old value, evaluates the capture, and only then applies a successful frequency. X is direct at the toolhead; Y is indirect and confidence-gated more strictly.

BLTouch bed probing and MPU gravity-level assessment remain separate systems.


## Runtime state ownership

V1 separates persistent machine configuration from transient session state. Display rotation, BLTouch runtime enable, MPU enable/wiring and IMU calibration are EEPROM-backed. Print/pause classification, JOG repeat state, transient UI screens and IMU live filters are session state and are rebuilt as needed. `M502` restores V1 runtime hardware defaults before a later `M500` can persist them again.

The serial print-state helper is deliberately classification-only. It normalizes lowercase G-code, removes comments/checksums and keeps an inferred stream active for up to five minutes of legitimate job inactivity. It does not plan motion or replace Marlin's SD/host state machines.

## Generated-project safety contract

`build_firmware.py` validates both V1 custom modules and critical inherited Marlin protections. A generated tree is rejected if thermal protection for hotend/bed, cold-extrusion prevention, X/Y/Z minimum endstop inputs, or configured heater/bed temperature bounds disappear. Custom generated headers are also checked for balanced preprocessor conditionals before PlatformIO starts. EEPROM-mutating `M500/M501/M502` follow the same idle-only rule as the Storage menu, so settings cannot be loaded/reset beneath an active print.
