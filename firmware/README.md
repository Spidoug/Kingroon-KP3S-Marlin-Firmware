# Kingroon KP3S Marlin Firmware V1

Canonical repository: https://github.com/Spidoug/Kingroon-KP3S-Marlin-Firmware

This directory contains the complete V1 build and serial-print entry points.

The generated V1 hotend profile allows a maximum selectable target of **340 °C** using Marlin thermistor table 61 (100k B3950 / 350 °C), with a 350 °C hard cutoff and 10 °C overshoot reserve. This requires matching all-metal high-temperature hardware; do not use the stock table-1 thermistor or a PTFE-lined hotend at this temperature.

- `BUILD_FIRMWARE.bat` — Windows build entry point with automatic prerequisite setup.
- `build_firmware.py` — downloads the pinned Marlin 2.1.3-b3/KP3S commits, generates the KP3S Marlin Firmware V1 tree, checks required V1 invariants and builds with PlatformIO Core 6.1.19.
- `SERIAL_SPOOL.bat` — optional Windows launcher for serial file transfer / printing.
- `serial_spool.py` — serial transfer, SD-start and telemetry client.
- `requirements.txt` — pinned Python dependency for the serial client (`pyserial 3.5`).
- `FLASH_GUIDE.txt` — concise flash procedure.

Generated and downloaded content is created locally under `cache/`, `generated/`, `.build_env/` and `firmware_output/` and is not part of the repository release.

