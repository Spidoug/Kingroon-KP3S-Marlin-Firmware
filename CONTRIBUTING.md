# Contributing

This project targets a particular **custom-wired** KP3S, not a factory printer. Please keep the Nokia 5110 and Samsung UE5000 mapping as the standard control profile. Do not silently change motor, endstop, heater or thermistor pins.

1. Open an issue explaining the motherboard revision, relevant peripherals, expected behavior and reproducible steps, with personal/device identifiers removed from logs.
2. Keep patches narrowly scoped; document any user-facing G-code, wiring or thermal behavior changes.
3. Run `python3 firmware/build_firmware.py --audit-only` and `python3 firmware/selftest.py`. On Linux, also run `bash -n firmware/*.sh`.
4. For generated Marlin C++ changes, attach the **real PlatformIO build log** and compiled output size. A mocked build or passing Python tests alone are not sufficient.
5. For hardware or temperature changes, provide supervised validation evidence and exact sensor/hotend ratings without suggesting that hardware is automatically safe.

Do **not** commit generated sources, downloaded archives, firmware binaries, environment directories, local secrets or printer EEPROM backups. The PR template is available in `.github/`.

The generator contains some substantial C++ patch strings. Please favor exact upstream anchors, fail-fast checks and targeted tests over fragile blind replacements.
