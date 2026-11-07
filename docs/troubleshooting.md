# Troubleshooting

## Nokia display is blank

Do not change the validated pinout first. Verify power, reset, backlight polarity and the custom PCD8544 transport.

## JOG direction is wrong

Enable `KP3S_UE5000_DEBUG` and record `RCus` for every physical direction. Change RC thresholds only after measurement.

## Confirmation dialog still uses UP/DOWN

Verify that the generated Marlin tree contains `kp3s_ui_selection_mode` in `menu.cpp` and that `marlinui.cpp` contains the context-aware LEFT/RIGHT branch.

## Language does not persist

Confirm EEPROM is enabled and `LCD_LANGUAGE_AUTO_SAVE` is active. If settings appear inconsistent after flashing V1, restore firmware defaults once, re-enter machine-specific calibration values, and save them.

## Filament runout triggers backwards

Measure the sensor logic and adjust `FIL_RUNOUT_STATE` only after confirming the electrical level with and without filament.

## Build stops with `Unexpected Robin Nano build target`

The pinned Marlin uses PlatformIO section inheritance. The generator validates
`[env:mks_robin_nano_v1v2]` and its parent sections for the effective
STM32F103VE board, 0x7000 bootloader offset, 0x08007000 upload address and
`Robin_nano35.bin` output. Use the current project builder to avoid the old
whitespace-sensitive check. If this error persists after updating, do **not**
remove the validation: inspect `firmware/generated/ini/stm32f1.ini` for an
unexpected board or bootloader setting and attach `firmware/BUILD.log` to a
bug report. Do not flash an image built for a different controller.

## Windows launcher prints `python.exe" -c` is not recognized

Update `firmware/BUILD_FIRMWARE.bat` to the version that reads the internal
thermal profile through a temporary file, instead of running the quoted
Python path inside a `FOR /F` command. To verify the launcher without
building or downloading dependencies, run:

```bat
firmware\BUILD_FIRMWARE.bat --show-default-profile
```

The normal launcher still prompts for `stock` or `high-temp` and enforces
the high-temperature hardware confirmation.
