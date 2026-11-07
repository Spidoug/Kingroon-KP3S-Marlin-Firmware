# KP3S V1 standard hardware and internal temperature switch

**Standard firmware hardware:** the custom **Nokia 5110 (PCD8544) display + Samsung BN41-01840B / BN96-22413B UE5000 navigation board** on the MKS Robin Nano / STM32F103VE board. This is the user's original custom assembly, not a factory touchscreen KP3S. The Nokia/Samsung wiring and panel integration always stay enabled regardless of the hotend selection.

## One internal thermal setting

Edit `firmware/kp3s_project_config.py`:

```python
CONTROL_HARDWARE_PROFILE = "nokia5110-samsung-ue5000"
DEFAULT_HOTEND_PROFILE = "stock"  # Change to "high-temp" ONLY after hardware verification
```

`stock` is the **thermal sensor/hotend profile name**, *not* the factory touchscreen hardware profile. In `stock`, Marlin table 1 is used and the target is limited to 235 °C (`MAXTEMP` 250 °C). In `high-temp`, Marlin table 61 is used and the target is 340 °C (`MAXTEMP` 350 °C). Switching these profiles changes the actual temperature conversion table, not just the displayed temperature. **Never enable high-temp without checking the installed 350 °C-rated all-metal hotend, sensor, heater and wiring**. The builder and launchers still require an explicit hardware acknowledgement for `high-temp`, even if it is set as the internal default.

The board, screen, Samsung keys/IR/LED, endstops and runtime options are **unchanged** by this thermal switch. Pin defaults are recorded in `CONTROL_PIN_MAP` in that same file and in `docs/pinout.md`. These assignments are fixed for the supplied custom wiring; do not edit them without modifying and validating the actual pin patches. Generation audits fail on changed/missing assignments, accidental factory display enablement, overlapping declared control pins, or conflicts with the MKS Robin Nano motion, heater, endstop, fan and SD pin allocations.

## Ubuntu build

```sh
cd firmware
python3 build_firmware.py --audit-only
python3 selftest.py
./BUILD_FIRMWARE.sh stock
# Only when all high-temperature hardware is verified:
./BUILD_FIRMWARE.sh high-temp
```

`--generate-only` creates the source tree, not a firmware binary. The full build downloads upstream Marlin and PlatformIO packages. No `.bin` is supplied in this source archive. Even successful static tests do **not** prove that the C++ compiles, the image fits flash, or the custom controls and thermal safety work physically. Confirm firmware build, pins, motion, sensors, endstops, and emergency stops on the actual printer before first printing.
