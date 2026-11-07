"""Single-point configuration for the custom KP3S V1 hardware build.

This project's *standard control hardware* is the Nokia 5110 (PCD8544)
84x48 screen plus Samsung UE5000 / BN41-01840B navigation board.
It is NOT the factory KP3S touchscreen configuration.

CHANGE ONLY DEFAULT_HOTEND_PROFILE to select the usual thermal build:
  stock      -- sensor table 1, 235 C target, 250 C MAXTEMP
  high-temp  -- sensor table 61, 340 C target, 350 C MAXTEMP

Changing to high-temp never bypasses the mandatory hardware confirmation.
The hotend, sensor, heater, wires and connectors must all be independently
verified for high-temperature operation before using that build.
"""

CONTROL_HARDWARE_PROFILE = "nokia5110-samsung-ue5000"
DEFAULT_HOTEND_PROFILE = "stock"

# These pin assignments describe the physical wiring of the V1 custom panel.
# Do not change these to match a factory touchscreen. Changing wiring needs
# coordinated modifications in the generator and an on-printer pin audit.
CONTROL_PIN_MAP = {
    "DOGLCD_SCK": "PD5",           # Nokia CLK / FFC21
    "DOGLCD_MOSI": "PD14",         # Nokia DIN / FFC3
    "DOGLCD_CS": "PD7",           # Nokia CS / FFC19
    "DOGLCD_A0": "PD11",          # Nokia DC / FFC20
    "LCD_RESET_PIN": "PC6",       # Nokia RST / FFC23
    "LCD_BACKLIGHT_PIN": "PD13",  # Nokia BL / FFC24
    "KP3S_UE5000_KEY1_PIN": "PE10",  # Samsung KEY1 / FFC10
    "KP3S_UE5000_KEY2_PIN": "PE13",  # Samsung KEY2 / FFC13 (1k/100nF RC)
    "KP3S_UE5000_IR_PIN": "PE7",    # Samsung IR / FFC7
    "KP3S_UE5000_LED_PIN": "PD10",  # Samsung LED / FFC18
    "KP3S_MPU6050_SDA_PIN": "PD9",
    "KP3S_MPU6050_SCL_PIN": "PD8",
    "Z_MIN_PROBE_PIN": "PC4",
    "BTN_ENC": "PE15",          # Dummy input only, not physically wired
}

# Fixed motherboard functions that must never be reassigned to an LCD, key,
# LED, IMU or probe input. Probe PC4 is intentionally not included here:
# Z_MAX is disabled and that connector becomes the probe input.
RESERVED_MACHINE_PIN_MAP = {
    "SERVO0_PIN": "PA8",
    "X_STOP_PIN": "PA15", "Y_STOP_PIN": "PA12", "Z_MIN_PIN": "PA11",
    "X_ENABLE_PIN": "PE4", "X_STEP_PIN": "PE3", "X_DIR_PIN": "PE2",
    "Y_ENABLE_PIN": "PE1", "Y_STEP_PIN": "PE0", "Y_DIR_PIN": "PB9",
    "Z_ENABLE_PIN": "PB8", "Z_STEP_PIN": "PB5", "Z_DIR_PIN": "PB4",
    "E0_ENABLE_PIN": "PB3", "E0_STEP_PIN": "PD6", "E0_DIR_PIN": "PD3",
    "TEMP_0_PIN": "PC1", "TEMP_BED_PIN": "PC0",
    "HEATER_0_PIN": "PC3", "HEATER_BED_PIN": "PA0",
    "FAN0_PIN": "PB1", "FIL_RUNOUT_PIN": "PA4",
    "SD_DETECT_PIN": "PD12", "ONBOARD_SD_CS_PIN": "PC11",
    "SPI_FLASH_CS_PIN": "PB12",
}


def validate_project_settings():
    if CONTROL_HARDWARE_PROFILE != "nokia5110-samsung-ue5000":
        raise ValueError("Unsupported control profile: Nokia/Samsung V1 is required")
    if DEFAULT_HOTEND_PROFILE not in ("stock", "high-temp"):
        raise ValueError("Unsupported default hotend profile")
    if len(set(CONTROL_PIN_MAP.values())) != len(CONTROL_PIN_MAP):
        raise ValueError("Overlapping control/IMU/probe pin assignments")
    occupied = set(RESERVED_MACHINE_PIN_MAP.values())
    conflict = occupied.intersection(CONTROL_PIN_MAP.values())
    if conflict:
        raise ValueError(f"Control wiring collides with motherboard motion/thermal/SD pins: {sorted(conflict)}")
    for name, pin in CONTROL_PIN_MAP.items():
        if not name or not pin.startswith("P") or len(pin) not in (3, 4):
            raise ValueError(f"Invalid pin assignment: {name}={pin}")
