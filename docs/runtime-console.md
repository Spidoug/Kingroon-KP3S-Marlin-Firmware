# KP3S V1 runtime console

The Python console exposes a **whitelisted** set of Marlin reports and controls over an existing USB/serial connection. It **does not stream arbitrary movement G-code** during printing, and it is not a substitute for a real emergency power switch, host or printer operator.

Install pyserial: `python3 -m pip install -r firmware/requirements.txt` (prefer a venv). On Ubuntu, ensure your account has permission for the printer serial device. Do not run the uploader and this console on the same serial port simultaneously.

```bash
# Full list of supported controls. Offline, no serial connection needed.
./firmware/KP3S_CONSOLE.sh --list-actions

# Discover likely serial ports.
./firmware/KP3S_CONSOLE.sh --list-ports

# Read-only checks (each establishes Marlin KP3S V1 machine identity).
./firmware/KP3S_CONSOLE.sh status --port /dev/ttyUSB0
./firmware/KP3S_CONSOLE.sh settings --port /dev/ttyUSB0
./firmware/KP3S_CONSOLE.sh position --port /dev/ttyUSB0

# Default for mutations: validate and show proposed commands, NO serial I/O.
./firmware/KP3S_CONSOLE.sh speed 90
./firmware/KP3S_CONSOLE.sh shaping X 32

# Apply only after verifying the printer status.
./firmware/KP3S_CONSOLE.sh fan 70 --port /dev/ttyUSB0 --execute
./firmware/KP3S_CONSOLE.sh linear-advance 0.14 --port /dev/ttyUSB0 --execute
./firmware/KP3S_CONSOLE.sh z-babystep -0.02 --port /dev/ttyUSB0 --execute

# High-temperature mode is available only for verified upgraded hardware.
./firmware/KP3S_CONSOLE.sh nozzle 290 --profile high-temp --confirm-high-temp-hardware --port /dev/ttyUSB0 --execute --yes

# PID autotune starts actual heating and can take several minutes.
./firmware/KP3S_CONSOLE.sh pid-autotune 205 --port /dev/ttyUSB0 --execute --yes

# Program macros only with carefully reviewed G-code.
./firmware/KP3S_CONSOLE.sh macro-set 1 'M105|M114' --port /dev/ttyUSB0 --execute --yes
./firmware/KP3S_CONSOLE.sh macro-run 1 --port /dev/ttyUSB0 --execute --yes
```

Windows equivalent: `firmware\KP3S_CONSOLE.bat status --port COM5` (and analogous options).

## Available controls

| Group | Actions | Notes |
| --- | --- | --- |
| Read-only | `status`, `temperatures`, `endstops`, `position`, `settings`, `sd`, `motion`, `shaping-status`, `level-status`, `filament-status`, `recovery-status`, `idle-timeout-status`, `macros` | Read from Marlin; no movement/heating commands |
| Temperature | `nozzle C`, `bed C` | Stock nozzle 0-235 C; upgraded 0-340 C; bed 0-100 C |
| Extrusion/motion tuning | `speed %`, `flow %`, `linear-advance K`, `shaping X|Y Hz`, `z-babystep mm` | Speed 25-200%; flow 50-150%; K 0-1; shaping 0/off or 20-100 Hz; Z step max ±0.05 mm |
| Fans and safety | `fan %`, `idle-timeout SEC` | Fan 0-100%; timeout 120-1800 s. `M86` holds 180 C trigger, 0 C idle targets |
| Machine states | `filament-sensor on|off`, `level on|off`, `recovery on|off` | Enabling requires confirmation, correct hardware, verified mesh or media |
| Printing | `pause`, `resume`, `abort`, `home` | Abort/home require both `--execute` and `--yes`. Homing needs a clear and correctly calibrated machine |
| EEPROM | `save`, `reload`, `factory-defaults` | Factory defaults only modify RAM until you save; mutating while printing is blocked by V1 firmware |
| Calibration | `pid-autotune C` | Only nozzle; monitored temperature rise with physically verified sensor/fan |
| G-code macros | `macro-set SLOT 'A|B'`, `macro-run SLOT` | Slots 0-3. Max 64 ASCII characters, not persisted by firmware |
| Emergency | `emergency` | Sends M112 without waiting for M115; --execute, --yes and exact port needed for certainty |

**Emergency command:** `./firmware/KP3S_CONSOLE.sh emergency --port /dev/ttyUSB0 --execute --yes`. If communication is lost or fire/unsafe motion is present, disconnect power safely and follow the equipment emergency plan. A software emergency command is not guaranteed to be delivered over a dead connection.

The console requires an `M115` identity report containing `MACHINE_TYPE:KINGROON KP3S V1` before ordinary commands; all writes are sent one at a time and require an `ok` response. An identity string does not authenticate a device or attest its physical hardware. Some Marlin replies are asynchronous during printing; use dedicated host monitoring for long operations.

`M290 P0 Z...` deliberately avoids changing the persisted BLTouch offset while performing small temporary Z babystepping. PID autotune modifies the in-RAM calibration; use `save` after checking the result, while idle, to persist.
