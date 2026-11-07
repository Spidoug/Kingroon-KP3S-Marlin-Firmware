# V1 Serial Spool Printing

V1 transfers the **complete G-code file** over the printer serial link before the print starts. The file is written to the printer microSD, then Marlin selects it with `M23` and starts local SD execution with `M24`.

This is deliberately different from normal host printing: the host does **not** feed motion G-code line-by-line during the print. After upload, the printer can continue the job from its SD card even if the monitoring application is closed. Power loss or removing the SD card is a separate matter.

## Firmware features

The generator enables and validates:

- `SDSUPPORT`
- `BINARY_FILE_TRANSFER` (`M28 B1`)
- `CAPABILITIES_REPORT` and `EXTENDED_CAPABILITIES_REPORT`
- `AUTO_REPORT_TEMPERATURES` (`M155`)
- `AUTO_REPORT_POSITION` (`M154`)
- `AUTO_REPORT_SD_STATUS` (`M27`)
- `ADVANCED_OK` so host acknowledgements can also expose queue/planner capacity

`M115` is used by the V1 reference client to reject unexpected firmware before upload.

## Use on Windows

Build and flash V1 first. Insert a writable microSD card in the printer, connect USB/serial, then run:

```text
firmware\SERIAL_SPOOL.bat "C:\prints\part.gcode" --port COM5
```

If only one serial port is present, `--port` may be omitted.

List ports:

```text
firmware\SERIAL_SPOOL.bat --list-ports
```

Start the job but do not keep the host monitor open:

```text
firmware\SERIAL_SPOOL.bat "C:\prints\part.gcode" --port COM5 --no-monitor
```

For a safer first connection check, transfer the file without starting the print:

```text
firmware\SERIAL_SPOOL.bat "C:\prints\part.gcode" --port COM5 --upload-only
```

For dependable `M23` selection, the serial client now uploads using a deterministic DOS 8.3 filename (for example, `BENCB8A1.GCO`). Very long names, punctuation and spaces are normalized, with a short hash suffix to reduce collisions. This does not disable the display's separate long-filename support for files copied directly to the SD card. The command-line output shows the exact uploaded filename. An existing file with the same 8.3 name may be replaced; check the SD contents first.

On Linux / Ubuntu use `python3 -m pip install --user -r firmware/requirements.txt` (or a Python virtual environment), and then:

```bash
./firmware/SERIAL_SPOOL.sh ./part.gcode --port /dev/ttyUSB0
```

Ensure the selected serial device is your printer and your account has serial-port access.

## What happens on the wire

1. `M115` verifies the V1 capabilities.
2. `M27` must report idle and `M27 C` must report `(no file)`; a selected or paused job blocks upload.
3. `M28 B1` switches Marlin to its binary stream.
4. The client synchronizes the stream, opens a file on SD and sends the complete G-code in checksummed blocks.
5. Marlin acknowledges blocks and can request retransmission if the stream is corrupted.
6. The client closes the file and exits binary mode; a fresh `M115` reply must confirm ASCII communication.
7. `M23 <8.3 file>` selects the uploaded file; the client requires Marlin's selection confirmation.
8. `M24` starts local SD printing; `M27` must then report SD print progress (or Marlin must explicitly report that a very short job already completed).
9. `M155 S2`, `M154 S2`, and `M27 S2` enable monitoring every two seconds.

The serial link remains available for monitoring and explicit controls. This is intentional for safety: `pause`, `resume`, `abort`, and status requests are still accepted, but ordinary motion G-code is not streamed from the host.

## Monitor commands

While the client is open, type:

- `pause` - `M25`
- `resume` - `M24`
- `abort` - `M524`
- `status` - immediate `M27`, `M105`, and `M114`
- `quit` - stop host monitoring only; local SD printing continues

## Important

The binary protocol rejects file-open packets that exceed the printer-advertised payload limit, and incompatible protocol versions. The upload requires a writable SD card in the printer. Do not remove the card during upload or printing. First tests should be performed without leaving the machine unattended.


## Generic serial job classification

V1 also has a small host-agnostic print-state classifier used by the Nokia status/standby logic when commands are streamed from a generic serial sender. It normalizes lowercase commands, strips semicolon comments and checksum tails, recognizes pause/resume/end commands, and does not let harmless status polling create a fake print job. An inferred stream expires only after five minutes without meaningful job traffic. This helper changes UI/state classification only; Marlin remains responsible for parsing and executing every command.

Logical standby is lossless. A queued command wakes V1 before queue execution instead of being discarded.
