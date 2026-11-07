#!/usr/bin/env python3
"""Offline regression checks for KP3S generator and serial host transport."""
from __future__ import annotations

from collections import deque
from pathlib import Path
from tempfile import TemporaryDirectory
import io
import subprocess
import sys
import unittest
from unittest import mock
import zipfile

import build_firmware as builder
import serial_spool as spool
import kp3s_console as console


class SimulatedMarlin:
    """Minimal protocol responder, not a substitute for a real board."""

    def __init__(self, *, buffer_size: int = 96, write_failure: bool = False,
                 selected: bool = True, correct_identity: bool = True):
        self.outgoing = deque()
        self.commands = []
        self.packets = []
        self.buffer_size = buffer_size
        self.write_failure = write_failure
        self.selected = selected
        self.correct_identity = correct_identity
        self.mode = 'ascii'

    def write(self, raw: bytes) -> int:
        if raw.endswith(b'\n'):
            command = raw.decode('ascii').strip()
            self.commands.append(command)
            if command == 'M28 B1':
                self.outgoing.append(b'ok\n')
                self.mode = 'binary'
            elif command == 'M115':
                if self.mode == 'ascii':
                    identity = 'KINGROON KP3S V1' if self.correct_identity else 'OTHER'
                    self.outgoing.append(f'FIRMWARE_NAME:Marlin MACHINE_TYPE:{identity}\n'.encode())
                    self.outgoing.append(b'ok\n')
            elif command.startswith('M23 '):
                if self.selected:
                    self.outgoing.append(b'File opened: DEMO.GCO Size: 4096\n')
                    self.outgoing.append(b'File selected\n')
                else:
                    self.outgoing.append(b'Not found\n')
                self.outgoing.append(b'ok\n')
            elif command == 'M27 C':
                self.outgoing.append(b'(no file)\n')
                self.outgoing.append(b'ok\n')
            elif command == 'M27':
                self.outgoing.append(b'SD printing byte 0/4096\n' if 'M24' in self.commands else b'Not SD printing\n')
                self.outgoing.append(b'ok\n')
            else:
                self.outgoing.append(b'ok\n')
        else:
            self.packets.append(raw)
            assert raw[:2] == b'\xad\xb5'
            sync = raw[2]
            proto = raw[3] >> 4
            opcode = raw[3] & 0x0f
            if proto == spool.PROTO_CONTROL and opcode == spool.CTRL_SYNC:
                self.outgoing.append(f'ss0,{self.buffer_size},0.1.0\n'.encode())
            else:
                self.outgoing.append(f'ok{sync}\n'.encode())
                if proto == spool.PROTO_FILE:
                    if opcode == spool.PFT_QUERY:
                        self.outgoing.append(b'PFT:version:0.1.0:compression:none\n')
                    elif opcode == spool.PFT_WRITE and self.write_failure:
                        self.outgoing.append(b'PFT:ioerror\n')
                    elif opcode in (spool.PFT_OPEN, spool.PFT_CLOSE, spool.PFT_ABORT):
                        self.outgoing.append(b'PFT:success\n')
                elif proto == spool.PROTO_CONTROL and opcode == spool.CTRL_CLOSE:
                    self.mode = 'ascii'
        return len(raw)

    def readline(self) -> bytes:
        return self.outgoing.popleft() if self.outgoing else b''

    def flush(self):
        pass


