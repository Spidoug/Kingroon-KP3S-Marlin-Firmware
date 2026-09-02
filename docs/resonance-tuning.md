# Resonance / Input Shaping — V1

The V1 assistant uses the toolhead-mounted MPU6050 to calibrate Marlin's native Input Shaping frequency without creating a second motion controller.

## Safety gates

The test only starts when:

- no print is active or paused;
- no planner motion is queued;
- the MPU has valid live data.

The assistant then prepares the machine automatically: it runs a fresh full `G28`, confirms X/Y/Z are homed, raises Z to 10 mm, disables bed leveling temporarily, moves the tested axis to a safe central window and disables shaping only for the measurement. The ±5 mm broadband reversal is queued instead of executed as two blocking moves, so the main loop can service the MPU explicitly at about 200 Hz while the stepper ISR performs the motion. Capture continues through the ring-down until the 192-sample buffer is full or a bounded timeout is reached.

If homing, safe-Z preparation or MPU capture fails, no new shaping value is applied. The previous shaping frequency and the previous bed-leveling state are restored before returning. After a valid test the axis returns to the safe test center and only then is the new result considered for application.

## Measurement

- Capture target: 200 Hz, maximum 192 samples.
- Search band: 20-80 Hz.
- Normal MPU DLPF: configuration 3 (~44 Hz accelerometer / ~42 Hz gyroscope).
- During resonance capture only: configuration 2 (~94 Hz accelerometer / ~98 Hz gyroscope), restored immediately after capture.
- Frequency analysis: Bartlett-windowed Goertzel 1 Hz scan followed by 0.25 Hz refinement around the strongest response. Noise confidence excludes ±2 Hz around the winning peak.

All three accelerometer axes contribute to the spectral score so the result is less sensitive to the physical orientation of the MPU board.

## Confidence and application

- X: minimum 45% confidence. The MPU is attached to the toolhead, so X is the preferred/direct measurement.
- Y: minimum 60% confidence. On the KP3S the bed moves in Y while the MPU is on the toolhead, so Y is an indirect frame-transmitted measurement.
- A rejected or failed measurement never changes Input Shaping.
- An accepted result calls Marlin's native `stepper.set_shaping_frequency()` and saves the normal Marlin settings to EEPROM. The UI only reports `APPLIED+SAVED` if that save succeeds; otherwise shaping stays active for the session and the screen reports the save failure.
- The existing damping ratio is intentionally preserved in V1.

The test must be rerun after meaningful mechanical changes such as belt tension, toolhead mass, frame changes, or motor/pulley changes.
