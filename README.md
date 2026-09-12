# [**Kingroon-KP3S-Marlin-Firmware**](https://github.com/Spidoug/Kingroon-KP3S-Marlin-Firmware)

**Kingroon KP3S — Marlin Firmware V1**

Custom **Marlin 2.1.3-b3** firmware for the Kingroon KP3S STM32F103VET6, built around a Nokia 5110 display, Samsung UE5000 control board, optional BLTouch, filament runout sensor and MPU6050 IMU with resonance-assisted Input Shaping.

<p align="center">
  <img src="assets/photos/kp3s-marlin-firmware-overview.jpg" alt="Kingroon KP3S Marlin Firmware V1 running with the Nokia 5110 display and Samsung control board" width="820">
</p>

<p align="center"><strong>Kingroon KP3S Marlin Firmware V1 — V1 hardware running the custom firmware.</strong></p>

## Project overview

This repository contains a single maintained **V1** firmware line. The build system starts from the official Kingroon KP3S Marlin configuration and applies the complete V1 hardware, interface, persistence and safety layer automatically.

The project replaces the original display/control workflow with a compact 84x48 Nokia UI and a repurposed Samsung BN41-01840B / BN96-22413B control board, while adding runtime hardware controls, multilingual menus, idle IMU diagnostics and native Marlin motion tuning.

### Main features

- Nokia 5110 / PCD8544 84x48 graphical interface.
- Samsung UE5000 board for four-way navigation, CENTER action, IR receiver, LED and feedback.
- Selected long-label marquee constrained to the label field.
- Five runtime LCD languages with English as the primary/default language, plus V1 completion of visible Marlin strings so the four non-English modes do not fall back to English for enabled features.
- Mechanical Z-min retained on PA11.
- Optional BLTouch on PA8 with probe input on PC4.
- Filament runout input on PA4 with Advanced Pause / M600 support.
- Up to two MPU6050 modules on PD8/PD9, using addresses 0x68/0x69 with independent Bed / Toolhead role assignment.
- Independent bed/toolhead fused level, startup inclination, vibration and calibrated IMU die-temperature diagnostics.
- Independent guided level-zero and temperature-offset calibration for bed and toolhead IMUs.
- Motion-isolated IMU policy: MPU polling, detection, recovery and reconfiguration stop during printing, pause and ordinary queued motion.
- Resonance assistant with automatic homing, active ~200 Hz MPU capture and native Marlin Input Shaping application.
- Linear Advance, Firmware Retract, babystepping, Z-offset wizard and PID controls.
- High-temperature hotend profile with a selectable target up to 340 °C, using Marlin sensor table 61 (100k B3950 / 350 °C) and a 350 °C hard cutoff.
- Native Hotend Idle Timeout: 10 minutes above 180 °C, then nozzle and bed targets are reduced to 0 °C.
- Power-loss recovery support, disabled by default.
- Serial printing / transfer helper and host telemetry.
- Persistent V1 runtime settings in EEPROM.
- Lossless logical standby: queued G-code wakes the interface instead of being discarded.

## Hardware gallery

<table>
  <tr>
    <td align="center" width="50%">
      <img src="assets/photos/display-controller-assembly.jpg" alt="Nokia display and Samsung controller assembly" width="420"><br>
      <sub>Nokia 5110 display and Samsung navigation board.</sub>
    </td>
    <td align="center" width="50%">
      <img src="assets/photos/control-panel-back.jpg" alt="Rear wiring of the modified control panel" width="420"><br>
      <sub>Rear wiring of the modified control panel / FFC interface.</sub>
    </td>
  </tr>
  <tr>
    <td colspan="2" align="center">
      <img src="assets/photos/control-panel-assembly.jpg" alt="Complete V1 control-panel hardware assembly" width="620"><br>
      <sub>Complete V1 control-panel hardware assembly.</sub>
    </td>
  </tr>
</table>

## Hardware

| Function | V1 connection |
| --- | --- |
| Nokia DIN | PD14 / FFC3 |
| Nokia CS / CE | PD7 / FFC19 |
| Nokia DC | PD11 / FFC20 |
| Nokia CLK | PD5 / FFC21 |
| Nokia RST | PC6 / FFC23 |
| Nokia backlight | PD13 / FFC24 |
| Samsung KEY1 | PE10 / FFC10 |
| Samsung KEY2 | PE13 / FFC13, with 1k series + 100nF to GND |
| Samsung IR | PE7 / FFC7 |
| Samsung LED | PD10 / FFC18 |
| Mechanical Z-min | PA11 |
| BLTouch control | PA8 |
| BLTouch probe | PC4 |
| Filament runout | PA4 |
| MPU6050 physical pair | PD8 / FFC16 + PD9 / FFC17 |
| Hotend thermistor | 100k B3950 high-temperature sensor compatible with Marlin table 61, rated to at least 350 °C |

See [`docs/pinout.md`](docs/pinout.md) and [`docs/samsung-control-board.md`](docs/samsung-control-board.md) for the complete wiring reference.

## V1 interface

V1 keeps Marlin's native menu hierarchy and adds only focused feature submenus where they improve clarity. SD / file selection is placed at the top of the main menu for the shortest print workflow. Filament runout and Firmware Retract remain in `Configuration`, Power-loss Recovery and EEPROM actions remain in their native configuration positions, BLTouch tools remain together, and all screen-related controls are consolidated into one `Display` submenu.