class ProtocolTests(unittest.TestCase):
    def test_known_sync_frame(self):
        self.assertEqual(spool.packet_bytes(0, 0, 1), bytes.fromhex('AD B5 00 01 00 00 01 03'))

    def test_83_filename(self):
        cases = ('Tiny.gcode', 'my favorite 3d benchy.gcode', 'file with üñicode.gcode',
                 'CON.gcode', 'LPT1.gcode', 'some.folder.gcode')
        for name in cases:
            with self.subTest(name=name):
                result = spool.safe_sd_name(Path(name), None)
                stem, ext = result.split('.')
                self.assertTrue(stem.isascii())
                self.assertTrue(1 <= len(stem) <= 8)
                self.assertTrue(all(c.isalnum() or c == '_' for c in stem))
                self.assertEqual(ext, 'GCO')
        self.assertEqual(spool.safe_sd_name(Path('Tiny.gcode'), None), 'TINY.GCO')
        self.assertNotEqual(spool.safe_sd_name(Path('long filename one.gcode'), None),
                            spool.safe_sd_name(Path('long filename two.gcode'), None))
        with self.assertRaises(spool.TransferError):
            spool.safe_sd_name(Path('foo.gcode'), 'BAD.bin')

    def test_full_transfer(self):
        client = SimulatedMarlin()
        session = spool.BinarySession(client)
        session.enter_binary()
        self.assertEqual(session.max_block, 96)
        self.assertIn('compression:none', session.query_file_protocol())
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'demo.gcode'
            path.write_bytes(b'G1 X10 Y10\n' * 80)
            name = spool.safe_sd_name(path, None)
            session.open_file(name)
            with mock.patch('sys.stdout', new_callable=io.StringIO):
                session.write_file(path)
            session.close_file()
        session.leave_binary()
        spool.start_local_print(session, name)
        self.assertIn('M115', client.commands)
        self.assertIn('M23 DEMO.GCO', client.commands)
        self.assertIn('M24', client.commands)
        self.assertIn('M27', client.commands)
        self.assertTrue(all(len(p) <= 2 + 6 + 96 + 2 for p in client.packets))

    def test_small_advertised_buffer_is_respected(self):
        session = spool.BinarySession(SimulatedMarlin(buffer_size=8))
        session.enter_binary()
        self.assertEqual(session.max_block, 8)

    def test_zero_advertised_buffer_rejected(self):
        with self.assertRaises(spool.TransferError):
            spool.BinarySession(SimulatedMarlin(buffer_size=0)).enter_binary()

    def test_transfer_io_error_blocks_completion(self):
        client = SimulatedMarlin(write_failure=True)
        session = spool.BinarySession(client)
        session.enter_binary()
        session.open_file('DEMO.GCO')
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'demo.gcode'
            path.write_text('G1 X20\n')
            with self.assertRaises(spool.TransferError):
                with mock.patch('sys.stdout', new_callable=io.StringIO):
                    session.write_file(path)
                session.close_file()
        self.assertNotIn('M24', client.commands)

    def test_wrong_identity_blocks_start(self):
        client = SimulatedMarlin(correct_identity=False)
        session = spool.BinarySession(client)
        session.enter_binary()
        with self.assertRaises(spool.TransferError):
            session.leave_binary()
        self.assertNotIn('M24', client.commands)

    def test_no_file_selection_blocks_start(self):
        client = SimulatedMarlin(selected=False)
        session = spool.BinarySession(client)
        with self.assertRaises(spool.TransferError):
            spool.start_local_print(session, 'DEMO.GCO')
        self.assertNotIn('M24', client.commands)

    def test_idle_status_must_be_explicit(self):
        class SilentSession:
            def ascii_command(self, *_args, **_kwargs):
                return ['ok']
        with self.assertRaises(spool.TransferError):
            spool.ensure_not_sd_printing(SilentSession())

    def test_active_sd_file_refuses_upload(self):
        class BusySession:
            def ascii_command(self, *_args, **_kwargs):
                return ['SD printing byte 10/100', 'ok']
        with self.assertRaises(spool.TransferError):
            spool.ensure_not_sd_printing(BusySession())

    def test_upload_only_is_parsed(self):
        with mock.patch.object(sys, 'argv', ['serial_spool.py', 'benchy.gcode', '--upload-only']):
            self.assertTrue(spool.parse_args().upload_only)

    def test_archive_traversal_rejected(self):
        with TemporaryDirectory() as directory:
            directory = Path(directory)
            bad_zip = directory / 'bad.zip'
            with zipfile.ZipFile(bad_zip, 'w') as archive:
                archive.writestr('../ESCAPE.txt', 'bad')
            with zipfile.ZipFile(bad_zip) as archive:
                with self.assertRaises(RuntimeError):
                    builder.safe_extract(archive, directory / 'generated')
            self.assertFalse((directory / 'ESCAPE.txt').exists())

    def test_high_temperature_ack_required_before_generation(self):
        script = Path(builder.__file__).resolve()
        result = subprocess.run([sys.executable, str(script), '--generate-only', '--hotend-profile', 'high-temp'],
                                text=True, capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('--confirm-high-temp-hardware', result.stderr)

    def test_oversize_binary_refused_before_flash_output(self):
        with TemporaryDirectory() as directory:
            image = Path(directory) / 'Robin_nano35.bin'
            with image.open('wb') as stream:
                stream.truncate(builder.MAX_FLASH_IMAGE_BYTES + 1)
            with self.assertRaisesRegex(RuntimeError, 'Unsafe firmware image size'):
                builder.prepare_flash_output(image)

    def test_static_generator_audit(self):
        builder.verify_release_tree()


class ExtendedProtocolTests(unittest.TestCase):
    """Boundary, timeout, malformed response and CLI checks with a virtual printer."""

    def test_packet_checksums_payload_and_fields(self):
        import struct
        payload = bytes(range(1, 40))
        frame = spool.packet_bytes(13, 1, spool.PFT_WRITE, payload)
        self.assertEqual(frame[:2], b'\xad\xb5')
        self.assertEqual(frame[2], 13)
        self.assertEqual(frame[3], 0x13)
        self.assertEqual(struct.unpack('<H', frame[4:6])[0], len(payload))
        self.assertEqual(struct.unpack('<H', frame[6:8])[0], spool.fletcher16(frame[2:6]))
        self.assertEqual(frame[8:-2], payload)
        self.assertEqual(struct.unpack('<H', frame[-2:])[0], spool.fletcher16(frame[2:-2]))
        self.assertEqual(spool.fletcher16(b''), 0)
        self.assertEqual(spool.fletcher16(bytes([255])), 0)

    def test_packet_large_payload_rejected(self):
        with self.assertRaises(ValueError):
            spool.packet_bytes(0, 1, 3, b'0' * 65536)

    def test_filename_explicit_root_only(self):
        for text in ('../evil.gcode', 'sub/evil.gcode', r'sub\evil.gcode'):
            with self.subTest(text=text), self.assertRaises(spool.TransferError):
                spool.safe_sd_name(Path('print.gcode'), text)

    def test_filename_edge_and_bad_extension(self):
        for text in ('', '.', '..'):
            with self.subTest(text=text), self.assertRaises(spool.TransferError):
                spool.safe_sd_name(Path('a.gcode'), text)
        for text in ('x.exe', 'x.tar.gz', 'bad.bin'):
            with self.subTest(text=text), self.assertRaises(spool.TransferError):
                spool.safe_sd_name(Path('a.gcode'), text)
        self.assertEqual(spool.safe_sd_name(Path('a.gcode'), 'NAME.gcode'), 'NAME.GCO')

    def test_ascii_success_with_ok_position_payload(self):
        ser = SimulatedMarlin()
        session = spool.BinarySession(ser)
        ser.outgoing.extend([b'X:0 Y:0\n', b'ok T:25\n'])
        result = session.ascii_command('M114')
        self.assertEqual(result, ['X:0 Y:0', 'ok T:25'])
        self.assertEqual(ser.commands[-1], 'M114')

    def test_ascii_error_and_timeout(self):
        client = SimulatedMarlin()
        client.outgoing.append(b'Error:Unknown command\n')
        with self.assertRaisesRegex(spool.TransferError, 'Unknown command'):
            spool.BinarySession(client).ascii_command('M117 BAD')
        class NeverRespond:
            def write(self, value): return len(value)
            def flush(self): pass
            def readline(self): return b''
        with self.assertRaisesRegex(spool.TransferError, 'Timed out'):
            spool.BinarySession(NeverRespond()).ascii_command('M115', timeout=0.003)
        self.assertEqual(spool.BinarySession(NeverRespond()).ascii_command('M155 S0', wait_ok=False), [])

    def test_sync_malformed_and_limits(self):
        for bsize in (0, -1, 65536):
            with self.subTest(buffer=bsize), self.assertRaises(spool.TransferError):
                spool.BinarySession(SimulatedMarlin(buffer_size=bsize)).enter_binary()
        session = spool.BinarySession(SimulatedMarlin(buffer_size=4096))
        session.enter_binary()
        self.assertEqual(session.max_block, 512)

    def test_open_packet_cannot_exceed_advertised_buffer(self):
        client = SimulatedMarlin(buffer_size=8)
        session = spool.BinarySession(client)
        session.enter_binary()
        sent_before = len(client.packets)
        with self.assertRaisesRegex(spool.TransferError, 'payload limit'):
            session.open_file('PRINT.GCO')
        self.assertEqual(len(client.packets), sent_before)

    def test_send_packet_checks_size_and_retries(self):
        class DropOnce(SimulatedMarlin):
            def __init__(self):
                super().__init__()
                self.dropped = False
            def write(self, raw):
                if not raw.endswith(b'\n') and raw[3] == 0x13 and not self.dropped:
                    self.packets.append(raw)
                    self.dropped = True
                    return len(raw)
                return super().write(raw)
        client = DropOnce()
        session = spool.BinarySession(client, timeout=0.003)
        session.enter_binary()
        session.send_packet(spool.PROTO_FILE, spool.PFT_WRITE, b'abc')
        self.assertTrue(client.dropped)
        self.assertEqual(session.sync, 1)
        with self.assertRaises(ValueError):
            session.send_packet(1, 3, retries=0)

    def test_sync_resend_protocol_and_fatal_error(self):
        class Resend(SimulatedMarlin):
            def __init__(self, response):
                super().__init__()
                self.response = response
                self.first = True
            def write(self, raw):
                if not raw.endswith(b'\n') and raw[3] == 0x13 and self.first:
                    self.first = False
                    self.outgoing.append(self.response)
                    return len(raw)
                return super().write(raw)
        client = Resend(b'rs255\n')
        session = spool.BinarySession(client)
        session.enter_binary()
        session.send_packet(1, 3, b'xyz')
        self.assertEqual(session.sync, 1)
        for bad in (b'rsNope\n', b'rs5\n'):
            client = Resend(bad)
            session = spool.BinarySession(client)
            session.enter_binary()
            with self.subTest(bad=bad), self.assertRaises(spool.TransferError):
                session.send_packet(1, 3, b'xyz')

    def test_pft_wait_failure_and_missing_response(self):
        class Quiet:
            def readline(self): return b''
        for response in (b'PFT:fail\n', b'PFT:busy\n', b'PFT:invalid\n', b'PFT:ioerror\n'):
            client = SimulatedMarlin()
            client.outgoing.append(response)
            with self.subTest(response=response), self.assertRaises(spool.TransferError):
                spool.BinarySession(client).wait_pft(('PFT:success',))
        with self.assertRaises(spool.TransferError):
            spool.BinarySession(Quiet()).wait_pft(('PFT:success',), timeout=0.003)

    def test_upload_open_packet_payload_layout(self):
        client = SimulatedMarlin()
        session = spool.BinarySession(client)
        session.enter_binary()
        session.open_file('DEMO.GCO')
        frame = client.packets[-1]
        self.assertEqual(frame[3], 0x11)
        self.assertEqual(frame[8:-2], b'\0\0DEMO.GCO\0')

    def test_abort_on_failed_write_and_suppress_abort_error(self):
        client = SimulatedMarlin()
        session = spool.BinarySession(client)
        session.enter_binary()
        session.open_file('TEST.GCO')
        session.abort_file()
        self.assertEqual(client.packets[-1][3], 0x14)
        with mock.patch.object(session, 'send_packet', side_effect=spool.TransferError('not opened')):
            session.abort_file()

    def test_probe_capabilities_checks_exact_requirements(self):
        needed = ('BINARY_FILE_TRANSFER', 'SDCARD', 'SD_WRITE', 'LONG_FILENAME',
                  'LFN_WRITE', 'AUTOREPORT_TEMP', 'AUTOREPORT_POS', 'AUTOREPORT_SD_STATUS')
        class FakeCapabilities:
            def ascii_command(self, *args, **kwargs):
                return ['FIRMWARE_NAME:Marlin MACHINE_TYPE:KINGROON KP3S V1'] + [f'Cap:{x}:1' for x in needed] + ['ok']
        spool.probe_capabilities(FakeCapabilities())
        class Incomplete:
            def ascii_command(self, *args, **kwargs):
                return ['FIRMWARE_NAME:Marlin MACHINE_TYPE:KINGROON KP3S V1', 'Cap:SDCARD:1', 'ok']
        with self.assertRaisesRegex(spool.TransferError, 'missing required'):
            spool.probe_capabilities(Incomplete())

    def test_port_discovery_cases(self):
        self.assertEqual(spool.discover_port('/dev/ttyUSB1'), '/dev/ttyUSB1')
        with mock.patch.object(spool, 'available_ports', return_value=['/dev/ttyUSB0']):
            self.assertEqual(spool.discover_port(None), '/dev/ttyUSB0')
        with mock.patch.object(spool, 'available_ports', return_value=[]):
            with self.assertRaisesRegex(spool.TransferError, 'No serial port'):
                spool.discover_port(None)
        with mock.patch.object(spool, 'available_ports', return_value=['p1', 'p2']):
            with self.assertRaisesRegex(spool.TransferError, 'Multiple serial ports'):
                spool.discover_port(None)
        with mock.patch.object(spool, 'serial', None):
            with self.assertRaisesRegex(spool.TransferError, 'pyserial'):
                spool.require_pyserial()

    def test_start_refuses_bad_name_and_failed_status(self):
        client = SimulatedMarlin()
        with self.assertRaises(spool.TransferError):
            spool.start_local_print(spool.BinarySession(client), 'BAD NAME.GCODE')
        self.assertFalse(client.commands)
        class NeverPrinted:
            def __init__(self): self.commands = []
            def ascii_command(self, command, **kwargs):
                self.commands.append(command)
                if command.startswith('M23'): return ['File selected', 'ok']
                if command == 'M27': return ['Not SD printing', 'ok']
                return ['ok']
        client = NeverPrinted()
        with self.assertRaisesRegex(spool.TransferError, 'did not confirm'):
            spool.start_local_print(client, 'TEST.GCO')
        self.assertIn('M24', client.commands)

    def test_short_job_can_complete_before_status(self):
        class FastFinish:
            def __init__(self): self.calls = []
            def ascii_command(self, command, **kwargs):
                self.calls.append(command)
                if command.startswith('M23'): return ['File selected', 'ok']
                if command == 'M24': return ['Done printing file', 'ok']
                if command == 'M27': return ['Not SD printing', 'ok']
                return ['ok']
        fake = FastFinish()
        spool.start_local_print(fake, 'FAST.GCO')
        self.assertEqual(fake.calls, ['M23 FAST.GCO', 'M24', 'M27'])

    def test_stop_auto_reports_attempts_all_commands(self):
        class PartialFailure:
            def __init__(self): self.calls = []
            def ascii_command(self, command, **kwargs):
                self.calls.append(command)
                if command == 'M154 S0': raise spool.TransferError('offline')
        fake = PartialFailure()
        spool.stop_auto_reports(fake)
        self.assertEqual(fake.calls, ['M155 S0', 'M154 S0', 'M27 S0'])

    def test_serial_cli_validation_and_list_ports(self):
        with mock.patch.object(sys, 'argv', ['serial_spool.py', '--list-ports']):
            with mock.patch.object(spool, 'available_ports', return_value=['COM42']):
                with mock.patch('sys.stdout', new_callable=io.StringIO) as output:
                    self.assertEqual(spool.main(), 0)
                    self.assertIn('COM42', output.getvalue())
        with mock.patch.object(sys, 'argv', ['serial_spool.py']):
            with self.assertRaisesRegex(spool.TransferError, 'required'):
                spool.main()
        with TemporaryDirectory() as td:
            path = Path(td) / 'bad.txt'
            path.write_text('G28\n')
            with mock.patch.object(sys, 'argv', ['serial_spool.py', str(path)]):
                with self.assertRaisesRegex(spool.TransferError, 'Input file must'):
                    spool.main()
            path = Path(td) / 'empty.gcode'
            path.write_text('')
            with mock.patch.object(sys, 'argv', ['serial_spool.py', str(path)]):
                with self.assertRaisesRegex(spool.TransferError, 'empty'):
                    spool.main()

    def test_binary_sync_failure_rejected(self):
        class BadSync(SimulatedMarlin):
            def write(self, data):
                if not data.endswith(b'\n') and data[3] == 1:
                    self.outgoing.append(b'fe:synchronization lost\n')
                    return len(data)
                return super().write(data)
        with self.assertRaisesRegex(spool.TransferError, 'fatal'):
            spool.BinarySession(BadSync()).enter_binary()


class BuilderToolingTests(unittest.TestCase):
    """Unit checks for generator helpers without claiming a Marlin C++ compilation."""

    def test_text_read_write_and_replace_once(self):
        with TemporaryDirectory() as td:
            p = Path(td) / 'test.h'
            builder.write(p, 'A\nB\n')
            self.assertEqual(builder.read(p), 'A\nB\n')
            builder.replace_once(p, 'A', 'C', 'single replacement')
            self.assertEqual(builder.read(p), 'C\nB\n')
            with self.assertRaises(RuntimeError):
                builder.replace_once(p, 'missing', 'X', 'absent replacement')
            builder.write(p, 'B B')
            with self.assertRaises(RuntimeError):
                builder.replace_once(p, 'B', 'C', 'duplicate replacement')

    def test_regex_and_insert_anchor_guards(self):
        with TemporaryDirectory() as td:
            p = Path(td) / 'config.h'
            builder.write(p, 'ONE\nTWO\n')
            builder.regex_once(p, r'^ONE$', 'NEW', 'replace')
            builder.insert_before_regex_once(p, r'^TWO$', 'HEAD\n', 'insert before')
            builder.insert_after_regex_once(p, r'^TWO$', '\nTAIL', 'insert after')
            self.assertEqual(builder.read(p), 'NEW\nHEAD\nTWO\nTAIL\n')
            for fn, args in (
                (builder.regex_once, (r'^MISS$', 'X', 'missing')),
                (builder.insert_before_regex_once, (r'^MISS$', 'X', 'missing')),
                (builder.insert_after_regex_once, (r'^MISS$', 'X', 'missing')),
            ):
                with self.subTest(name=fn.__name__), self.assertRaises(RuntimeError):
                    fn(p, *args)

    def test_set_define_and_boolean_toggle(self):
        with TemporaryDirectory() as td:
            path = Path(td) / 'config.h'
            path.write_text('//#define SENSOR 123\n#define LCD\n')
            builder.set_define(path, 'SENSOR', '#define SENSOR 61', 'sensor')
            builder.set_bool_define(path, 'LCD', False, 'disable LCD')
            self.assertEqual(path.read_text(), '#define SENSOR 61\n//#define LCD\n')
            builder.set_bool_define(path, 'LCD', True, 'enable LCD')
            self.assertIn('\n#define LCD\n', path.read_text())

    def test_zip_validation_good_and_bad(self):
        good = {
            'Marlin-x/platformio.ini': 'x',
            'Marlin-x/Marlin/Configuration.h': 'x',
            'Marlin-x/Marlin/src/lcd/marlinui.cpp': 'x',
            'Marlin-x/Marlin/src/inc/Conditionals-2-LCD.h': 'x',
            'Marlin-x/Marlin/src/inc/Version.h': '#define SHORT_BUILD_VERSION "2.1.3-beta3"\n#define MARLIN_HEX_VERSION 02010300\n',
            'Marlin-x/Marlin/src/module/settings.cpp': '#define EEPROM_VERSION "V00"\n} SettingsData;\n// Report final CRC and Data Size\n// Validate Final Size and CRC\n',
        }
        with TemporaryDirectory() as td:
            path = Path(td) / 'source.zip'
            with zipfile.ZipFile(path, 'w') as z:
                for name, data in good.items(): z.writestr(name, data)
            builder.validate_marlin_zip(path)
            good['Marlin-x/Marlin/src/inc/Version.h'] = 'not correct'
            with zipfile.ZipFile(path, 'w') as z:
                for name, data in good.items(): z.writestr(name, data)
            with self.assertRaisesRegex(RuntimeError, 'not the Marlin'):
                builder.validate_marlin_zip(path)
            path.write_bytes(b'not-a-zip')
            with self.assertRaisesRegex(RuntimeError, 'Invalid Marlin ZIP'):
                builder.validate_marlin_zip(path)

    def test_validate_configuration_files(self):
        with TemporaryDirectory() as td:
            file = Path(td) / 'Configuration.h'
            file.write_text('#define CONFIGURATION_H_VERSION 02010300\nBOARD_MKS_ROBIN_NANO\nKingroon/KP3S\n')
            builder.validate_config_h(file)
            file.write_text('#define CONFIGURATION_H_VERSION 02010300\n')
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                builder.validate_config_h(file)
            file = Path(td) / 'Configuration_adv.h'
            file.write_text('#define CONFIGURATION_ADV_H_VERSION 02010300\n//#define JOYSTICK\n#define JOY_X_PIN\n#define JOY_Y_PIN\n')
            builder.validate_config_adv(file)
            file.write_text('#define CONFIGURATION_ADV_H_VERSION 02010300')
            with self.assertRaisesRegex(RuntimeError, 'missing'):
                builder.validate_config_adv(file)

    def test_cache_valid_invalid_redownload_and_size(self):
        with TemporaryDirectory() as td:
            directory = Path(td)
            dest = directory / 'pkg.zip'
            dest.write_bytes(b'GOOD')
            def accept(path):
                if path.read_bytes() != b'GOOD': raise ValueError('cache invalid')
            with mock.patch.object(builder, 'CACHE', directory):
                with mock.patch.object(builder, 'download_with_curl') as curl:
                    builder.ensure_download('https://example.invalid', dest, 4, 'pkg', accept)
                    curl.assert_not_called()
                dest.write_bytes(b'BAD!')
                def download(url, path):
                    path.write_bytes(b'GOOD')
                    return True
                with mock.patch.object(builder, 'download_with_curl', side_effect=download):
                    builder.ensure_download('https://example.invalid', dest, 4, 'pkg', accept)
                    self.assertEqual(dest.read_bytes(), b'GOOD')
                dest.unlink()
                with mock.patch.object(builder, 'download_with_curl', return_value=False):
                    with mock.patch.object(builder, 'download_with_python', side_effect=lambda url, path: path.write_bytes(b'GOOD')):
                        builder.ensure_download('https://example.invalid', dest, 4, 'pkg', accept)
                        self.assertEqual(dest.read_bytes(), b'GOOD')
                dest.unlink()
                with mock.patch.object(builder, 'download_with_curl', return_value=True):
                    with self.assertRaisesRegex(RuntimeError, 'Invalid download'):
                        builder.ensure_download('https://example.invalid', dest, 4, 'pkg', accept)

    def test_safe_extract_good_and_absolute_path_rejection(self):
        with TemporaryDirectory() as td:
            target = Path(td) / 'output'
            with zipfile.ZipFile(Path(td) / 'safe.zip', 'w') as z:
                z.writestr('Marlin/Configuration.h', 'content')
            with zipfile.ZipFile(Path(td) / 'safe.zip') as z:
                builder.safe_extract(z, target)
            self.assertEqual((target / 'Marlin' / 'Configuration.h').read_text(), 'content')
            with zipfile.ZipFile(Path(td) / 'unsafe.zip', 'w') as z:
                z.writestr('/tmp/hack', 'bad')
            with zipfile.ZipFile(Path(td) / 'unsafe.zip') as z:
                # Python Path.joinpath discards the destination on absolute filenames.
                with self.assertRaisesRegex(RuntimeError, 'Unsafe path'):
                    builder.safe_extract(z, target)

    def test_preprocessor_balance(self):
        with TemporaryDirectory() as td:
            path = Path(td) / 'test.cpp'
            path.write_text('#if A\n#ifdef B\n#endif\n#endif\n')
            builder.verify_preprocessor_balance(path)
            path.write_text('#endif\n')
            with self.assertRaisesRegex(RuntimeError, 'extra #endif'):
                builder.verify_preprocessor_balance(path)
            path.write_text('#if A\n#ifdef B\n#endif\n')
            with self.assertRaisesRegex(RuntimeError, 'unterminated'):
                builder.verify_preprocessor_balance(path)

    def test_sha256_and_flash_output_integrity(self):
        import hashlib
        with TemporaryDirectory() as td:
            td = Path(td)
            source = td / 'Robin_nano35.bin'
            source.write_bytes(bytes(range(256)) * 64)
            with mock.patch.object(builder, 'FW_OUT', td / 'firmware_output'):
                with mock.patch.object(builder, 'FLASH_DIR', td / 'firmware_output' / 'FLASH_KP3S'):
                    result = builder.prepare_flash_output(source)
                    self.assertEqual(result.name, 'Robin_nano.bin')
                    self.assertEqual(result.read_bytes(), source.read_bytes())
                    digest = hashlib.sha256(source.read_bytes()).hexdigest()
                    self.assertEqual(builder.sha256_file(result), digest)
                    self.assertIn(digest, (td / 'firmware_output' / 'SHA256.txt').read_text())
                    self.assertIn('FAT32', (td / 'firmware_output' / 'FLASH_README.txt').read_text())

    def test_too_small_flash_binary_rejected(self):
        with TemporaryDirectory() as td:
            path = Path(td) / 'small.bin'
            path.write_bytes(b'0' * 15_000)
            with self.assertRaisesRegex(RuntimeError, 'Unsafe firmware image size'):
                builder.prepare_flash_output(path)

    def test_command_runner_exit_status(self):
        with mock.patch.object(builder.subprocess, 'run', return_value=mock.Mock(returncode=0)) as proc:
            self.assertEqual(builder.run(['echo', 'test']), 0)
            proc.assert_called_once()
        with mock.patch.object(builder.subprocess, 'run', return_value=mock.Mock(returncode=12)):
            with self.assertRaisesRegex(RuntimeError, 'exit code 12'):
                builder.run(['command', 'fail'])
            self.assertEqual(builder.run(['command', 'fail'], check=False), 12)

    def test_toolchain_version_parsing_and_selection(self):
        result = mock.Mock(returncode=0, stdout='PlatformIO Core, version 6.1.19')
        with mock.patch.object(builder.subprocess, 'run', return_value=result):
            self.assertEqual(builder.platformio_version(Path('/tmp/pio')), '6.1.19')
        result.stdout = 'Something else'
        with mock.patch.object(builder.subprocess, 'run', return_value=result):
            self.assertIsNone(builder.platformio_version(Path('/tmp/pio')))
        result.returncode = 1
        with mock.patch.object(builder.subprocess, 'run', return_value=result):
            self.assertIsNone(builder.platformio_version(Path('/tmp/pio')))
        with TemporaryDirectory() as td:
            exe = Path(td) / 'pio'
            exe.write_text('placeholder')
            with mock.patch.object(builder, 'pio_candidates', return_value=[exe]):
                with mock.patch.object(builder, 'platformio_version', return_value='6.1.19'):
                    self.assertEqual(builder.find_platformio(), exe)
                with mock.patch.object(builder, 'platformio_version', return_value='6.2.0'):
                    self.assertIsNone(builder.find_platformio())

    def test_parse_build_modes_and_high_temp_guard(self):
        import contextlib
        for mode in ('--generate-only', '--build'):
            with mock.patch.object(sys, 'argv', ['build_firmware.py', mode, '--hotend-profile', 'high-temp']):
                with self.assertRaises(SystemExit) as result, contextlib.redirect_stderr(io.StringIO()):
                    builder.parse_args()
                self.assertEqual(result.exception.code, 2)
        for mode in ('--generate-only', '--build', '--audit-only', '--clean'):
            argv = ['build_firmware.py', mode]
            with mock.patch.object(sys, 'argv', argv):
                args = builder.parse_args()
                self.assertTrue(getattr(args, mode.lstrip('-').replace('-', '_')))
        with mock.patch.object(sys, 'argv', ['build_firmware.py', '--build', '--clean']):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                builder.parse_args()

    def test_cleanup_generated_directories(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            targets = [td / s for s in ('generated', 'firmware_output', 'cache', 'build_env', '__pycache__')]
            for target in targets:
                target.mkdir()
                (target / 'x').write_text('x')
            log = td / 'BUILD.log'
            log.write_text('x')
            with mock.patch.multiple(builder, OUT=targets[0], FW_OUT=targets[1], CACHE=targets[2],
                                     BASE=td, LOG=log):
                # builder.clean checks the local .build_env, not build_env.
                (td / '.build_env').mkdir()
                builder.clean()
                self.assertFalse(log.exists())
                self.assertFalse(targets[0].exists())
                self.assertFalse(targets[1].exists())
                self.assertFalse(targets[2].exists())
                self.assertFalse((td / '.build_env').exists())

    def test_script_syntax_and_linux_launchers(self):
        root = Path(builder.__file__).resolve().parent
        import ast
        for path in root.glob('*.py'):
            ast.parse(path.read_text(), filename=str(path))
        for name in ('BUILD_FIRMWARE.sh', 'SERIAL_SPOOL.sh'):
            proc = subprocess.run(['bash', '-n', str(root / name)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)


class IntegrationAndFailureTests(unittest.TestCase):
    """End-to-end mocked CLI paths and remaining generator dependencies."""

    def test_serial_upload_only_main_virtual_board(self):
        from types import SimpleNamespace
        supported = (
            'BINARY_FILE_TRANSFER', 'SDCARD', 'SD_WRITE', 'LONG_FILENAME',
            'LFN_WRITE', 'AUTOREPORT_TEMP', 'AUTOREPORT_POS', 'AUTOREPORT_SD_STATUS',
        )
        class Firmware(SimulatedMarlin):
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def reset_input_buffer(self): self.outgoing.clear()
            def write(self, raw):
                if raw == b'M115\n':
                    self.commands.append('M115')
                    self.outgoing.append(b'FIRMWARE_NAME:Marlin MACHINE_TYPE:KINGROON KP3S V1\n')
                    self.outgoing.extend(f'Cap:{key}:1\n'.encode() for key in supported)
                    self.outgoing.append(b'ok\n')
                    return len(raw)
                return super().write(raw)
        with TemporaryDirectory() as td:
            file = Path(td) / 'my house model.gcode'
            file.write_bytes(b'G28\nG1 X20 Y20 F1200\n' * 8)
            for upload_only in (True, False):
                with self.subTest(upload_only=upload_only):
                    client = Firmware()
                    args = ['serial_spool.py', str(file), '--port', 'SIMULATED', '--no-monitor']
                    if upload_only: args.append('--upload-only')
                    with mock.patch.object(sys, 'argv', args), \
                         mock.patch.object(spool, 'serial', SimpleNamespace(Serial=lambda *a, **kw: client)), \
                         mock.patch.object(spool, 'list_ports', SimpleNamespace(comports=lambda: [])), \
                         mock.patch.object(spool.time, 'sleep', return_value=None), \
                         mock.patch('sys.stdout', new_callable=io.StringIO):
                        self.assertEqual(spool.main(), 0)
                    self.assertIn('M28 B1', client.commands)
                    self.assertIn('M115', client.commands)
                    self.assertIn('M27', client.commands)
                    self.assertTrue(any(p[3] == 0x13 for p in client.packets))
                    if upload_only:
                        self.assertFalse(any(cmd.startswith('M23 ') for cmd in client.commands))
                        self.assertNotIn('M24', client.commands)
                    else:
                        self.assertIn('M24', client.commands)
                        self.assertTrue(any(cmd.startswith('M23 ') for cmd in client.commands))

    def test_serial_main_refuses_wrong_firmware_before_transfer(self):
        from types import SimpleNamespace
        class Wrong(SimulatedMarlin):
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def reset_input_buffer(self): self.outgoing.clear()
        with TemporaryDirectory() as td:
            path = Path(td) / 'job.gcode'
            path.write_text('G28\n')
            client = Wrong(correct_identity=False)
            with mock.patch.object(sys, 'argv', ['serial_spool.py', str(path), '--port', 'SIM']), \
                 mock.patch.object(spool, 'serial', SimpleNamespace(Serial=lambda *a, **kw: client)), \
                 mock.patch.object(spool, 'list_ports', SimpleNamespace(comports=lambda: [])), \
                 mock.patch.object(spool.time, 'sleep', return_value=None), \
                 mock.patch('sys.stdout', new_callable=io.StringIO):
                with self.assertRaisesRegex(spool.TransferError, 'not identified'):
                    spool.main()
            self.assertNotIn('M28 B1', client.commands)

    def test_monitor_all_supported_commands(self):
        # Feed UI commands synchronously into the internal queue. No motion is sent.
        class MockThread:
            def __init__(self, target, daemon=False): self.target = target
            def start(self): self.target()
        class Serial:
            def readline(self): return b''
        class Session:
            def __init__(self): self.commands = []; self.ser = Serial()
            def ascii_command(self, command, **kwargs):
                self.commands.append(command)
                return ['ok']
        actions = iter(('pause', 'resume', 'status', 'abort', 'quit'))
        def user_input():
            try: return next(actions)
            except StopIteration: raise EOFError()
        session = Session()
        with mock.patch.object(spool.threading, 'Thread', MockThread), \
             mock.patch('builtins.input', side_effect=user_input), \
             mock.patch('sys.stdout', new_callable=io.StringIO):
            spool.monitor(session)
        for cmd in ('M25', 'M24', 'M27', 'M105', 'M114', 'M524', 'M155 S0', 'M154 S0', 'M27 S0'):
            self.assertIn(cmd, session.commands)

    def test_monitor_finishes_after_completed_job_line(self):
        class MockThread:
            def __init__(self, target, daemon=False): self.target = target
            def start(self): pass  # Non-interactive host, only serial completion line.
        class Serial:
            def readline(self): return b'Done printing file\n'
        class Session:
            def __init__(self): self.commands = []; self.ser = Serial()
            def ascii_command(self, command, **kwargs): self.commands.append(command)
        session = Session()
        with mock.patch.object(spool.threading, 'Thread', MockThread), \
             mock.patch('sys.stdout', new_callable=io.StringIO) as output:
            spool.monitor(session)
        self.assertIn('Print monitoring finished.', output.getvalue())
        self.assertIn('M27 S0', session.commands)

    def test_writer_cleanly_handles_zero_length_and_sync_rollover(self):
        client = SimulatedMarlin()
        session = spool.BinarySession(client)
        session.enter_binary()
        session.sync = 254
        # Reset sync to 0 by sending two frames; ack based on host frame.
        session.send_packet(1, spool.PFT_WRITE, b'A')
        self.assertEqual(session.sync, 255)
        session.send_packet(1, spool.PFT_WRITE, b'B')
        self.assertEqual(session.sync, 0)
        with TemporaryDirectory() as td:
            file = Path(td) / 'empty.gcode'
            file.write_bytes(b'')
            with mock.patch('sys.stdout', new_callable=io.StringIO):
                session.write_file(file)

    def test_generator_tee_and_formatting(self):
        a, b = io.StringIO(), io.StringIO()
        tee = builder.Tee(a, b)
        self.assertEqual(tee.write('hello'), 5)
        tee.flush()
        self.assertEqual(a.getvalue(), 'hello')
        self.assertEqual(b.getvalue(), 'hello')
        self.assertIn('hello world', builder.cmdline(['hello', 'world']))

    def test_python_downloader_offline_mock(self):
        from contextlib import contextmanager
        @contextmanager
        def url_stream():
            yield io.BytesIO(b'UPSTREAM DATA')
        with TemporaryDirectory() as td:
            dest = Path(td) / 'artifact.zip'
            with mock.patch.object(builder.urllib.request, 'urlopen', return_value=url_stream()):
                with mock.patch.object(builder.time, 'sleep'):
                    builder.download_with_python('https://example.invalid/firmware', dest)
            self.assertEqual(dest.read_bytes(), b'UPSTREAM DATA')

    def test_curl_download_failure_and_success_offline_mock(self):
        with TemporaryDirectory() as td:
            dest = Path(td) / 'download.zip'
            with mock.patch.object(builder.shutil, 'which', return_value=None):
                self.assertFalse(builder.download_with_curl('https://example.invalid', dest))
            def succeed(cmd, **kwargs):
                Path(cmd[cmd.index('-o') + 1]).write_bytes(b'OK')
                return 0
            with mock.patch.object(builder.shutil, 'which', return_value='/usr/bin/curl'), \
                 mock.patch.object(builder, 'run', side_effect=succeed):
                self.assertTrue(builder.download_with_curl('https://example.invalid', dest))
            self.assertEqual(dest.read_bytes(), b'OK')

    def test_extract_marlin_minimal_zip(self):
        with TemporaryDirectory() as td:
            td = Path(td)
            source_zip = td / 'Marlin.zip'
            with zipfile.ZipFile(source_zip, 'w') as z:
                z.writestr('Marlin-pinned/platformio.ini', '[env]')
                z.writestr('Marlin-pinned/Marlin/Configuration.h', 'default')
                z.writestr('Marlin-pinned/Marlin/Configuration_adv.h', 'default advanced')
            ch = td / 'Configuration.h'
            adv = td / 'Configuration_adv.h'
            ch.write_text('Kingroon config')
            adv.write_text('Kingroon advanced')
            out = td / 'generated' / 'Marlin-KP3S-Firmware-V1'
            with mock.patch.multiple(builder, MARLIN_ZIP=source_zip, CONFIG_H=ch, CONFIG_ADV_H=adv, OUT=out):
                builder.extract_marlin()
            self.assertEqual((out / 'Marlin' / 'Configuration.h').read_text(), 'Kingroon config')
            self.assertEqual((out / 'Marlin' / 'Configuration_adv.h').read_text(), 'Kingroon advanced')

    def test_native_language_patch_applies_every_key(self):
        keys = sorted({key for values in builder.V1_NATIVE_LANGUAGE_SUPPLEMENTS.values() for key in values})
        with TemporaryDirectory() as td:
            out = Path(td)
            lang = out / 'Marlin' / 'src' / 'lcd' / 'language'
            lang.mkdir(parents=True)
            (lang / 'language_en.h').write_text('\n'.join(f'LSTR {key} = _UxGT("English");' for key in keys))
            for code in builder.V1_NATIVE_LANGUAGE_SUPPLEMENTS:
                (lang / f'language_{code}.h').write_text(
                    f'namespace LanguageNarrow_{code} {{\n}}\nnamespace LanguageWide_{code} {{\n}}\n'
                )
            with mock.patch.object(builder, 'OUT', out), mock.patch('sys.stdout', new_callable=io.StringIO):
                builder.patch_v1_native_languages()
            for code in builder.V1_NATIVE_LANGUAGE_SUPPLEMENTS:
                content = (lang / f'language_{code}.h').read_text()
                for key in keys:
                    self.assertEqual(content.count(f'LSTR {key} '), 1, (code, key))

    def test_native_language_patch_rejects_undefined_key(self):
        with TemporaryDirectory() as td:
            out = Path(td)
            lang = out / 'Marlin' / 'src' / 'lcd' / 'language'
            lang.mkdir(parents=True)
            (lang / 'language_en.h').write_text('no known keys')
            with mock.patch.object(builder, 'OUT', out):
                with self.assertRaisesRegex(RuntimeError, 'Unknown V1 Marlin language keys'):
                    builder.patch_v1_native_languages()

    def test_build_mocked_toolchain_and_flash_image(self):
        with TemporaryDirectory() as td:
            out = Path(td)
            image = out / '.pio' / 'build' / builder.ENV / builder.BUILD_BINARY
            image.parent.mkdir(parents=True)
            image.write_bytes(b'Z' * 16384)
            with mock.patch.object(builder, 'OUT', out), \
                 mock.patch.object(builder, 'FW_OUT', out / 'firmware_output'), \
                 mock.patch.object(builder, 'find_platformio', return_value=Path('/mock/pio')), \
                 mock.patch.object(builder, 'run', return_value=0) as commands, \
                 mock.patch.object(builder, 'prepare_flash_output', return_value=image) as flash:
                (out / 'firmware_output').mkdir()
                builder.build()
                manifest = (out / 'firmware_output' / 'BUILD_MANIFEST.json').read_text()
                self.assertIn('"thermal_profile": "stock"', manifest)
                self.assertIn('"control_hardware_profile": "nokia5110-samsung-ue5000"', manifest)
                self.assertIn('"hardware_validation": "NOT PERFORMED', manifest)
            self.assertEqual(commands.call_count, 2)
            self.assertIn('pkg', commands.call_args_list[0].args[0])
            self.assertIn('run', commands.call_args_list[1].args[0])
            flash.assert_called_once_with(image)

    def test_build_refuses_missing_toolchain_and_missing_image(self):
        with mock.patch.object(builder, 'find_platformio', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'toolchain'):
                builder.build()
        with TemporaryDirectory() as td:
            with mock.patch.object(builder, 'OUT', Path(td)), \
                 mock.patch.object(builder, 'find_platformio', return_value=Path('/mock/pio')), \
                 mock.patch.object(builder, 'run', return_value=0):
                with self.assertRaisesRegex(RuntimeError, 'was not found'):
                    builder.build()

    def test_generator_main_dispatch_offline(self):
        from types import SimpleNamespace
        with TemporaryDirectory() as td:
            fake_output = Path(td) / 'output'
            fake_output.mkdir()
            (Path(td) / 'generated').mkdir()
            fake = SimpleNamespace(clean=False, audit_only=False, build=False, auto_toolchain=False, pio=None, hotend_profile='high-temp', enable_arcs=False)
            with mock.patch.object(builder, 'OUT', Path(td) / 'generated'), \
                 mock.patch.object(builder, 'FW_OUT', fake_output), \
                 mock.patch.object(builder, 'ensure_download'), \
                 mock.patch.object(builder, 'extract_marlin') as extract, \
                 mock.patch.object(builder, 'patch_configuration'), \
                 mock.patch.object(builder, 'verify_release_tree'), \
                 mock.patch.object(builder, 'verify_project'), \
                 mock.patch.object(builder, 'build') as compiled, \
                 mock.patch('sys.stdout', new_callable=io.StringIO):
                builder.main(fake)
                compiled.assert_not_called()
                fake.build = True
                builder.main(fake)
                compiled.assert_called_once()
                self.assertFalse(fake_output.exists())
                fake.audit_only = True
                compiled.reset_mock()
                builder.main(fake)
                compiled.assert_not_called()


class SdSafetyAndStateTests(unittest.TestCase):
    def test_paused_or_selected_file_refused(self):
        class Paused:
            def __init__(self): self.calls = []
            def ascii_command(self, cmd, **kw):
                self.calls.append(cmd)
                if cmd == 'M27': return ['Not SD printing', 'ok']
                return ['Current file: PAUSED.GCO', 'ok']
        paused = Paused()
        with self.assertRaisesRegex(spool.TransferError, 'no SD file is open'):
            spool.ensure_not_sd_printing(paused)
        self.assertEqual(paused.calls, ['M27', 'M27 C'])

    def test_unrecognized_open_file_status_is_not_assumed_safe(self):
        class Unknown:
            def ascii_command(self, cmd, **kw):
                return ['Not SD printing', 'ok'] if cmd == 'M27' else ['ok']
        with self.assertRaisesRegex(spool.TransferError, 'no SD file is open'):
            spool.ensure_not_sd_printing(Unknown())

    def test_explicit_no_open_file_allows_upload(self):
        class Clear:
            def ascii_command(self, cmd, **kw):
                return ['Not SD printing', 'ok'] if cmd == 'M27' else ['(no file)', 'ok']
        spool.ensure_not_sd_printing(Clear())

    def test_failed_start_m24_does_not_enable_reports(self):
        class Refused:
            def __init__(self): self.commands = []
            def ascii_command(self, cmd, **kw):
                self.commands.append(cmd)
                if cmd.startswith('M23 '): return ['File selected', 'ok']
                if cmd == 'M24': raise spool.TransferError('Cannot start print')
                return ['ok']
        client = Refused()
        with self.assertRaisesRegex(spool.TransferError, 'Cannot start'):
            spool.start_local_print(client, 'PART.GCO')
        self.assertEqual(client.commands, ['M23 PART.GCO', 'M24'])


class ProtocolCompatibilityTests(unittest.TestCase):
    def test_version_compatibility(self):
        for response in ('PFT:version:0.1.0:compression:none',
                         'PFT:version:0.1.0:compression:heatshrink,8,4'):
            with self.subTest(response=response):
                with mock.patch.object(spool.BinarySession, 'send_packet'):
                    with mock.patch.object(spool.BinarySession, 'wait_pft', return_value=response):
                        self.assertEqual(spool.BinarySession(None).query_file_protocol(), response)

    def test_unrecognized_binary_protocol_rejected(self):
        for response in ('PFT:version:1.0.0:compression:none',
                         'PFT:version:0.1.0:compression:custom',
                         'PFT:version:invalid'):
            with self.subTest(response=response):
                with mock.patch.object(spool.BinarySession, 'send_packet'):
                    with mock.patch.object(spool.BinarySession, 'wait_pft', return_value=response):
                        with self.assertRaisesRegex(spool.TransferError, 'Unsupported'):
                            spool.BinarySession(None).query_file_protocol()


class EnhancedFirmwareAndConsoleTests(unittest.TestCase):
    """Safety boundary and feature dispatch tests without touching a printer."""

    def test_watchdog_patching_from_active_or_commented_upstream(self):
        with TemporaryDirectory() as tmp:
            path=Path(tmp) / 'Configuration_adv.h'
            for initial in ('//#define USE_WATCHDOG', '#define USE_WATCHDOG'):
                with self.subTest(initial=initial):
                    path.write_text(initial + '\n')
                    builder.set_bool_define(path, 'USE_WATCHDOG', True, 'Keep hardware watchdog')
                    self.assertEqual(path.read_text(), '#define USE_WATCHDOG\n')

    def test_watchdog_required_in_generator_validation(self):
        source = Path(builder.__file__).read_text()
        self.assertIn('set_bool_define(adv, "USE_WATCHDOG", True', source)
        self.assertIn('Safety protection disabled: {safety_define}', source)

    def test_thermal_profiles_are_consistent(self):
        for key, expected in {'stock': (1, 235, 250, 15), 'high-temp': (61, 340, 350, 10)}.items():
            with self.subTest(key=key):
                p = builder.HOTEND_PROFILES[key]
                p.validate()
                self.assertEqual((p.sensor, p.target_max, p.cutoff, p.overshoot), expected)

    def test_bad_thermal_profiles_are_rejected(self):
        for params in [(1, 235, 350, 15), (1, 390, 400, 10), (1, 50, 65, 15), (61, 340, 350, 9)]:
            with self.subTest(params=params), self.assertRaises(ValueError):
                builder.HotendProfile('bad', *params, 'invalid').validate()

    def test_high_temperature_generation_requires_hardware_acknowledgement(self):
        with mock.patch.object(sys, 'argv', ['build_firmware.py', '--generate-only', '--hotend-profile', 'high-temp']):
            with self.assertRaises(SystemExit):
                with mock.patch('sys.stderr', new_callable=io.StringIO):
                    builder.parse_args()

    def test_stock_generation_does_not_require_upgraded_hardware_acknowledgement(self):
        with mock.patch.object(sys, 'argv', ['build_firmware.py', '--generate-only', '--hotend-profile', 'stock']):
            a = builder.parse_args()
        self.assertEqual(a.hotend_profile, 'stock')
        self.assertTrue(a.enable_arcs)

    def test_optional_arc_firmware_switches(self):
        for option, expected in [('--disable-arcs', False), ('--enable-arcs', True)]:
            with self.subTest(option=option):
                with mock.patch.object(sys, 'argv', ['builder', '--generate-only', '--hotend-profile', 'stock', option]):
                    self.assertEqual(builder.parse_args().enable_arcs, expected)

    def test_high_temp_profile_acknowledged(self):
        with mock.patch.object(sys, 'argv', ['builder', '--generate-only', '--hotend-profile', 'high-temp', '--confirm-high-temp-hardware']):
            self.assertEqual(builder.parse_args().hotend_profile, 'high-temp')

    def test_profile_command_has_no_raw_overrides(self):
        with mock.patch.object(sys, 'argv', ['builder', '--generate-only', '--hotend-profile', 'custom']):
            with self.assertRaises(SystemExit):
                with mock.patch('sys.stderr', new_callable=io.StringIO):
                    builder.parse_args()

    def test_all_report_groups_are_read_only(self):
        self.assertTrue({'status', 'motion', 'shaping-status', 'macros', 'idle-timeout-status'} <= set(console.READ_COMMANDS))
        for operation in console.READ_COMMANDS:
            with self.subTest(operation=operation):
                op = console.action(operation, None, None, profile='stock', hardware_confirmed=False)
                self.assertFalse(op.mutating)
                self.assertFalse(op.high_risk)
                self.assertTrue(all(cmd[0] in 'GM' for cmd in op.commands))

    def test_temperature_profiles_restrict_high_targets(self):
        for bad in ('236', '340', 'nan', 'inf', '-1', 'bad'):
            with self.subTest(value=bad), self.assertRaises(console.ConsoleError):
                console.action('nozzle', bad, None, profile='stock', hardware_confirmed=False)
        with self.assertRaises(console.ConsoleError):
            console.action('nozzle', '300', None, profile='high-temp', hardware_confirmed=False)
        op = console.action('nozzle', '300', None, profile='high-temp', hardware_confirmed=True)
        self.assertEqual(op.commands, ('M104 S300',))
        self.assertTrue(op.high_risk)
        with self.assertRaises(console.ConsoleError):
            console.action('nozzle', '341', None, profile='high-temp', hardware_confirmed=True)

    def test_temperature_zero_and_normal_range(self):
        self.assertEqual(console.action('nozzle', '0', None, profile='stock', hardware_confirmed=False).commands, ('M104 S0',))
        self.assertEqual(console.action('bed', '60', None, profile='stock', hardware_confirmed=False).commands, ('M140 S60',))
        with self.assertRaises(console.ConsoleError):
            console.action('bed', '101', None, profile='stock', hardware_confirmed=False)

    def test_fan_and_speed_and_flow_control_codes(self):
        cases = [('fan','0','M107'), ('fan','100','M106 S255'), ('speed','75','M220 S75'),
                 ('flow','98','M221 S98'), ('linear-advance','0.22','M900 K0.22'),
                 ('z-babystep','-0.02','M290 P0 Z-0.02'),
                 ('idle-timeout','600','M86 S600 T180 E0 B0')]
        for name, value, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(console.action(name, value, None, profile='stock', hardware_confirmed=False).commands, (expected,))

    def test_out_of_bounds_tuning_is_rejected(self):
        for name, value in [('fan','101'), ('speed','500'), ('speed','80.25'), ('flow','10'),
                            ('linear-advance','3'), ('z-babystep','0.1'), ('z-babystep','0'),
                            ('idle-timeout','0'), ('idle-timeout','120.4')]:
            with self.subTest(name=name, value=value), self.assertRaises(console.ConsoleError):
                console.action(name, value, None, profile='stock', hardware_confirmed=False)

    def test_shaping_uses_axis_specific_m593(self):
        op = console.action('shaping','y','36.2',profile='stock',hardware_confirmed=False)
        self.assertEqual(op.commands, ('M593 Y F36.2',))
        self.assertEqual(console.action('shaping','X','0',profile='stock',hardware_confirmed=False).commands, ('M593 X F0',))
        for axis, hz in [('Z','25'), ('X','5'), ('X','101'), ('Y','nan')]:
            with self.subTest(axis=axis,hz=hz), self.assertRaises(console.ConsoleError):
                console.action('shaping',axis,hz,profile='stock',hardware_confirmed=False)

    def test_filament_level_and_recovery_switches(self):
        for name, g in [('filament-sensor','M412'), ('recovery','M413'), ('level','M420')]:
            with self.subTest(name=name):
                off = console.action(name,'off',None,profile='stock',hardware_confirmed=False)
                on = console.action(name,'on',None,profile='stock',hardware_confirmed=False)
                self.assertEqual(off.commands, (g+' S0',))
                self.assertEqual(on.commands, (g+' S1',))
                self.assertTrue(on.high_risk)

    def test_basic_print_and_persistence_operations(self):
        for name, g in [('pause','M25'), ('resume','M24'), ('abort','M524'),
                        ('save','M500'), ('reload','M501'), ('factory-defaults','M502'), ('home','G28')]:
            with self.subTest(name=name):
                op = console.action(name,None,None,profile='stock',hardware_confirmed=False)
                self.assertEqual(op.commands,(g,))
                self.assertTrue(op.mutating)
        self.assertTrue(console.action('abort',None,None,profile='stock',hardware_confirmed=False).high_risk)
        self.assertTrue(console.action('home',None,None,profile='stock',hardware_confirmed=False).high_risk)

    def test_pid_autotune_requires_confirmation_and_temperature_guard(self):
        with self.assertRaises(console.ConsoleError):
            console.action('pid-autotune','300',None,profile='stock',hardware_confirmed=False)
        with self.assertRaises(console.ConsoleError):
            console.action('pid-autotune','280',None,profile='high-temp',hardware_confirmed=False)
        o=console.action('pid-autotune','280',None,profile='high-temp',hardware_confirmed=True)
        self.assertEqual(o.commands, ('M303 E0 S280 C8',))
        self.assertTrue(o.high_risk)
        self.assertGreater(o.timeout,300)

    def test_macro_length_and_slot_limits(self):
        o=console.action('macro-set','1','M105|M114',profile='stock',hardware_confirmed=False)
        self.assertEqual(o.commands, ('M811 M105|M114',))
        self.assertTrue(o.high_risk)
        for slot,script in [('4','M105'), ('-1','M105'), ('foo','M105'), ('0','A'*65),
                            ('0','M105|'), ('1','M105\nM112'), ('0',''), ('0','M105\\M112')]:
            with self.subTest(slot=slot,script=script), self.assertRaises(console.ConsoleError):
                console.action('macro-set',slot,script,profile='stock',hardware_confirmed=False)
        self.assertEqual(console.action('macro-run','3',None,profile='stock',hardware_confirmed=False).commands, ('M813',))

    def test_read_only_diagnostics_verify_printer_identity(self):
        class Fake:
            def __init__(self): self.calls=[]
            def ascii_command(self,cmd,**kwargs):
                self.calls.append(cmd)
                return ['FIRMWARE_NAME:Marlin MACHINE_TYPE:KINGROON KP3S V1', 'ok'] if cmd=='M115' else ['ok']
        fake=Fake()
        result=console.execute(fake,console.action('status',None,None,profile='stock',hardware_confirmed=False))
        self.assertEqual(fake.calls[0], 'M115')
        self.assertEqual(len(result), 5)

    def test_unsafe_commands_not_sent_before_identity_proof(self):
        class Fake:
            def __init__(self): self.calls=[]
            def ascii_command(self,cmd,**kwargs):
                self.calls.append(cmd)
                return ['MACHINE_TYPE:UNKNOWN','ok']
        fake=Fake()
        with self.assertRaises(console.ConsoleError):
            console.execute(fake,console.action('save',None,None,profile='stock',hardware_confirmed=False),execute_changes=True)
        self.assertEqual(fake.calls, ['M115'])

    def test_mutation_requires_execute_flag_without_io(self):
        class Fake:
            def ascii_command(self,*args,**kwargs): raise AssertionError('Unexpected I/O')
        o=console.action('fan','50',None,profile='stock',hardware_confirmed=False)
        result=console.execute(Fake(),o,execute_changes=False)
        self.assertIn('DRY RUN',result[0][1][0])

    def test_high_risk_actions_require_yes(self):
        class Fake:
            def ascii_command(self,*args,**kwargs): raise AssertionError('Unexpected I/O')
        o=console.action('abort',None,None,profile='stock',hardware_confirmed=False)
        with self.assertRaises(console.ConsoleError):
            console.execute(Fake(),o,execute_changes=True,yes=False)

    def test_emergency_stop_is_sent_without_waiting_for_identity(self):
        class FakePort:
            def __init__(self): self.frames=[]
            def write(self,data): self.frames.append(data)
            def flush(self): pass
        class Fake:
            def __init__(self): self.ser=FakePort()
            def ascii_command(self,*args,**kwargs): raise AssertionError('Emergency cannot wait')
        fake=Fake()
        op=console.action('emergency',None,None,profile='stock',hardware_confirmed=False)
        console.execute(fake,op,execute_changes=True,yes=True)
        self.assertEqual(fake.ser.frames,[b'M112\n'])

    def test_console_main_dry_run_needs_no_serial(self):
        with mock.patch.object(spool,'require_pyserial',side_effect=AssertionError('Should not need pyserial')):
            with mock.patch('sys.stdout', new_callable=io.StringIO) as out:
                self.assertEqual(console.main(['nozzle','210']),0)
                self.assertIn('M104 S210',out.getvalue())

    def test_console_actions_list_needs_no_serial(self):
        with mock.patch('sys.stdout',new_callable=io.StringIO) as out:
            self.assertEqual(console.main(['--list-actions']),0)
            self.assertIn('macro-set',out.getvalue())

    def test_console_requires_operation(self):
        with self.assertRaises(console.ConsoleError):
            console.main([])

    def test_builder_generates_profile_manifest_fields_in_source(self):
        text=Path(builder.__file__).read_text()
        for token in ('KP3S_BUILD_PROFILE.json', 'BUILD_MANIFEST.json',
                      'maximum_target_c', 'binary_size_bytes', 'hardware_validation'):
            self.assertIn(token,text)

    def test_shell_launchers_static_validity(self):
        for name in ('BUILD_FIRMWARE.sh', 'SERIAL_SPOOL.sh', 'KP3S_CONSOLE.sh'):
            cmd=['bash','-n',str(Path(builder.__file__).parent/name)]
            self.assertEqual(subprocess.run(cmd, capture_output=True).returncode,0)


class PlatformIOTargetRegressionTests(unittest.TestCase):
    """Reproduce the reported 2.1.3-b3 Robin Nano INI layout without network."""

    PINNED_INI = """
[STM32F103VE_robin]
extends                     = stm32_variant
board                       = genericSTM32F103VE
board_build.variant         = MARLIN_F103Vx
board_build.offset          = 0x7000
board_upload.offset_address = 0x08007000
[mks_robin_nano_v1v2_common]
extends                     = STM32F103VE_robin
board_build.encrypt_mks     = Robin_nano35.bin
[env:mks_robin_nano_v1v2]
extends                     = mks_robin_nano_v1v2_common
build_flags                 = ${mks_robin_nano_v1v2_common.build_flags} -DENABLE_HWSERIAL3
[env:mks_robin_e3]
board = genericSTM32F103RC
"""

    def test_pinned_inherited_target_matches_real_marlin_layout(self):
        builder.verify_robin_nano_build_target(self.PINNED_INI)

    def test_normalized_spacing_and_comments_are_accepted(self):
        ini = self.PINNED_INI.replace('board                       = ', 'board=')
        ini = ini.replace('board_build.offset          = ', 'board_build.offset = ')
        ini = ini.replace('board_build.encrypt_mks     = ', 'board_build.encrypt_mks= ')
        builder.verify_robin_nano_build_target(ini)

    def test_wrong_values_in_unrelated_env_do_not_confuse_target(self):
        builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
            '[env:mks_robin_e3]\nboard = genericSTM32F103RC',
            '[env:mks_robin_e3]\nboard = genericSTM32F103VE\nboard_build.offset = 0x7000'
        ))

    def test_target_override_must_be_checked_not_just_parent(self):
        ini = self.PINNED_INI.replace(
            'extends                     = mks_robin_nano_v1v2_common',
            'extends = mks_robin_nano_v1v2_common\nboard = genericSTM32F103ZE'
        )
        with self.assertRaisesRegex(RuntimeError, 'board='):
            builder.verify_robin_nano_build_target(ini)

    def test_wrong_board_in_parent_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'board='):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                'board                       = genericSTM32F103VE',
                'board                       = genericSTM32F103ZE'))

    def test_wrong_bootloader_offset_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'board_build.offset='):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                'board_build.offset          = 0x7000',
                'board_build.offset          = 0x8000'))

    def test_wrong_upload_address_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'board_upload.offset_address='):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                '0x08007000', '0x08008000'))

    def test_wrong_firmware_filename_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'board_build.encrypt_mks='):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                'Robin_nano35.bin', 'Robin_mini.bin'))

    def test_wrong_variant_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'board_build.variant='):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                'MARLIN_F103Vx', 'MARLIN_F103Rx'))

    def test_missing_parent_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing inherited PlatformIO section'):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                'extends                     = STM32F103VE_robin',
                'extends                     = non_existent_parent'))

    def test_circular_inheritance_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Circular PlatformIO inheritance'):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                'extends                     = STM32F103VE_robin',
                'extends                     = env:mks_robin_nano_v1v2'))

    def test_missing_target_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Missing PlatformIO environment'):
            builder.verify_robin_nano_build_target(self.PINNED_INI.replace(
                '[env:mks_robin_nano_v1v2]', '[env:another_board]'))

    def test_windows_launcher_profile_reader_avoids_nested_cmd_quoting(self):
        launcher = (Path(builder.__file__).parent / 'BUILD_FIRMWARE.bat').read_text()
        self.assertIn('> "%PROFILE_FILE%"', launcher)
        self.assertIn('set /p "DEFAULT_HOTEND=" < "%PROFILE_FILE%"', launcher)
        self.assertNotIn("for /f \"delims=\" %%H", launcher)
        self.assertIn('--show-default-profile', launcher)


