# Samsung Control Board Integration

Hardware: BN41-01840B / BN96-22413B family. The board is powered from 3.3V and must not receive 5V on its logic supply.

Current mapping:

- KEY1 -> PE10 / FFC10
- KEY2 -> PE13 / FFC13 through 1 kΩ, with 100 nF from PE13 side to GND
- IR -> PE7 / FFC7
- LED -> PD10 / FFC18

The firmware decodes KEY2 using RC discharge time because PE13 is used as a digital GPIO.

The hardware identifier is documented here, but it is intentionally not displayed on the printer status screen.