The V1-specific additions are deliberately small and placed beside their native counterparts:

- `Configuration > BLTouch On` — runtime probe enable directly beside the native BLTouch tools.
- `Configuration > Display > Rotate LCD 180` — flips the Nokia UI by 180 degrees (upside down), applies immediately, and persists in EEPROM; editable only while idle.
- `Configuration > Display > Language` — language selection stays with brightness, contrast and screen timeout, then returns to the Display submenu after selection.
- `Configuration > MPU6050 / IMU` — dual-MPU wiring, role assignment, diagnostics and per-role data beside the sensor controls.
- `Configuration > Advanced Settings > Input Shaping > Auto Resonance` — X/Y resonance assistant next to Marlin's manual Input Shaping controls.
- `Info > Printer Info` — native Marlin information screen extended with the KP3S V1 identity and author.

Probe / Level no longer duplicates EEPROM Save. With BLTouch disabled, automatic leveling and the probe-offset wizard are hidden while manual bed tramming remains available.

Long labels scroll only while selected and only inside their reserved field, so submenu arrows and editable values remain fixed. Two-choice confirmation screens use isolated left/right fields, preventing long translations such as Cancel / Print from drawing over one another. Reset-to-defaults now uses an explicit confirmation screen.

The MPU subsystem detects only 0x68 and 0x69 and lets each address be assigned as Bed, Toolhead or unused. Both addresses start unassigned in V1. MPU software-I2C is fully suspended during printing, pause and normal queued motion. Resonance tuning is an explicit calibration operation and applies accepted frequencies through Marlin's native Input Shaping implementation.

## Build

On Windows, run:

```text
firmware/BUILD_FIRMWARE.bat
```

A successful local build creates:

```text
firmware/firmware_output/FLASH_KP3S/Robin_nano.bin
```

The build script downloads the exact Marlin 2.1.3-b3 source and official KP3S configuration, applies all V1 changes, checks the required V1 invariants and compiles the STM32 firmware.

## Flash

1. Format a reliable microSD card as FAT32.
2. Copy only `Robin_nano.bin` to the card root.
3. Power the printer off.
4. Insert the microSD card.
5. Power the printer on and allow the bootloader to process the file.
6. Power the printer off before removing the card.
7. Verify endstops, temperatures, heaters, fans, motion direction and Z/probe behavior before the first print.

## Safety and persistence

**340 °C is a high-temperature hardware profile, not a stock-hotend setting.** The V1 configuration now assumes an all-metal hotend, heater cartridge, thermistor, wiring and connectors rated for at least 350 °C. The thermistor must match Marlin table 61 (100k B3950 Formbot/Vivedino style). Do not use the original table-1 thermistor or a PTFE-lined hotend at 340 °C. After any hotend or thermistor change, verify room-temperature plausibility first and run PID autotune at a representative operating temperature before printing.

Marlin uses `HEATER_0_MAXTEMP = 350` and `HOTEND_OVERSHOOT = 10`, so the highest selectable hotend target is exactly **340 °C** while 350 °C remains the hard thermal fault ceiling. Native Hotend Idle Timeout is enabled for 10 minutes above 180 °C and commands nozzle / bed targets to 0 °C after inactivity.

The builder validates the V1 safety rules on the generated Marlin tree. It refuses to proceed if essential hotend/bed thermal protection, cold-extrusion prevention, required X/Y/Z endstop inputs, the 340 °C high-temperature sensor profile or configured temperature limits disappear.

Display orientation, BLTouch runtime state, MPU enable/wiring, 0x68/0x69 role assignments and independent bed/toolhead calibration are EEPROM-backed. Native Marlin Input Shaping values are persistent as well. EEPROM-mutating `M500`, `M501` and `M502` are blocked while an active or paused print is detected.

The internal EEPROM identifier is **V01**, representing the single V1 schema. The public firmware identity is **V1**.

After the first flash of this V1 schema, verify machine-specific PID values, steps/mm, Z-offset, motion limits and other calibration values before unattended printing.

## Documentation

- [`docs/firmware-v1.md`](docs/firmware-v1.md) — V1 behavior and menu structure.
- [`docs/architecture.md`](docs/architecture.md) — architecture and safety rules.
- [`docs/build-and-flash.md`](docs/build-and-flash.md) — complete build / flash workflow.
- [`docs/mpu6050.md`](docs/mpu6050.md) — IMU behavior, level and calibration.
- [`docs/resonance-tuning.md`](docs/resonance-tuning.md) — resonance-assisted Input Shaping.
- [`docs/bltouch.md`](docs/bltouch.md) — optional BLTouch operation.
- [`docs/filament-runout.md`](docs/filament-runout.md) — filament sensor behavior.
- [`docs/serial-print.md`](docs/serial-print.md) — serial printing / transfer support.
- [`docs/navigation.md`](docs/navigation.md) — Samsung control-board navigation.
- [`docs/troubleshooting.md`](docs/troubleshooting.md) — troubleshooting reference.

## Version

**Kingroon-KP3S-Marlin-Firmware — V1**