class StandardControlHardwareTests(unittest.TestCase):
    """The custom Nokia+Samsung assembly, not the factory LCD, is the default."""

    def test_custom_hardware_is_only_supported_control_profile(self):
        import kp3s_project_config as config
        config.validate_project_settings()
        self.assertEqual(config.CONTROL_HARDWARE_PROFILE, 'nokia5110-samsung-ue5000')
        self.assertEqual(config.DEFAULT_HOTEND_PROFILE, 'stock')
        self.assertEqual(builder.CONTROL_HARDWARE_PROFILE, config.CONTROL_HARDWARE_PROFILE)
        self.assertEqual(builder.DEFAULT_HOTEND_PROFILE, config.DEFAULT_HOTEND_PROFILE)
        self.assertEqual(config.CONTROL_PIN_MAP['KP3S_UE5000_KEY2_PIN'], 'PE13')
        self.assertEqual(config.CONTROL_PIN_MAP['LCD_BACKLIGHT_PIN'], 'PD13')

    def test_builder_defaults_to_custom_panel_with_safe_thermal_profile(self):
        with mock.patch.object(sys, 'argv', ['builder', '--generate-only']):
            selected = builder.parse_args()
        self.assertEqual(selected.hotend_profile, 'stock')
        self.assertTrue(selected.enable_arcs)

    def test_switching_internal_default_to_high_temp_still_requires_ack(self):
        with mock.patch.object(builder, 'DEFAULT_HOTEND_PROFILE', 'high-temp'), \
             mock.patch.object(sys, 'argv', ['builder', '--generate-only']):
            with self.assertRaises(SystemExit), mock.patch('sys.stderr', new_callable=io.StringIO):
                builder.parse_args()

    def test_duplicate_control_pin_is_rejected(self):
        import kp3s_project_config as config
        changed = dict(config.CONTROL_PIN_MAP)
        changed['KP3S_UE5000_IR_PIN'] = 'PD14'
        with mock.patch.object(config, 'CONTROL_PIN_MAP', changed):
            with self.assertRaisesRegex(ValueError, 'Overlapping'):
                config.validate_project_settings()

    def test_reserved_motion_and_thermal_pin_collision_rejected(self):
        import kp3s_project_config as config
        changed = dict(config.CONTROL_PIN_MAP)
        changed['KP3S_UE5000_IR_PIN'] = config.RESERVED_MACHINE_PIN_MAP['HEATER_0_PIN']
        with mock.patch.object(config, 'CONTROL_PIN_MAP', changed):
            with self.assertRaisesRegex(ValueError, 'collides'):
                config.validate_project_settings()

    def test_generated_profile_verification_good_and_bad(self):
        from kp3s_project_config import CONTROL_PIN_MAP, RESERVED_MACHINE_PIN_MAP
        with TemporaryDirectory() as td:
            root = Path(td)
            cfg = root / 'Marlin' / 'Configuration.h'
            pins = root / 'Marlin' / 'src' / 'pins' / 'stm32f1' / 'pins_MKS_ROBIN_NANO_common.h'
            pins.parent.mkdir(parents=True)
            cfg.write_text('#define NOKIA5110_LCD\n#define KP3S_UE5000\n#define KP3S_SMART_UI\n'
                           '//#define MKS_ROBIN_TFT24\n//#define TFT_COLOR_UI\n//#define TOUCH_SCREEN\n')
            pins.write_text('\n'.join(f'#define {name} {pin}' for name, pin in {**CONTROL_PIN_MAP, **RESERVED_MACHINE_PIN_MAP}.items()))
            with mock.patch.object(builder, 'OUT', root):
                builder.verify_generated_control_profile()
                pins.write_text(pins.read_text().replace('#define KP3S_UE5000_KEY2_PIN PE13',
                                                           '#define KP3S_UE5000_KEY2_PIN PE12'))
                with self.assertRaisesRegex(RuntimeError, 'Control/motherboard wiring changed'):
                    builder.verify_generated_control_profile()
                pins.write_text('\n'.join(f'#define {name} {pin}' for name, pin in {**CONTROL_PIN_MAP, **RESERVED_MACHINE_PIN_MAP}.items()))
                cfg.write_text(cfg.read_text() + '\n#define TOUCH_SCREEN\n')
                with self.assertRaisesRegex(RuntimeError, 'Factory touchscreen must be disabled'):
                    builder.verify_generated_control_profile()

    def test_build_profile_manifest_carries_control_pinmap(self):
        source = Path(builder.__file__).read_text()
        self.assertIn('"control_hardware_profile": CONTROL_HARDWARE_PROFILE', source)
        self.assertIn('"control_pins": CONTROL_PIN_MAP', source)
        self.assertIn('verify_generated_control_profile()', source)


if __name__ == '__main__':
    unittest.main(verbosity=2)
