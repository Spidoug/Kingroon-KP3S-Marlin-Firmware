# Current Pinout

## Nokia 5110 / PCD8544

| Function | MCU | FFC |
|---|---|---:|
| VCC | 3.3V | 1 |
| GND | GND | 2 |
| DIN | PD14 | 3 |
| CS | PD7 | 19 |
| DC | PD11 | 20 |
| CLK | PD5 | 21 |
| RST | PC6 | 23 |
| Backlight | PD13 | 24 |

## Samsung BN41-01840B / BN96-22413B control board

| Function | MCU | FFC |
|---|---|---:|
| KEY1 / center | PE10 | 10 |
| KEY2 / JOG | PE13 | 13 |
| IR | PE7 | 7 |
| LED | PD10 | 18 |

KEY2 wiring: `KEY2 -- 1k -- PE13`, with **100 nF from the PE13 side to GND**.

## Mechanical Z endstop

- `PA11`: Z-min microswitch.

## Optional BLTouch

- `PA8`: servo / control.
- `PC4`: probe signal through the Z-MAX / Z+ connector.
- `5V`: 3D Touch connector.
- `GND`: 3D Touch / Z-MAX ground.

## Filament runout

- `PA4`: Filament Detection 1 signal.
- sensor ground: same connector ground.

## MPU6050

- VCC: `FFC1 / 3.3V`.
- GND: `FFC2`.
- Default SDA: `FFC17 / PD9`.
- Default SCL: `FFC16 / PD8`.
- The LCD option `SDA/SCL Inv.` exchanges these two roles without reflashing.
- `FFC15 / PE15` is now only the internal dummy BTN_ENC input and must not be wired.
