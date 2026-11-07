#!/usr/bin/env python3
"""Kingroon KP3S V1 - guarded Marlin diagnostics and runtime control over serial.

Read-only reports are sent immediately. Mutating actions require --execute;
high-risk actions also require --yes. All mutable commands have explicit bounds.
This tool cannot verify the printer's physical wiring, thermistor or mechanics.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import math
from typing import Sequence

import serial_spool as spool


class ConsoleError(ValueError):
    pass


@dataclass(frozen=True)
class Operation:
    commands: tuple[str, ...]
    description: str
    mutating: bool = False
    high_risk: bool = False
    timeout: float = 5.0


READ_COMMANDS: dict[str, tuple[str, ...]] = {
    'status': ('M115', 'M105', 'M114', 'M119', 'M27'),
    'temperatures': ('M105',),
    'endstops': ('M119',),
    'position': ('M114', 'M114 D', 'M114 R'),
    'settings': ('M503',),
    'sd': ('M27', 'M27 C'),
    'motion': ('M201', 'M203', 'M204', 'M205'),
    'shaping-status': ('M593',),
    'level-status': ('M420 V',),
    'filament-status': ('M412',),
    'recovery-status': ('M413',),
    'idle-timeout-status': ('M86',),
    'macros': ('M820',),
}


def number(value: str | None, *, field: str, low: float, high: float, integer: bool = False) -> float:
    if value is None:
        raise ConsoleError(f"{field} requires a numeric value")
    try:
        result = float(value)
    except (ValueError, TypeError) as exc:
        raise ConsoleError(f"{field} requires a numeric value") from exc
    if not math.isfinite(result) or not low <= result <= high:
        raise ConsoleError(f"{field} must be a finite number between {low:g} and {high:g}")
    if integer and not result.is_integer():
        raise ConsoleError(f"{field} must be an integer")
    return result


def no_extra(value: str | None, extra: str | None):
    if value is not None or extra is not None:
        raise ConsoleError("This operation does not accept a value")


def action(name: str, value: str | None, extra: str | None, *, profile: str, hardware_confirmed: bool) -> Operation:
    if name in READ_COMMANDS:
        no_extra(value, extra)
        return Operation(READ_COMMANDS[name], f"Read {name}")

    if name == 'nozzle':
        if extra is not None:
            raise ConsoleError('nozzle takes one temperature')
        ceiling = 235 if profile == 'stock' else 340
        t = number(value, field='nozzle temperature', low=0, high=ceiling)
        if profile == 'high-temp' and t > 235 and not hardware_confirmed:
            raise ConsoleError('Hotend targets above 235 C require --confirm-high-temp-hardware')
        return Operation((f'M104 S{t:g}',), f"Set nozzle target to {t:g} C", True, t > 235)

    if name == 'bed':
        if extra is not None:
            raise ConsoleError('bed takes one temperature')
        t = number(value, field='bed temperature', low=0, high=100)
        return Operation((f'M140 S{t:g}',), f"Set bed target to {t:g} C", True)

    if name in ('fan', 'speed', 'flow', 'linear-advance', 'z-babystep', 'idle-timeout'):
        if extra is not None:
            raise ConsoleError(f'{name} accepts exactly one value')
        if name == 'fan':
            pct = number(value, field='fan percentage', low=0, high=100)
            raw = round(pct * 255 / 100)
            cmd = 'M107' if raw == 0 else f'M106 S{raw}'
        elif name == 'speed':
            pct = number(value, field='speed percentage', low=25, high=200, integer=True)
            cmd = f'M220 S{int(pct)}'
        elif name == 'flow':
            pct = number(value, field='flow percentage', low=50, high=150, integer=True)
            cmd = f'M221 S{int(pct)}'
        elif name == 'linear-advance':
            k = number(value, field='linear advance K', low=0, high=1)
            cmd = f'M900 K{k:g}'
        elif name == 'z-babystep':
            step = number(value, field='babystep Z', low=-0.05, high=0.05)
            if step == 0:
                raise ConsoleError('Babystep must be non-zero')
            # P0 prevents unintended persistent changes to the BLTouch probe Z-offset.
            cmd = f'M290 P0 Z{step:g}'
        else:
            seconds = number(value, field='hotend idle timeout seconds', low=120, high=1800, integer=True)
            cmd = f'M86 S{int(seconds)} T180 E0 B0'
        return Operation((cmd,), f'Change {name}', True)

    if name == 'shaping':
        if not value or not extra or value.upper() not in ('X', 'Y'):
            raise ConsoleError('shaping requires axis X or Y and frequency Hz')
        hz = number(extra, field='input shaping frequency Hz', low=0, high=100)
        if hz != 0 and hz < 20:
            raise ConsoleError('Shaping frequency must be 0 (off) or 20-100 Hz')
        return Operation((f'M593 {value.upper()} F{hz:g}',), f'Set {value.upper()} shaping', True)

    if name in ('filament-sensor', 'recovery', 'level'):
        if extra is not None or value not in ('on', 'off'):
            raise ConsoleError(f'{name} requires on or off')
        code = {'filament-sensor':'M412', 'recovery':'M413', 'level':'M420'}[name]
        return Operation((f'{code} S{1 if value == "on" else 0}',), f'Set {name} {value}', True, value == 'on')

    if name in ('pause', 'resume', 'abort', 'save', 'reload', 'factory-defaults', 'home', 'emergency'):
        no_extra(value, extra)
        cmds = {'pause':'M25', 'resume':'M24', 'abort':'M524', 'save':'M500',
                'reload':'M501', 'factory-defaults':'M502', 'home':'G28', 'emergency':'M112'}
        return Operation((cmds[name],), name, True, name in {'abort', 'factory-defaults', 'home', 'emergency'},
                         timeout=40.0 if name == 'home' else 5.0)

    if name == 'pid-autotune':
        if extra is not None:
            raise ConsoleError('pid-autotune takes exactly one hotend target')
        ceiling = 215 if profile == 'stock' else 320
        t = number(value, field='PID autotune temperature', low=175, high=ceiling, integer=True)
        if profile == 'high-temp' and t > 215 and not hardware_confirmed:
            raise ConsoleError('High-temperature PID tuning requires --confirm-high-temp-hardware')
        return Operation((f'M303 E0 S{int(t)} C8',), 'Perform supervised heater PID autotune', True, True, 400.0)

    if name in ('macro-set', 'macro-run'):
        if value is None or not value.isascii() or not value.isdigit() or not (0 <= int(value) <= 3):
            raise ConsoleError('Macro slot must be an integer from 0 to 3')
        slot = int(value)
        cmd = f'M81{slot}'
        if name == 'macro-run':
            if extra is not None:
                raise ConsoleError('macro-run takes only a slot')
        else:
            if not extra or not extra.isascii() or any(ord(c) < 32 or ord(c) > 126 for c in extra):
                raise ConsoleError('Macro must be a printable ASCII command sequence')
            if len(extra) > 64 or len(cmd + ' ' + extra) > 96:
                raise ConsoleError('Macro exceeds firmware slot or command buffer')
            if any(c in extra for c in ('\\', '"')) or not all(part.strip() for part in extra.split('|')):
                raise ConsoleError('Macro cannot contain quotes, escapes, or empty commands')
            cmd += ' ' + extra
        return Operation((cmd,), f'{name} slot {slot}', True, True)

    raise ConsoleError(f'Unknown operation: {name}')


def validate_identity(session: spool.BinarySession) -> None:
    response = session.ascii_command('M115', timeout=5)
    if 'MACHINE_TYPE:KINGROON KP3S V1' not in ' '.join(response):
        raise ConsoleError('Device is not identified as KINGROON KP3S V1. No commands sent.')


def execute(session: spool.BinarySession, operation: Operation, *, execute_changes: bool = False, yes: bool = False) -> list[tuple[str, list[str]]]:
    if operation.mutating and not execute_changes:
        return [(c, ['DRY RUN - use --execute to send this command']) for c in operation.commands]
    if operation.high_risk and not yes:
        raise ConsoleError('This operation requires --execute --yes after checking the printer is safe')
    if operation.commands == ('M112',):
        session.ser.write(b'M112\n')
        session.ser.flush()
        return [('M112', ['Emergency stop sent; verify the physical machine.'])]
    validate_identity(session)
    result = []
    for cmd in operation.commands:
        result.append((cmd, session.ascii_command(cmd, timeout=operation.timeout)))
    return result


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description='KP3S read-only diagnostics and guarded runtime Marlin controls')
    p.add_argument('operation', nargs='?', help='status, position, settings, nozzle, bed, fan, shaping, macro-set, ...')
    p.add_argument('value', nargs='?', help='Numerical value, axis or slot')
    p.add_argument('extra', nargs='?', help='Shaping frequency or quoted macro script')
    p.add_argument('--port', help='Serial port e.g. /dev/ttyUSB0 or COM5')
    p.add_argument('--baud', type=int, default=250000)
    p.add_argument('--profile', choices=('stock', 'high-temp'), default='stock', help='Conservative temperature guard (default: stock)')
    p.add_argument('--confirm-high-temp-hardware', action='store_true', help='Affirm upgraded thermistor and all-metal heater assembly')
    p.add_argument('--execute', action='store_true', help='Actually send changing commands; otherwise show dry run')
    p.add_argument('--yes', action='store_true', help='Confirm high-risk actions')
    p.add_argument('--list-ports', action='store_true')
    p.add_argument('--list-actions', action='store_true')
    return p.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.list_actions:
        print('Read-only: ' + ', '.join(sorted(READ_COMMANDS)))
        print('Controls: nozzle TEMP, bed TEMP, fan PCT, speed PCT, flow PCT, linear-advance K, '
              'z-babystep MM, idle-timeout SECONDS, shaping X|Y HZ, filament-sensor on|off, '
              'recovery on|off, level on|off, pause, resume, abort, save, reload, '
              'factory-defaults, home, pid-autotune TEMP, macro-set SLOT "GCODE|...", macro-run SLOT, emergency')
        return 0
    if args.list_ports:
        print('\n'.join(spool.available_ports()) or 'No serial ports detected.')
        return 0
    if not args.operation:
        raise ConsoleError('Provide an operation or use --list-actions')
    op = action(args.operation, args.value, args.extra, profile=args.profile,
                hardware_confirmed=args.confirm_high_temp_hardware)
    if op.mutating and not args.execute:
        print(f'DRY RUN: {op.description}')
        for cmd in op.commands:
            print(f'  {cmd}')
        print('No serial connection opened. Add --execute to send; some commands also require --yes.')
        return 0
    if op.high_risk and not args.yes:
        raise ConsoleError('Review the physical machine and add --yes for this high-risk action')
    if not 9600 <= args.baud <= 1000000:
        raise ConsoleError('Baud rate out of supported host range')
    spool.require_pyserial()
    port = spool.discover_port(args.port)
    with spool.serial.Serial(port, args.baud, timeout=0.2, write_timeout=3) as ser:
        session = spool.BinarySession(ser, timeout=5.0)
        for cmd, responses in execute(session, op, execute_changes=args.execute, yes=args.yes):
            print('> ' + cmd)
            for line in responses:
                print('  ' + line)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ConsoleError, spool.TransferError) as exc:
        print(f'ERROR: {exc}', file=__import__('sys').stderr)
        raise SystemExit(2)
