# JOG and Menu Navigation

## Physical RC mapping

| RC time | Physical direction |
|---:|---|
| `<60 us` | DOWN |
| `60..219 us` | UP |
| `220..899 us` | RIGHT |
| `900..5199 us` | LEFT |
| neutral cutoff / timeout | NONE |

## UI context rules

The physical direction is context-aware instead of being blindly mapped to a rotary encoder.

### Normal list / file browser

- UP: previous item
- DOWN: next item
- LEFT: back
- RIGHT: select / enter
- CENTER: select / confirm

### Two-choice confirmation

- LEFT: choose left option
- RIGHT: choose right option
- CENTER: confirm highlighted option
- UP/DOWN: ignored for choice selection

### Numeric / edit screens

- LEFT: decrease
- RIGHT: increase
- CENTER: confirm and leave edit mode
- UP/DOWN: ignored while editing

## Hold acceleration

All four directions now share the same hold-repeat engine. A direction begins repeating after 320 ms. The repeat interval is 110 ms initially, 75 ms after one second, and 45 ms after 2.5 seconds. This applies equally to LEFT, RIGHT, UP, and DOWN.

## Center-key standby gesture

A short center-key press is emitted as ENTER only after release. Holding the center key for five seconds is reserved for logical power control:

- while awake and fully idle: enter standby;
- while in standby: wake the interface;
- during printing, pause state, queued motion, or with a hotend/bed target above zero: standby is refused and the long press is consumed.

V1 boots awake. Standby leaves the MCU powered so the key can wake the interface; the LCD/backlight is off and the red status LED remains on. Standby never clears the G-code queue. If work is queued from serial, SD or an internal command source, V1 wakes the interface automatically and then lets Marlin process the command normally.
