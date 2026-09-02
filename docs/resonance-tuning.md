# Resonance / Input Shaping — V1

The V1 assistant uses the toolhead-mounted MPU6050 to calibrate Marlin's native Input Shaping frequency without creating a second motion controller.

## Safety gates

The test only starts when:

- no print is active or paused;
- no planner motion is queued;
- the MPU has valid live data;
- the selected axis and Z have been homed;
- current Z is at least 5 mm above the bed;
- there is enough travel around the current position.

The test temporarily disables shaping only after the planner is synchronized. If the MPU cannot actually enter capture mode / widen its DLPF, the axis is returned without applying the broadband impulse. It performs a bounded ±5 mm reversal, returns the axis to its original position, restores the previous shaping value, and only then evaluates whether a new value should be accepted.

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
