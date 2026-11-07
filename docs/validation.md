# Validation status

**Source preparation date:** 2026-11-06. **Scope:** uploaded custom KP3S Nokia/Samsung source package, Python tools, static generator checks and virtual serial simulations.

| Check | Result | What it establishes |
| --- | --- | --- |
| `python3 firmware/selftest.py` | **119/119 passed** | Python utilities, safe-failure paths, mocked build steps and virtual printer protocol paths |
| `python3 firmware/build_firmware.py --audit-only` | **Passed** | Maintained generator configuration and source-level invariants |
| Python syntax (`compileall`) | **Passed** | Python source parses in tested interpreter |
| `bash -n firmware/*.sh` | **Passed** | Shell launcher syntax is valid |
| Resource exclusion and local relative links | **Passed at packaging** | Working tree excludes generated files and local documentation links resolve |
| Download and patch full pinned Marlin source | **Not executed** | Requires externally downloaded Marlin sources (not present in the repository) |
| Real PlatformIO C++ compile/link and firmware flash size | **Not executed** | Requires a full external toolchain and linked Marlin source |
| Actual KP3S board, thermal, motion, LCD, BLTouch and MPU tests | **Not executed** | Requires the specific physical printer and supervised checks |

The automated tests do **not** prove that the generated Marlin code compiles, that a binary fits flash, that all physical pins match an arbitrary printer, or that thermal protections work in real hardware.

## Reproduce offline checks

```bash
python3 firmware/build_firmware.py --audit-only
python3 firmware/selftest.py
python3 -m compileall -q firmware
bash -n firmware/BUILD_FIRMWARE.sh firmware/SERIAL_SPOOL.sh firmware/KP3S_CONSOLE.sh
```

For Windows, the GitHub workflow also smoke-tests `BUILD_FIRMWARE.bat --show-default-profile` without downloading firmware and includes the Python CLI audit/help checks. Windows end-to-end serial operation is **not** hardware-validated.

## Full build and hardware gate

The [build guide](build-and-flash.md) explains the pinned PlatformIO/MKS Robin Nano output. The separate [test matrix](test-matrix.md) identifies functions exercised by virtual serial responses and those still requiring physical checks, including endstops before homing, plausible ambient temperature before heating, printer motion direction and safe shutdown. These gates must be completed before distributing firmware binaries as validated for use.

The `stock` name means the conservative **hotend thermal profile**, not the factory control panel: **the Nokia/Samsung panel remains standard**. `high-temp` must not be enabled without a compatible 350 °C-rated hardware assembly and matching thermistor. Confirmation flags are acknowledgement only, not physical sensors.
