#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
echo "KINGROON KP3S MARLIN FIRMWARE"
echo "Hardware must match the Nokia/Samsung wiring and MKS Robin Nano board."
echo "Thermistor selection is not detected automatically."
echo
default_profile="$(python3 -c 'from kp3s_project_config import DEFAULT_HOTEND_PROFILE; print(DEFAULT_HOTEND_PROFILE)')"
profile="${1:-}"
if [[ -z "$profile" ]]; then
  read -r -p "Choose hotend profile [stock/high-temp] (default ${default_profile}): " profile
  profile="${profile:-$default_profile}"
fi
if [[ "$profile" != "stock" && "$profile" != "high-temp" ]]; then
  echo "Invalid profile: choose stock or high-temp." >&2
  exit 2
fi
args=(--build --auto-toolchain --hotend-profile "$profile")
if [[ "$profile" == "high-temp" ]]; then
  echo "WARNING: 340 C target / 350 C cutoff; requires an independently confirmed table-61 sensor"
  echo "and all-metal hotend, heater cartridge, wiring and connectors rated >=350 C."
  echo "Never use this with a stock or PTFE-lined hotend."
  read -r -p "Type 340 to acknowledge the verified upgrades: " confirm
  if [[ "$confirm" != "340" ]]; then
    echo "Cancelled: high-temperature hardware was not confirmed." >&2
    exit 2
  fi
  args+=(--confirm-high-temp-hardware)
else
  echo "Stock-compatible profile: table-1 thermistor, 235 C target, 250 C cutoff."
  echo "Verify the actual thermistor type and any PTFE-lined hotend limit before heating."
fi
python3 build_firmware.py "${args[@]}"
