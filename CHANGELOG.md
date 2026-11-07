# Changelog

## V1 — Windows build compatibility fix (2026-11-06)

- Validate the inherited PlatformIO Robin Nano environment semantically, regardless of INI whitespace.
- Keep strict checks for the board MCU, variant, bootloader offsets and encrypted firmware file name.
- Fix Windows Python path quoting when loading the internal default thermal profile.
- Add an offline Windows launcher smoke check and regression cases for the pinned Marlin INI layout.
- The Nokia/Samsung controller settings and the guarded thermal profiles are unchanged.

## V1 — source package prepared for public repository (2026-11-06)

- Preserved the custom Nokia 5110 + Samsung UE5000 hardware as the default control configuration.
- Retained guarded `stock` and upgraded `high-temp` thermal profiles, the generator, serial upload client, maintenance console and firmware feature patches.
- Consolidated historical audit snapshots into a current validation record while retaining technical and hardware test documentation.
- Added repository hygiene, contribution and security guidance, GitHub Actions offline checks and an optional manual full-build workflow.
- **Validation scope:** 106 offline Python tests and generator structural audit passed; full C++ compilation and real-board testing remain pending.

No public binary release is provided or implied by this changelog.
