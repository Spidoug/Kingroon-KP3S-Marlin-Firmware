# Resonance / Input Shaping — V1

The V1 assistant uses the configured MPU6050 roles to calibrate Marlin's native Input Shaping frequency without becoming a second motion controller.

Menu path: `Configuration > Advanced Settings > Input Shaping > Auto Resonance`.

## Sensor selection

- X uses the MPU assigned to `Toolhead / Extrusora`.
- Y uses the MPU assigned to `Bed / Mesa`.
- The required role must be configured and have valid data before the test starts.

Direct X and Y measurements use the same confidence threshold. V1 does not substitute the other sensor when the required role is missing.

## Safety gates

The test only starts when no print is active or paused, no planner motion is queued, and the required MPU has valid live data. The assistant runs a fresh `G28`, verifies X/Y/Z, raises Z to 10 mm, temporarily disables leveling, moves to a safe central window and disables shaping only for the measurement.

The ±5 mm broadband reversal is queued so the stepper ISR performs motion while the firmware services a bounded ~200 Hz IMU capture.

If homing, safe-Z preparation, sensor capture or analysis fails, no new shaping value is applied. The previous shaping frequency and leveling state are restored before returning.

## Measurement

- capture target: 200 Hz, up to 192 samples;
- search band: 20-80 Hz;
- normal MPU DLPF: configuration 3;
- capture MPU DLPF: configuration 2, restored afterward;
- analysis: Bartlett-windowed Goertzel scan with 0.25 Hz local refinement.

All three accelerometer axes contribute to the spectral score, reducing sensitivity to the physical orientation of the MPU board.

An accepted result calls Marlin's native `stepper.set_shaping_frequency()` and saves through normal Marlin settings. The MPU does not modify individual G0/G1 moves in real time.
