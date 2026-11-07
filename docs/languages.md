# Language System

V1 uses Marlin multi-language selection with EEPROM persistence. **English is the primary and default language**. On a fresh V1 installation, before a different language has been selected and saved, the UI starts in English. The selector is at `Configuration > Display > Language`:

1. English — default
2. Português (Brasil)
3. Español
4. Français
5. Deutsch

The language order is fixed in V1 as `en`, `pt_br`, `es`, `fr`, `de`. Selecting another language saves that user choice to EEPROM; the saved choice may override English on later boots until the user changes it again.

All KP3S-specific menu additions, MPU diagnostics, resonance results, print states, display inversion and BLTouch runtime controls are authored as a complete five-language set in the same order. Native Marlin items start from the pinned official Marlin language files, and V1 completes or corrects the labels used by this firmware whenever the upstream language would otherwise fall back to English, contain a partial translation, or only provide a wide-display variant. This includes display controls, Input Shaping, PID autotune, hotend idle protection, probe wizard, bed tramming, printer information/statistics, SD/media actions (mount, eject, select files, media state) and the other V1-visible runtime controls. Hardware names (`MPU6050`, `BLTouch`, `KINGROON KP3S`), axis letters, SI units and I2C identity values remain invariant.

V1-specific labels are kept within the Nokia 84x48 display's 14-character row width. The bounded marquee remains available for longer native Marlin labels, but V1 custom translations do not depend on it for basic readability.

After choosing a language, the firmware saves it and returns to `Configuration > Display`, avoiding a duplicate language selector in the main menu.
