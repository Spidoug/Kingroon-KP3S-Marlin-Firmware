# Optional BLTouch

BLTouch is optional and does not replace the mechanical Z-min switch.

- PA8: servo/control
- PC4 / Z-MAX: probe signal
- PA11: mechanical Z-min microswitch remains unchanged

BLTouch starts disabled on V1 defaults and can be enabled from `Configuration > BLTouch On`. The enable state is persisted in EEPROM and re-applied after settings load. `G29` and probe deployment are blocked while it is disabled.

The runtime enable switch sits directly beside Marlin's native BLTouch tools instead of inside a second probe submenu. While the printer is busy, the toggle and native BLTouch actions are unavailable. Disabling the probe while idle also disables active bed leveling and stows the probe.

The native Probe / Level menu follows the same state. With BLTouch disabled it shows `BLTouch OFF`, hides automatic `Level Bed` and the Probe Offset Wizard, and keeps manual bed tramming available. The duplicate `Save Settings` action was removed from Probe / Level; EEPROM save/load/reset actions live only in `Configuration`.
