# Kingroon KP3S Marlin Firmware V1

Canonical repository: https://github.com/Spidoug/Kingroon-KP3S-Marlin-Firmware

This directory contains the complete V1 build and serial-print entry points.

- `BUILD_FIRMWARE.bat` — Windows build entry point with automatic prerequisite setup.
- `build_firmware.py` — downloads Marlin 2.1.3-b3, generates the KP3S Marlin Firmware V1 tree, checks required V1 invariants and builds the firmware.
- `SERIAL_SPOOL.bat` — optional Windows launcher for serial file transfer / printing.
- `serial_spool.py` — serial transfer, SD-start and telemetry client.
- `requirements.txt` — Python dependency for the serial client.
- `FLASH_GUIDE.txt` — concise flash procedure.
- `prebuilt/` — reserved for a validated bootloader-ready V1 release binary.

Generated and downloaded content is created locally under `cache/`, `generated/`, `.build_env/` and `firmware_output/` and is not part of the repository release.

Local build output remains ignored. A deliberately published `prebuilt/Robin_nano.bin` is allowed to be tracked as the tested V1 release image.
