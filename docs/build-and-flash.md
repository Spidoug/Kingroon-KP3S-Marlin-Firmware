# Build and flash

## Automatic build

Run `firmware/BUILD_FIRMWARE.bat` on Windows or `./firmware/BUILD_FIRMWARE.sh` on Linux / Ubuntu. On Windows, you can first run `firmware\BUILD_FIRMWARE.bat --show-default-profile` to verify Python detection and the internal default without downloading Marlin.

On Linux, ensure `python3`, `python3-venv`, `python3-pip`, `curl`, and an available C/C++ build toolchain are installed. The builder installs the pinned PlatformIO version in its own environment when needed.

**Choose a thermal profile before building.** The Windows and Ubuntu launchers offer a conservative `stock` profile by default (table 1 sensor, 235 C maximum target, 250 C cutoff) and an upgraded `high-temp` profile (table 61 sensor, 340 C maximum target, 350 C cutoff). Each requires the physical thermistor to match. The high-temp choice additionally requires confirmation of an all-metal 350 C-rated heating/sensor assembly.

```bash
# Noninteractive Ubuntu build; requires upstream Marlin and PlatformIO access
python3 firmware/build_firmware.py --build --auto-toolchain --hotend-profile stock

# Only after physically verifying all 350 C-rated parts:
python3 firmware/build_firmware.py --build --auto-toolchain --hotend-profile high-temp --confirm-high-temp-hardware

# Inspect options without contacting the printer:
python3 firmware/build_firmware.py --help
./firmware/KP3S_CONSOLE.sh --list-actions
```

The Python builder and both interactive launchers read the internal `DEFAULT_HOTEND_PROFILE` from `firmware/kp3s_project_config.py` (`stock` initially). Any high-temp selection still requires `--confirm-high-temp-hardware` or equivalent interactive acknowledgement. A typed acknowledgment cannot detect a bad thermistor, an unsafe PTFE-lined hotend, or miswiring. Do not bypass it.

To run the maintained-source validation and offline protocol regression checks without downloading anything:

```bash
python3 firmware/build_firmware.py --audit-only
python3 firmware/selftest.py
```

The V1 builder performs the complete workflow:

1. locate or install Python 3.10+;
2. prepare the pinned PlatformIO Core 6.1.19 isolated build environment if needed;
3. download and validate the immutable commits for Marlin 2.1.3-b3 and the matching KP3S configuration;
4. generate a fresh project under `firmware/generated/`;
5. apply and verify all V1 patches;
6. compile the firmware;
7. create `firmware/firmware_output/FLASH_KP3S/Robin_nano.bin`, `BUILD_MANIFEST.json`, and `SHA256.txt`.

Build details and failures are written to `firmware/BUILD.log`.

## Flash

1. Use a reliable microSD card formatted FAT32.
2. Confirm the motherboard is the KP3S STM32F103VET6 / `BOARD_MKS_ROBIN_NANO` hardware and back up your current configuration; then copy only `Robin_nano.bin` to the card root.
3. Power the printer off.
4. Insert the card.
5. Power the printer on and allow the bootloader to process the file.
6. Power the printer off before removing the card.
7. Verify endstops, temperature readings, heater control and motion before the first print.
8. For the high-temp 340 °C profile, verify that the installed hotend is all-metal and that the thermistor matches Marlin table 61 (100k B3950 / 350 °C). Confirm a plausible room-temperature reading before enabling the heater, then run PID autotune at a representative operating temperature.

The normal update path is the printer bootloader reading the file from microSD.

## Validation limits

The source package is a generator, not a complete standalone Marlin source tree. Its enhanced host controls are independently testable; they do not verify that the generated C++ patch compiles. Generation downloads pinned Marlin and KP3S configuration commits. A complete firmware compile requires the downloaded source, PlatformIO packages and a supported compiler. The offline checks do not replace a successful PlatformIO build or a physical-machine safety check.

Before printing, verify `M115` identity, `M105` ambient temperatures, `M119` endstops, the fan, thermistor behavior, heater shutdown, correct motor directions and that all movement stays within the machine's travel. Check the mechanical Z stop and BLTouch independently. Never leave first heat-up or first print unattended.
