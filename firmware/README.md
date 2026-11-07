# Firmware tools

This folder contains the project configuration, pinned Marlin generator, offline regression tests, Windows/Ubuntu build launchers and guarded serial helpers. It **does not** include compiled Marlin firmware.

The standard control profile is **Nokia 5110 + Samsung UE5000**, not the KP3S factory panel. Only the hotend profile changes between `stock` (235 °C target, table-1 sensor) and `high-temp` (340 °C target, table-61 sensor). High-temperature hardware verification and explicit acknowledgement remain mandatory.

| File | Purpose |
| --- | --- |
| `kp3s_project_config.py` | Control profile, pin assignments and default hotend profile |
| `build_firmware.py` | Source download, patch, verification, PlatformIO build and SHA-256 manifest |
| `BUILD_FIRMWARE.sh`, `BUILD_FIRMWARE.bat` | Interactive Ubuntu/Windows build entry points |
| `serial_spool.py`, `SERIAL_SPOOL.*` | Marlin binary SD-file transfer and print monitor |
| `kp3s_console.py`, `KP3S_CONSOLE.*` | Guarded G-code diagnostics and maintenance console |
| `selftest.py` | Offline regression suite |
| `requirements.txt` | Optional Python dependency for real serial connections |

From the repository root:

```bash
python3 firmware/build_firmware.py --audit-only
python3 firmware/selftest.py
python3 firmware/build_firmware.py --build --auto-toolchain --hotend-profile stock
python3 firmware/kp3s_console.py --list-actions
```

To build the upgraded profile **only with independently verified compatible hotend hardware**:

```bash
python3 firmware/build_firmware.py --build --auto-toolchain --hotend-profile high-temp --confirm-high-temp-hardware
```

Generated files belong in `cache/`, `generated/`, `.build_env/`, `firmware_output/` and `BUILD.log`; they are ignored by Git. Build artifacts are *not* hardware-tested. For instructions and safe validation, see [`../docs/build-and-flash.md`](../docs/build-and-flash.md), [`../docs/control-profile.md`](../docs/control-profile.md), and [`../docs/test-matrix.md`](../docs/test-matrix.md).
