# Build and flash

## Automatic build

Run `firmware/BUILD_FIRMWARE.bat` on Windows.

The V1 builder performs the complete workflow:

1. locate or install Python 3.10+;
2. prepare the pinned PlatformIO Core 6.1.19 isolated build environment if needed;
3. download and validate the immutable commits for Marlin 2.1.3-b3 and the matching KP3S configuration;
4. generate a fresh project under `firmware/generated/`;
5. apply and verify all V1 patches;
6. compile the firmware;
7. create `firmware/firmware_output/FLASH_KP3S/Robin_nano.bin`.

Build details and failures are written to `firmware/BUILD.log`.

## Flash

1. Use a reliable microSD card formatted FAT32.
2. Copy only `Robin_nano.bin` to the card root.
3. Power the printer off.
4. Insert the card.
5. Power the printer on and allow the bootloader to process the file.
6. Power the printer off before removing the card.
7. Verify endstops, temperature readings, heater control and motion before the first print.
8. For the 340 °C profile, verify that the installed hotend is all-metal and that the thermistor matches Marlin table 61 (100k B3950 / 350 °C). Confirm a plausible room-temperature reading before enabling the heater, then run PID autotune at a representative operating temperature.

The normal update path is the printer bootloader reading the file from microSD.
