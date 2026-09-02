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
firmware\current\SERIAL_SPOOL.bat "C:\prints\part.gcode" --port COM5
```

If only one serial port is present, `--port` may be omitted.

List ports:

```text
firmware\current\SERIAL_SPOOL.bat --list-ports
```

Start the job but do not keep the host monitor open:

```text
firmware\current\SERIAL_SPOOL.bat "C:\prints\part.gcode" --port COM5 --no-monitor
```

V1 enables Marlin long-filename write support. The client keeps a readable sanitized filename (up to 48 stem characters), and the Nokia UI scrolls it safely when it does not fit.

## What happens on the wire

1. `M115` verifies the V1 capabilities.
2. `M27` confirms there is no existing SD print.
3. `M28 B1` switches Marlin to its binary stream.
4. The client synchronizes the stream, opens a file on SD and sends the complete G-code in checksummed blocks.
5. Marlin acknowledges blocks and can request retransmission if the stream is corrupted.
6. The client closes the file and exits binary mode.
7. `M23 <file>` selects the uploaded file.
8. `M24` starts local SD printing.
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

The upload requires a writable SD card in the printer. Do not remove the card during upload or printing. First tests should be performed without leaving the machine unattended.


## Generic serial job classification

V1 also has a small host-agnostic print-state classifier used by the Nokia status/standby logic when commands are streamed from a generic serial sender. It normalizes lowercase commands, strips semicolon comments and checksum tails, recognizes pause/resume/end commands, and does not let harmless status polling create a fake print job. An inferred stream expires only after five minutes without meaningful job traffic. This helper changes UI/state classification only; Marlin remains responsible for parsing and executing every command.

Logical standby is lossless. A queued command wakes V1 before queue execution instead of being discarded.
