#!/usr/bin/env python3
"""KP3S Marlin Firmware V1 - upload a complete G-code file over serial and print from SD.

Protocol implementation follows Marlin 2.1.3-b3 Binary File Transfer:
M28 B1 -> binary stream -> SD file -> binary close -> M23/M24 -> telemetry.
The motion G-code is not streamed from the host while printing.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import queue
import re
import struct
import sys
import threading
import time

try:
    import serial
    from serial.tools import list_ports
except ImportError as exc:
    raise SystemExit("pyserial is required. Run SERIAL_SPOOL.bat or: python -m pip install pyserial") from exc

PACKET_TOKEN = 0xB5AD
PROTO_CONTROL = 0
PROTO_FILE = 1
CTRL_SYNC = 1
CTRL_CLOSE = 2
PFT_QUERY = 0
PFT_OPEN = 1
PFT_CLOSE = 2
PFT_WRITE = 3
PFT_ABORT = 4


class TransferError(RuntimeError):
    pass


def fletcher16(data: bytes) -> int:
    low = high = 0
    for value in data:
        low = (low + value) % 255
        high = (high + low) % 255
    return (high << 8) | low


def packet_bytes(sync: int, protocol: int, packet_type: int, payload: bytes = b"") -> bytes:
    if len(payload) > 0xFFFF:
        raise ValueError("Payload is too large for Marlin binary protocol")
    meta = ((protocol & 0x0F) << 4) | (packet_type & 0x0F)
    header_data = struct.pack("<BBH", sync & 0xFF, meta, len(payload))
    header = header_data + struct.pack("<H", fletcher16(header_data))
    frame = struct.pack("<H", PACKET_TOKEN) + header
    if payload:
        frame += payload + struct.pack("<H", fletcher16(header + payload))
    return frame


def safe_sd_name(source: Path, requested: str | None) -> str:
    raw = requested or source.name
    path = Path(raw)
    stem = re.sub(r"[^A-Za-z0-9 _.-]", "_", path.stem).strip(" ._") or "KP3S Job"
    stem = re.sub(r"[ ]+", " ", stem)[:48].rstrip(" ._") or "KP3S Job"
    ext = re.sub(r"[^A-Za-z0-9]", "", path.suffix.lstrip("."))[:8] or "gcode"
    # V1 enables LONG_FILENAME_WRITE_SUPPORT. Keep a readable filename for the LCD,
    # while bounding it to a conservative FAT/VFAT-friendly length.
    return f"{stem}.{ext}"


def available_ports() -> list[str]:
    return [p.device for p in list_ports.comports()]


@dataclass
class BinarySession:
    ser: serial.Serial
    timeout: float = 2.0
    sync: int = 0
    max_block: int = 512

    def _readline(self, deadline: float) -> str:
        while time.monotonic() < deadline:
            raw = self.ser.readline()
            if not raw:
                continue
            text = raw.decode("utf-8", errors="replace").strip()
            if text:
                return text
        raise TransferError("Timed out waiting for printer response")

    def ascii_command(self, command: str, *, wait_ok: bool = True, timeout: float | None = None) -> list[str]:
        self.ser.write((command.rstrip() + "\n").encode("ascii"))
        self.ser.flush()
        if not wait_ok:
            return []
        lines: list[str] = []
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            line = self._readline(deadline)
            lines.append(line)
            low = line.lower()
            if low.startswith("error:") or low.startswith("echo:error"):
                raise TransferError(line)
            if low == "ok" or low.startswith("ok "):
                return lines
        raise TransferError(f"No OK for {command!r}")

    def enter_binary(self) -> None:
        lines = self.ascii_command("M28 B1", timeout=4.0)
        if not any("Switching to Binary Protocol" in line for line in lines):
            # Some hosts / serial wrappers may consume the informational echo. The OK is authoritative.
            pass
        self._sync_stream()

    def _sync_stream(self) -> None:
        self.ser.write(packet_bytes(0, PROTO_CONTROL, CTRL_SYNC))
        self.ser.flush()
        deadline = time.monotonic() + 4.0
        while time.monotonic() < deadline:
            line = self._readline(deadline)
            if line.startswith("ss"):
                try:
                    sync_text, max_block_text, _version = line[2:].split(",", 2)
                    self.sync = int(sync_text) & 0xFF
                    self.max_block = max(32, min(int(max_block_text), 4096))
                    return
                except (ValueError, TypeError) as exc:
                    raise TransferError(f"Invalid Marlin sync response: {line}") from exc
            if line.startswith("fe"):
                raise TransferError("Marlin reported a fatal binary-stream error")
        raise TransferError("Could not synchronize Marlin binary stream")

    def send_packet(self, protocol: int, packet_type: int, payload: bytes = b"", *, retries: int = 6) -> list[str]:
        expected = self.sync
        frame = packet_bytes(expected, protocol, packet_type, payload)
        for attempt in range(1, retries + 1):
            self.ser.write(frame)
            self.ser.flush()
            deadline = time.monotonic() + self.timeout
            extra: list[str] = []
            while time.monotonic() < deadline:
                try:
                    line = self._readline(deadline)
                except TransferError:
                    break
                if line.startswith("PFT:ioerror") or line.startswith("PFT:fail"):
                    raise TransferError(line)
                if line.startswith("fe"):
                    raise TransferError(f"Marlin binary fatal error: {line}")
                if line.startswith("rs"):
                    break
                if line.startswith("ok"):
                    try:
                        ack = int(line[2:].strip())
                    except ValueError:
                        extra.append(line)
                        continue
                    if ack == expected:
                        self.sync = (self.sync + 1) & 0xFF
                        return extra
                else:
                    extra.append(line)
            if attempt == retries:
                raise TransferError(f"Packet {expected} was not acknowledged after {retries} attempts")
        raise TransferError("Unreachable packet retry state")

    def wait_pft(self, accepted: tuple[str, ...], timeout: float = 3.0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            line = self._readline(deadline)
            if line.startswith(accepted):
                return line
            if line.startswith(("PFT:fail", "PFT:ioerror", "PFT:busy", "PTF:invalid", "PFT:invalid")):
                raise TransferError(line)
        raise TransferError("Timed out waiting for file-transfer response")

    def query_file_protocol(self) -> str:
        self.send_packet(PROTO_FILE, PFT_QUERY)
        line = self.wait_pft(("PFT:version:",))
        return line

    def open_file(self, sd_name: str) -> None:
        payload = b"\x00\x00" + sd_name.encode("utf-8") + b"\x00"
        self.send_packet(PROTO_FILE, PFT_OPEN, payload)
        self.wait_pft(("PFT:success",), timeout=5.0)

    def write_file(self, source: Path) -> None:
        total = source.stat().st_size
        sent = 0
        started = time.monotonic()
        with source.open("rb") as fh:
            while True:
                block = fh.read(self.max_block)
                if not block:
                    break
                self.send_packet(PROTO_FILE, PFT_WRITE, block)
                sent += len(block)
                elapsed = max(time.monotonic() - started, 0.001)
                pct = (sent * 100.0 / total) if total else 100.0
                rate = sent / elapsed / 1024.0
                print(f"\rUpload: {pct:6.2f}%  {sent}/{total} bytes  {rate:7.1f} KiB/s", end="", flush=True)
        print()

    def close_file(self) -> None:
        self.send_packet(PROTO_FILE, PFT_CLOSE)
        self.wait_pft(("PFT:success",))

    def abort_file(self) -> None:
        try:
            self.send_packet(PROTO_FILE, PFT_ABORT)
            self.wait_pft(("PFT:success",), timeout=1.5)
        except Exception:
            pass

    def leave_binary(self) -> None:
        self.send_packet(PROTO_CONTROL, CTRL_CLOSE)
        time.sleep(0.1)
        self.ser.reset_input_buffer()


def discover_port(explicit: str | None) -> str:
    if explicit:
        return explicit
    ports = available_ports()
    if len(ports) == 1:
        return ports[0]
    if not ports:
        raise TransferError("No serial port detected. Connect the printer or pass --port COMx.")
    raise TransferError("Multiple serial ports detected. Pass --port with one of: " + ", ".join(ports))


def probe_capabilities(session: BinarySession) -> None:
    lines = session.ascii_command("M115", timeout=4.0)
    caps = {m.group(1): m.group(2) for line in lines for m in [re.match(r"Cap:([^:]+):([01])", line)] if m}
    required = {
        "BINARY_FILE_TRANSFER": "1",
        "SDCARD": "1",
        "SD_WRITE": "1",
        "AUTOREPORT_TEMP": "1",
        "AUTOREPORT_POS": "1",
        "AUTOREPORT_SD_STATUS": "1",
    }
    missing = [name for name, value in required.items() if caps.get(name) != value]
    if missing:
        raise TransferError("Firmware is missing required V1 serial capabilities: " + ", ".join(missing))


def ensure_not_sd_printing(session: BinarySession) -> None:
    lines = session.ascii_command("M27", timeout=3.0)
    if any("SD printing byte" in line for line in lines):
        raise TransferError("The printer is already printing from SD. Stop that job before uploading a new one.")


def start_local_print(session: BinarySession, sd_name: str) -> None:
    session.ascii_command(f"M23 {sd_name}", timeout=4.0)
    session.ascii_command("M24", timeout=4.0)
    # 2-second reports are detailed enough without flooding the serial port.
    session.ascii_command("M155 S2")
    session.ascii_command("M154 S2")
    session.ascii_command("M27 S2")


def stop_auto_reports(session: BinarySession) -> None:
    for cmd in ("M155 S0", "M154 S0", "M27 S0"):
        try:
            session.ascii_command(cmd, timeout=1.0)
        except Exception:
            pass


def monitor(session: BinarySession) -> None:
    commands: queue.Queue[str] = queue.Queue()
    stop = threading.Event()

    def input_worker() -> None:
        while not stop.is_set():
            try:
                value = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                commands.put("quit")
                return
            commands.put(value)

    threading.Thread(target=input_worker, daemon=True).start()
    print("Monitoring local SD print. Commands: pause | resume | abort | status | quit")
    print("'quit' stops host monitoring only; the printer keeps printing locally.")
    saw_printing = False
    while True:
        try:
            try:
                cmd = commands.get_nowait()
            except queue.Empty:
                cmd = ""
            if cmd in {"pause", "p"}:
                session.ascii_command("M25")
            elif cmd in {"resume", "r"}:
                session.ascii_command("M24")
            elif cmd in {"abort", "x", "cancel"}:
                session.ascii_command("M524", timeout=4.0)
            elif cmd in {"status", "s"}:
                session.ascii_command("M27")
                session.ascii_command("M105")
                session.ascii_command("M114")
            elif cmd in {"quit", "q", "exit"}:
                stop_auto_reports(session)
                print("Host monitor closed. Local SD print was not stopped.")
                return

            raw = session.ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            print(line)
            if "SD printing byte" in line:
                saw_printing = True
            if saw_printing and ("Done printing file" in line or "Not SD printing" in line):
                stop_auto_reports(session)
                print("Print monitoring finished.")
                return
        except KeyboardInterrupt:
            stop_auto_reports(session)
            print("\nHost monitor closed. Local SD print was not stopped.")
            return
        finally:
            stop.set() if False else None


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Upload full G-code to KP3S over serial, print locally from SD, then monitor.")
    ap.add_argument("gcode", nargs="?", type=Path, help="G-code file to upload")
    ap.add_argument("--port", help="Serial port, e.g. COM5")
    ap.add_argument("--baud", type=int, default=250000, help="Serial baud rate (default: 250000)")
    ap.add_argument("--sd-name", help="Target SD filename. V1 preserves a readable long filename (up to 48 stem characters).")
    ap.add_argument("--no-monitor", action="store_true", help="Start the SD print and exit without live monitoring")
    ap.add_argument("--list-ports", action="store_true", help="List serial ports and exit")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    if args.list_ports:
        ports = available_ports()
        print("\n".join(ports) if ports else "No serial ports detected.")
        return 0
    if args.gcode is None:
        raise TransferError("A .gcode file is required. Use --list-ports to inspect serial ports.")
    source = args.gcode.expanduser().resolve()
    if not source.is_file():
        raise TransferError(f"G-code file not found: {source}")
    if source.suffix.lower() not in {".gcode", ".gco", ".gc"}:
        raise TransferError("Input file must be G-code (.gcode, .gco, or .gc)")

    port = discover_port(args.port)
    sd_name = safe_sd_name(source, args.sd_name)
    print(f"Printer: {port} @ {args.baud}")
    print(f"Source : {source}")
    print(f"SD file: {sd_name}")

    with serial.Serial(port, baudrate=args.baud, timeout=0.20, write_timeout=5.0) as ser:
        time.sleep(1.8)
        ser.reset_input_buffer()
        session = BinarySession(ser)
        probe_capabilities(session)
        ensure_not_sd_printing(session)

        print("Entering Marlin binary file-transfer mode...")
        session.enter_binary()
        proto = session.query_file_protocol()
        print(proto)
        file_open = False
        try:
            session.open_file(sd_name)
            file_open = True
            session.write_file(source)
            session.close_file()
            file_open = False
        except Exception:
            if file_open:
                session.abort_file()
            raise
        finally:
            try:
                session.leave_binary()
            except Exception:
                pass

        print("Upload complete. Starting local SD print...")
        start_local_print(session, sd_name)
        print("The host is no longer streaming motion G-code. The printer is executing the SD file locally.")
        if not args.no_monitor:
            monitor(session)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except TransferError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
