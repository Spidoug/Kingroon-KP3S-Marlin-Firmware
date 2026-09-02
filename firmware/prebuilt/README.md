# Prebuilt firmware

This directory is reserved for **validated, already-compiled V1 release binaries**.

Expected bootloader-ready file:

```text
Robin_nano.bin
```

A release binary placed here should meet all of the following conditions:

- built from the repository's current V1 source state;
- compiled for the `mks_robin_nano_v1v2` PlatformIO environment used by the KP3S STM32F103VET6 board;
- successfully flashed and smoke-tested on the target printer;
- accompanied by a published SHA-256 checksum in the release notes when distributed.

Do not place temporary PlatformIO outputs, `.elf`, `.map`, cache files or generated source trees here. Those remain under the ignored local build directories.

For flashing, copy `Robin_nano.bin` to the root of a FAT32 microSD card.
