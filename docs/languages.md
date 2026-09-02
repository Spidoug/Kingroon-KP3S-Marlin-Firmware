# Language System

V1 uses Marlin multi-language selection with EEPROM persistence:

1. English
2. Português (Brasil)
3. Español
4. Français
5. Deutsch

All KP3S-specific menu groups, MPU diagnostics, resonance results, print states, display controls, recovery/storage labels and BLTouch controls follow the selected language. Hardware names (`MPU6050`, `BLTouch`, `KINGROON KP3S`), axis letters and I2C identity values remain invariant.

The 84x48 display no longer requires every translated label to be artificially shortened. Long selected labels can use the bounded marquee, so names may stay more descriptive without overwriting adjacent UI fields.
