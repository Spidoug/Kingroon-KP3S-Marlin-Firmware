# Slicer G-code integration

These samples are **deliberately conservative** and do not presume that BLTouch, a saved mesh, an all-metal hotend, or another upgrade is installed. Use the correct material temperatures in your slicer's built-in temperature sections. They do not add automated extrusion, nozzle wiping, or unexpected moves.

## Start G-code

```gcode
; KP3S V1 - validate endstops, axis direction and clearance before use
G21       ; millimeters
G90       ; absolute XYZ
M82       ; absolute extruder
M107      ; fan off
G28       ; home only if actual X/Y/Z endstops are verified
; With calibrated BLTouch + saved/validated mesh ONLY, optionally uncomment:
; M420 S1  ; enable previously saved mesh; verify status with M420 V
G92 E0    ; zero extruder position
```

If your slicer already generates `G28`, start heating, fan settings, or extrusion commands, combine these scripts carefully rather than duplicating them. The firmware's `RESTORE_LEVELING_AFTER_G28` option preserves the earlier leveling state, but explicit `M420 S1` still requires an existing valid mesh. `G29` physically probes the bed and should only be used after testing the BLTouch trigger, offsets, deploy/retract and travel limits.

## End G-code

```gcode
M400      ; finish queued moves
M104 S0   ; hotend off
M140 S0   ; heated bed off
M107      ; fan off
G90       ; absolute coordinates
M84       ; release steppers (ensure Z cannot drop dangerously)
```

## Optional slicer features

- Use `M73 P<percent> R<minutes>` if the slicer can calculate progress and ETA. Values are information, not motion commands.
- `M593 X F<Hz>` / `M593 Y F<Hz>` adjust input shaping only after empirical calibration. Start with shaping disabled until measured.
- `M900 K<value>` adjusts Linear Advance after a pressure-advance calibration. The generator's default K is 0.
- `M486` supports object cancellation, but your slicer must output compatible object labels/commands.
- `G2/G3` arcs remain supported by default. Do not disable `ARC_SUPPORT` if your files use them.
- Use `M500` only when idle and only after reviewing tuning changes.

Reference command list: <https://marlinfw.org/docs/gcode/>. Hardware setup and acceptance steps: `test-matrix.md`.
