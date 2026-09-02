# Optional BLTouch

BLTouch is optional and does not replace the mechanical Z-min switch.

- PA8: servo/control
- PC4 / Z-MAX: probe signal
- PA11: mechanical Z-min microswitch remains unchanged

BLTouch starts disabled on V1 defaults and can be enabled from `Configuration > KP3S Setup > BLTouch / Leveling`. The enable state is persisted in EEPROM and re-applied after settings load. `G29` and probe deployment are blocked while it is disabled.

While the printer is busy, the BLTouch enable control and native BLTouch actions are locked. This prevents a mid-print toggle from disabling bed leveling or changing probe state underneath active motion. Disabling the probe while idle also disables active bed leveling and stows the probe.
