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
