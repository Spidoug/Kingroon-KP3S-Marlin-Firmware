# Build and flash

## Automatic build

Run `firmware/BUILD_FIRMWARE.bat` on Windows.

The V1 builder performs the complete workflow:

1. locate or install Python 3.10+;
2. prepare an isolated build environment if needed;
3. download and validate the exact Marlin 2.1.3-b3 source and KP3S configuration;
4. generate a fresh project under `firmware/generated/`;
5. apply and verify all V1 patches;
6. compile the firmware;
7. create `firmware/firmware_output/FLASH_KP3S/Robin_nano.bin`.

Build details and failures are written to `firmware/BUILD.log`.

## Prebuilt V1 release binary

The repository reserves `firmware/prebuilt/` for a bootloader-ready release binary that has already been compiled and validated on the target hardware. When present, the release file is `firmware/prebuilt/Robin_nano.bin`.

The normal development build output remains under `firmware/firmware_output/` and stays ignored by Git. Only a deliberate, validated release binary should be copied into `firmware/prebuilt/`.

## Flash

1. Use a reliable microSD card formatted FAT32.
2. Copy only `Robin_nano.bin` to the card root.
3. Power the printer off.
4. Insert the card.
5. Power the printer on and allow the bootloader to process the file.
6. Power the printer off before removing the card.
7. Verify endstops, temperature readings, heater control and motion before the first print.

The normal update path is the printer bootloader reading the file from microSD.
