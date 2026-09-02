# Firmware V1

V1 is a single clean implementation generated from Marlin 2.1.3-b3.

## Runtime menu

`Configuration > KP3S Setup`

- `Display`
  - `Rotate 180`
  - contrast
  - display timeout
- `Motion / Tuning`
  - `Resonance / Shaping`
    - `Auto Tune X`
    - `Auto Tune Y (indirect)`
    - `Last Result`
  - `Advanced Motion`
  - firmware retract
- `Sensors / IMU`
  - `MPU6050 / IMU`
  - filament sensor
- `BLTouch / Leveling`
  - explicit BLTouch probe enable
  - native BLTouch controls
  - automatic bed level / G29
- `Recovery`
- `Storage`
- `About`

## MPU influence on motion

Normal real-time MPU sampling remains observational. The sensor does not inject corrections into each planned move. Instead, the resonance assistant calibrates the frequency used by Marlin's native Input Shaping. Once a valid resonance is applied and saved, the planner/stepper shaping logic uses that frequency on subsequent prints.

X is a direct toolhead measurement. Y is indirect because the moving bed is not carrying the MPU, so V1 requires higher confidence before applying a Y result.

## Long text

The status filename marquee remains independent. Menu and editable labels now have their own selected-item marquee: after a 900 ms pause, a long plain UTF-8 label advances one character every 420 ms inside the exact space already reserved for the label. The right-side arrow or numeric value does not move.

Dynamic Marlin template labels keep the native renderer so substitutions are never corrupted.
