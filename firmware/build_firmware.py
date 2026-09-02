#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Kingroon KP3S Marlin Firmware V1 builder for Marlin 2.1.3-b3.

The script:
  1. downloads Marlin and the official Kingroon KP3S configuration;
  2. validates downloaded inputs;
  3. applies the KP3S V1 hardware and UI patches using structural anchors;
  4. validates the generated project;
  5. prepares the build toolchain when needed and builds the firmware;
  6. creates firmware_output/FLASH_KP3S/Robin_nano.bin ready for the SD card.

Usage:
    python build_firmware.py --build

Optional:
    python build_firmware.py --generate-only
    python build_firmware.py --clean
"""

from __future__ import annotations

from pathlib import Path
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.error
import urllib.request
import zipfile

TAG = "2.1.3-b3"
ENV = "mks_robin_nano_v1v2"
BUILD_BINARY = "Robin_nano35.bin"
FLASH_BINARY = "Robin_nano.bin"

BASE = Path(__file__).resolve().parent
CACHE = BASE / "cache"
PROJECT_VERSION = "1.0.0"
OUT = BASE / "generated" / "Marlin-KP3S-Firmware-V1"
FW_OUT = BASE / "firmware_output"
FLASH_DIR = FW_OUT / "FLASH_KP3S"
ORIGINAL_DIR = FW_OUT / "build_original"
LOG = BASE / "BUILD.log"

MARLIN_ZIP = CACHE / f"Marlin-{TAG}.zip"
CONFIG_H = CACHE / "Configuration.h"
CONFIG_ADV_H = CACHE / "Configuration_adv.h"

MARLIN_URL = f"https://codeload.github.com/MarlinFirmware/Marlin/zip/refs/tags/{TAG}"
CONFIG_H_URL = (
    f"https://raw.githubusercontent.com/MarlinFirmware/Configurations/{TAG}/"
    "config/examples/Kingroon/KP3S/Configuration.h"
)
CONFIG_ADV_H_URL = (
    f"https://raw.githubusercontent.com/MarlinFirmware/Configurations/{TAG}/"
    "config/examples/Kingroon/KP3S/Configuration_adv.h"
)


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
            stream.flush()
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()


def banner(text: str):
    print()
    print("=" * 72)
    print(text)
    print("=" * 72)


def cmdline(cmd) -> str:
    return subprocess.list2cmdline([str(x) for x in cmd])


def run(cmd, cwd=None, check=True):
    print("\n>", cmdline(cmd))
    proc = subprocess.run(
        [str(x) for x in cmd],
        cwd=str(cwd) if cwd else None,
        text=True,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed with exit code {proc.returncode}: {cmdline(cmd)}"
        )
    return proc.returncode


def download_with_curl(url: str, dest: Path) -> bool:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        return False

    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)
    cmd = [
        curl,
        "-L",
        "--fail",
        "--retry", "4",
        "--retry-all-errors",
        "--retry-delay", "2",
        "--connect-timeout", "30",
        "--max-time", "300",
        "-A", "Mozilla/5.0 KP3S-Setup",
        "-o", str(part),
        url,
    ]

    try:
        if run(cmd, check=False) == 0 and part.exists() and part.stat().st_size > 0:
            part.replace(dest)
            return True
    finally:
        part.unlink(missing_ok=True)
    return False


def download_with_python(url: str, dest: Path):
    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)
    last_error = None

    for attempt in range(1, 4):
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 KP3S-Setup"},
        )
        try:
            print(f"[...] Python downloader: attempt {attempt}/3")
            with urllib.request.urlopen(req, timeout=90) as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            if part.stat().st_size <= 0:
                raise RuntimeError("Empty download")
            part.replace(dest)
            return
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, RuntimeError) as exc:
            last_error = exc
            part.unlink(missing_ok=True)
            if attempt < 3:
                time.sleep(2 * attempt)

    raise RuntimeError(f"Failed to download {url}: {last_error}")


def validate_marlin_zip(path: Path):
    """Validate both archive integrity and the exact Marlin baseline expected by V1."""
    try:
        with zipfile.ZipFile(path) as zf:
            bad = zf.testzip()
            if bad:
                raise RuntimeError(f"Corrupt ZIP entry: {bad}")
            names = zf.namelist()
            required_suffixes = (
                "/platformio.ini",
                "/Marlin/Configuration.h",
                "/Marlin/src/lcd/marlinui.cpp",
                "/Marlin/src/inc/Conditionals-2-LCD.h",
                "/Marlin/src/inc/Version.h",
                "/Marlin/src/module/settings.cpp",
            )
            resolved = {}
            for suffix in required_suffixes:
                matches = [name for name in names if name.endswith(suffix)]
                if len(matches) != 1:
                    raise RuntimeError(f"ZIP expected one {suffix}, found {len(matches)}")
                resolved[suffix] = matches[0]

            version = zf.read(resolved["/Marlin/src/inc/Version.h"]).decode("utf-8")
            if '#define SHORT_BUILD_VERSION "2.1.3-beta3"' not in version:
                raise RuntimeError("ZIP is not the Marlin 2.1.3 beta 3 baseline")
            if '#define MARLIN_HEX_VERSION 02010300' not in version:
                raise RuntimeError("ZIP reports an unexpected Marlin configuration version")

            settings = zf.read(resolved["/Marlin/src/module/settings.cpp"]).decode("utf-8")
            if not re.search(r'^#define\s+EEPROM_VERSION\s+"[^"]+"$', settings, flags=re.M):
                raise RuntimeError("Unexpected Marlin settings.cpp: EEPROM version marker missing")
            for marker in (
                '} SettingsData;',
                '// Report final CRC and Data Size',
                '// Validate Final Size and CRC',
            ):
                if marker not in settings:
                    raise RuntimeError(f"Unexpected Marlin settings.cpp: missing {marker!r}")
    except zipfile.BadZipFile as exc:
        raise RuntimeError("Invalid Marlin ZIP") from exc


def validate_config_h(path: Path):
    text = path.read_text(encoding="utf-8", errors="strict")
    required = (
        "#define CONFIGURATION_H_VERSION 02010300",
        "BOARD_MKS_ROBIN_NANO",
        "Kingroon/KP3S",
    )
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"Unexpected Configuration.h: missing {marker!r}")


def validate_config_adv(path: Path):
    text = path.read_text(encoding="utf-8", errors="strict")
    required = (
        "#define CONFIGURATION_ADV_H_VERSION 02010300",
        "//#define JOYSTICK",
        "#define JOY_X_PIN",
        "#define JOY_Y_PIN",
    )
    for marker in required:
        if marker not in text:
            raise RuntimeError(f"Unexpected Configuration_adv.h: missing {marker!r}")


def ensure_download(url: str, dest: Path, min_bytes: int, label: str, validator):
    CACHE.mkdir(exist_ok=True)

    if dest.exists() and dest.stat().st_size >= min_bytes:
        try:
            validator(dest)
            print(f"[OK] {label} already cached ({dest.stat().st_size} bytes)")
            return
        except Exception as exc:
            print(f"[WARNING] Invalid cache for {label}: {exc}")
            dest.unlink(missing_ok=True)

    dest.unlink(missing_ok=True)
    print(f"[...] Downloading {label}")
    print(f"      {url}")

    if not download_with_curl(url, dest):
        print("[...] curl did not complete; trying Python downloader...")
        download_with_python(url, dest)

    if not dest.exists() or dest.stat().st_size < min_bytes:
        size = dest.stat().st_size if dest.exists() else 0
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Invalid download for {label}. Size: {size} bytes.")

    try:
        validator(dest)
    except Exception:
        dest.unlink(missing_ok=True)
        raise

    print(f"[OK] {label}: {dest.stat().st_size} bytes")


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str):
    path.write_text(text, encoding="utf-8")


def replace_once(path: Path, old: str, new: str, desc: str):
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"{desc}: expected exactly one match, found {count}.\nFile: {path}"
        )
    write(path, text.replace(old, new, 1))
    print("[OK]", desc)


def regex_once(path: Path, pattern: str, repl: str, desc: str):
    text = read(path)
    rx = re.compile(pattern, flags=re.M)
    matches = list(rx.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"{desc}: expected exactly one match, found {len(matches)}.\nFile: {path}"
        )
    write(path, rx.sub(repl, text, count=1))
    print("[OK]", desc)


def insert_before_regex_once(path: Path, pattern: str, block: str, desc: str):
    """Insert *block* immediately before one structural regex anchor."""
    text = read(path)
    rx = re.compile(pattern, flags=re.M)
    matches = list(rx.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"{desc}: expected exactly one structural anchor, found {len(matches)}.\nFile: {path}"
        )
    m = matches[0]
    write(path, text[:m.start()] + block + text[m.start():])
    print("[OK]", desc)


def insert_after_regex_once(path: Path, pattern: str, block: str, desc: str):
    """Insert *block* immediately after one structural regex anchor."""
    text = read(path)
    rx = re.compile(pattern, flags=re.M)
    matches = list(rx.finditer(text))
    if len(matches) != 1:
        raise RuntimeError(
            f"{desc}: expected exactly one structural anchor, found {len(matches)}.\nFile: {path}"
        )
    m = matches[0]
    write(path, text[:m.end()] + block + text[m.end():])
    print("[OK]", desc)


def set_define(path: Path, name: str, replacement: str, desc: str):
    """Set one Marlin #define regardless of whether the baseline has it commented."""
    pattern = rf"^[ \t]*(?://[ \t]*)?#define[ \t]+{re.escape(name)}\b[^\r\n]*$"
    regex_once(path, pattern, replacement, desc)


def set_bool_define(path: Path, name: str, enabled: bool, desc: str, comment: str = ""):
    suffix = f"  // {comment}" if comment else ""
    replacement = f"#define {name}{suffix}" if enabled else f"//#define {name}{suffix}"
    set_define(path, name, replacement, desc)


def safe_extract(zf: zipfile.ZipFile, dest: Path):
    root = dest.resolve()
    for member in zf.infolist():
        target = (dest / member.filename).resolve()
        try:
            target.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"Unsafe path inside ZIP: {member.filename}") from exc
    zf.extractall(dest)


def extract_marlin():
    banner("EXTRACTING MARLIN")

    if OUT.exists():
        print("[...] Removing existing generated project")
        shutil.rmtree(OUT)

    with tempfile.TemporaryDirectory(prefix="kp3s_marlin_") as td_name:
        td = Path(td_name)
        extract = td / "extract"
        extract.mkdir()

        with zipfile.ZipFile(MARLIN_ZIP) as zf:
            safe_extract(zf, extract)

        roots = [p for p in extract.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise RuntimeError(
                f"Unexpected Marlin ZIP structure: {len(roots)} root directories."
            )
        shutil.copytree(roots[0], OUT)

    marlin_dir = OUT / "Marlin"
    if not (OUT / "platformio.ini").exists() or not (marlin_dir / "Configuration.h").exists():
        raise RuntimeError("Marlin project structure is incomplete after extraction.")

    shutil.copy2(CONFIG_H, marlin_dir / "Configuration.h")
    shutil.copy2(CONFIG_ADV_H, marlin_dir / "Configuration_adv.h")
    print("[OK] Official Kingroon/KP3S configuration applied")


def patch_configuration():
    banner("APPLYING V1 NOKIA UI + SAMSUNG CONTROLS + BLTOUCH + FILAMENT + MPU6050")

    cfg = OUT / "Marlin" / "Configuration.h"
    adv = OUT / "Marlin" / "Configuration_adv.h"
    c2 = OUT / "Marlin" / "src" / "inc" / "Conditionals-2-LCD.h"
    c4 = OUT / "Marlin" / "src" / "inc" / "Conditionals-4-adv.h"
    c5 = OUT / "Marlin" / "src" / "inc" / "Conditionals-5-post.h"
    pins = OUT / "Marlin" / "src" / "pins" / "stm32f1" / "pins_MKS_ROBIN_NANO_common.h"
    dogm = OUT / "Marlin" / "src" / "lcd" / "dogm" / "marlinui_DOGM.h"
    ui_dogm_cpp = OUT / "Marlin" / "src" / "lcd" / "dogm" / "marlinui_DOGM.cpp"
    ui_cpp = OUT / "Marlin" / "src" / "lcd" / "marlinui.cpp"
    marlin_core = OUT / "Marlin" / "src" / "MarlinCore.cpp"
    m24m25 = OUT / "Marlin" / "src" / "gcode" / "sd" / "M24_M25.cpp"
    status_cpp = OUT / "Marlin" / "src" / "lcd" / "dogm" / "status_screen_DOGM.cpp"
    nokia_status = OUT / "Marlin" / "src" / "lcd" / "dogm" / "status_screen_NOKIA5110.cpp"
    feedback_h = OUT / "Marlin" / "src" / "feature" / "kp3s_feedback.h"
    ue5000_h = OUT / "Marlin" / "src" / "feature" / "kp3s_ue5000.h"
    ue5000_impl_h = OUT / "Marlin" / "src" / "feature" / "kp3s_ue5000_impl.h"
    mpu6050_h = OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050.h"
    mpu6050_impl_h = OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050_impl.h"
    display_runtime_h = OUT / "Marlin" / "src" / "feature" / "kp3s_display_runtime.h"
    print_state_h = OUT / "Marlin" / "src" / "feature" / "kp3s_print_state.h"
    print_state_impl_h = OUT / "Marlin" / "src" / "feature" / "kp3s_print_state_impl.h"
    bltouch_runtime_h = OUT / "Marlin" / "src" / "feature" / "kp3s_bltouch_runtime.h"
    ui_context_h = OUT / "Marlin" / "src" / "feature" / "kp3s_ui_context.h"
    ui_text_h = OUT / "Marlin" / "src" / "feature" / "kp3s_ui_text.h"
    menu_cpp = OUT / "Marlin" / "src" / "lcd" / "menu" / "menu.cpp"
    menu_config = OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_configuration.cpp"
    g29 = OUT / "Marlin" / "src" / "gcode" / "bedlevel" / "abl" / "G29.cpp"
    g28 = OUT / "Marlin" / "src" / "gcode" / "calibrate" / "G28.cpp"
    probe_cpp = OUT / "Marlin" / "src" / "module" / "probe.cpp"
    joystick_h = OUT / "Marlin" / "src" / "feature" / "joystick.h"
    settings_cpp = OUT / "Marlin" / "src" / "module" / "settings.cpp"
    queue_cpp = OUT / "Marlin" / "src" / "gcode" / "queue.cpp"
    eeprom_gcode = OUT / "Marlin" / "src" / "gcode" / "eeprom" / "M500-M504.cpp"

    regex_once(
        cfg,
        r"^[ \t]*#define[ \t]+MKS_ROBIN_TFT24\b[^\r\n]*$",
        "//#define MKS_ROBIN_TFT24  // disabled: Nokia 5110",
        "Disable MKS_ROBIN_TFT24",
    )
    regex_once(
        cfg,
        r"^[ \t]*#define[ \t]+TFT_COLOR_UI\b[^\r\n]*$",
        "//#define TFT_COLOR_UI  // disabled: Nokia 5110",
        "Disable TFT_COLOR_UI",
    )
    regex_once(
        cfg,
        r"^[ \t]*#define[ \t]+TOUCH_SCREEN\b[^\r\n]*$",
        "//#define TOUCH_SCREEN  // disabled: Nokia 5110",
        "Disable TOUCH_SCREEN",
    )

    # Optional BLTouch support for Kingroon KP3 V1.3.
    # PA11 remains the mechanical Z_MIN microswitch. The probe uses PC4 / Z-MAX (Z+).
    # Support is compiled in, but the feature starts OFF and is enabled from the display.
    regex_once(
        cfg,
        r"^[ \t]*//[ \t]*#define[ \t]+BLTOUCH\b[^\r\n]*$",
        "#define BLTOUCH  // control / servo on PA8 - 3D Touch connector",
        "Enable BLTouch",
    )
    regex_once(
        cfg,
        r"^[ \t]*//[ \t]*#define[ \t]+USE_PROBE_FOR_Z_HOMING\b[^\r\n]*$",
        "//#define USE_PROBE_FOR_Z_HOMING  // Z homing remains on the PA11 microswitch",
        "Keep the Z microswitch for homing",
    )
    regex_once(
        cfg,
        r"^[ \t]*#define[ \t]+Z_MIN_PROBE_USES_Z_MIN_ENDSTOP_PIN\b[^\r\n]*$",
        "//#define Z_MIN_PROBE_USES_Z_MIN_ENDSTOP_PIN  // BLTouch probe is separate on PC4",
        "Keep probe separate from Z_MIN PA11",
    )
    regex_once(
        cfg,
        r"^[ \t]*#define[ \t]+MESH_BED_LEVELING\b[^\r\n]*$",
        "//#define MESH_BED_LEVELING  // replaced by bilinear BLTouch leveling",
        "Disable manual Mesh Bed Leveling",
    )
    regex_once(
        cfg,
        r"^[ \t]*//[ \t]*#define[ \t]+AUTO_BED_LEVELING_BILINEAR\b[^\r\n]*$",
        "#define AUTO_BED_LEVELING_BILINEAR",
        "Enable Auto Bed Leveling Bilinear",
    )
    regex_once(
        cfg,
        r"^[ \t]*//[ \t]*#define[ \t]+Z_SAFE_HOMING\b[^\r\n]*$",
        "//#define Z_SAFE_HOMING  // not needed: Z homing uses the microswitch",
        "Keep Z Safe Homing disabled",
    )
    regex_once(
        cfg,
        r"^[ \t]*//[ \t]*#define[ \t]+FILAMENT_RUNOUT_SENSOR\b[^\r\n]*$",
        "#define FILAMENT_RUNOUT_SENSOR",
        "Enable filament runout detection",
    )
    regex_once(
        adv,
        r"^[ \t]*//[ \t]*#define[ \t]+ADVANCED_PAUSE_FEATURE\b[^\r\n]*$",
        "#define ADVANCED_PAUSE_FEATURE",
        "Enable Advanced Pause / M600",
    )

    # V1 serial spool architecture: transfer the complete G-code to SD first,
    # then print locally. The host receives telemetry instead of streaming moves.
    regex_once(
        adv,
        r"^[ \t]*//[ \t]*#define[ \t]+BINARY_FILE_TRANSFER\b[^\r\n]*$",
        "#define BINARY_FILE_TRANSFER",
        "Enable binary serial file transfer / M28 B1",
    )
    regex_once(
        adv,
        r"^[ \t]*//[ \t]*#define[ \t]+AUTO_REPORT_POSITION\b[^\r\n]*$",
        "#define AUTO_REPORT_POSITION",
        "Enable automatic position telemetry / M154",
    )
    regex_once(
        adv,
        r"^[ \t]*//[ \t]*#define[ \t]+AUTO_REPORT_SD_STATUS\b[^\r\n]*$",
        "#define AUTO_REPORT_SD_STATUS",
        "Enable automatic SD progress telemetry / M27",
    )
    # AUTO_REPORT_TEMPERATURES and EXTENDED_CAPABILITIES_REPORT are enabled in
    # the Marlin 2.1.3-b3 baseline. Validation below makes this an invariant.

    # V1 runtime-oriented Marlin feature set. Hardware identities, pin assignments,
    # thermistor types, motor directions, build volume and thermal safety remain compile-time
    # invariants. User-tunable behavior is compiled in and exposed through Marlin menus/G-code
    # so it can be changed and stored with M500 instead of rebuilding firmware.
    set_define(cfg, "STRING_CONFIG_H_AUTHOR", '#define STRING_CONFIG_H_AUTHOR "spidoug" // KP3S Marlin Firmware V1', "Set V1 firmware author")
    set_bool_define(cfg, "PID_EDIT_MENU", True, "Enable runtime PID editing")
    set_bool_define(cfg, "PID_AUTOTUNE_MENU", True, "Enable PID autotune menu")
    set_bool_define(cfg, "LCD_BED_TRAMMING", True, "Enable manual bed tramming menu")
    set_bool_define(cfg, "EEPROM_SETTINGS", True, "Persist runtime tuning in EEPROM")
    set_bool_define(cfg, "EEPROM_AUTO_INIT", True, "Auto-initialize invalid EEPROM after V1 flash")
    set_bool_define(cfg, "PRINTCOUNTER", True, "Enable persistent print statistics")
    set_bool_define(cfg, "BAUD_RATE_GCODE", True, "Enable runtime serial baud control with M575")

    set_bool_define(adv, "LIN_ADVANCE", True, "Compile Linear Advance for runtime tuning")
    regex_once(
        adv,
        r"^[ \t]*#define[ \t]+ADVANCE_K[ \t]+0\.22[ \t]*[^\r\n]*$",
        "    #define ADVANCE_K 0.0         // V1: compiled in, disabled until K is set",
        "Default Linear Advance to off",
    )

    set_bool_define(adv, "INPUT_SHAPING_X", True, "Compile X input shaping")
    set_bool_define(adv, "INPUT_SHAPING_Y", True, "Compile Y input shaping")
    set_define(adv, "SHAPING_FREQ_X", "    #define SHAPING_FREQ_X   0.0        // V1: disabled until tuned with LCD / M593", "Default X input shaping to off")
    set_define(adv, "SHAPING_FREQ_Y", "    #define SHAPING_FREQ_Y   0.0        // V1: disabled until tuned with LCD / M593", "Default Y input shaping to off")
    set_define(adv, "SHAPING_MIN_FREQ", "  #define SHAPING_MIN_FREQ  20.0      // reserve a practical runtime tuning range", "Set input shaping runtime range")
    set_bool_define(adv, "SHAPING_MENU", True, "Expose input shaping in Advanced Settings")

    set_bool_define(adv, "FWRETRACT", True, "Compile firmware retract / M207 M208 M209")
    set_bool_define(adv, "BABYSTEPPING", True, "Enable Z babystepping")
    set_bool_define(adv, "BABYSTEP_ZPROBE_OFFSET", True, "Allow live probe Z-offset babystepping")
    set_bool_define(adv, "PROBE_OFFSET_WIZARD", True, "Enable probe Z-offset wizard")

    set_bool_define(adv, "POWER_LOSS_RECOVERY", True, "Compile power-loss recovery / M413")
    set_define(adv, "PLR_ENABLED_DEFAULT", "    #define PLR_ENABLED_DEFAULT       false // V1: opt-in, save with M500", "Keep power-loss recovery off by default")

    set_bool_define(adv, "LONG_FILENAME_HOST_SUPPORT", True, "Enable long filename host support")
    set_bool_define(adv, "LONG_FILENAME_WRITE_SUPPORT", True, "Enable long filename writes and binary uploads")
    set_bool_define(adv, "SCROLL_LONG_FILENAMES", True, "Scroll long filenames instead of overlapping")
    set_bool_define(adv, "STATUS_MESSAGE_SCROLLING", True, "Scroll long LCD status messages")
    set_bool_define(adv, "SDCARD_SORT_ALPHA", True, "Enable alphabetical SD sorting")
    set_define(adv, "SDSORT_GCODE", "    #define SDSORT_GCODE true   // runtime M34 / LCD sort control", "Allow SD sorting runtime control")

    set_bool_define(adv, "CANCEL_OBJECTS", True, "Enable M486 object cancellation")
    set_bool_define(adv, "PARK_HEAD_ON_PAUSE", True, "Park the toolhead on pause and filament change")
    set_bool_define(adv, "FILAMENT_LOAD_UNLOAD_GCODES", True, "Enable M701/M702 load-unload controls")
    set_bool_define(adv, "HOST_ACTION_COMMANDS", True, "Enable host action reporting")
    set_bool_define(adv, "HOST_PROMPT_SUPPORT", True, "Enable host prompt support")
    set_bool_define(adv, "EMERGENCY_PARSER", True, "Enable immediate serial emergency commands")
    set_bool_define(adv, "ADVANCED_OK", True, "Report queue/planner capacity to serial hosts")
    set_bool_define(adv, "LCD_INFO_MENU", True, "Enable Marlin information menu")
    set_bool_define(adv, "BUILD_INFO_MENU_ITEM", True, "Expose build information")
    set_bool_define(adv, "M115_GEOMETRY_REPORT", True, "Report machine geometry to connected hosts")
    set_bool_define(adv, "EDITABLE_DISPLAY_TIMEOUT", True, "Allow display timeout changes from the LCD")

    # Five-language Marlin menu. English is always language index 0 / default.
    regex_once(
        cfg,
        r"^[ \t]*#define[ \t]+LCD_LANGUAGE[ \t]+[^\r\n]+$",
        "#define LCD_LANGUAGE en\n#define LCD_LANGUAGE_2 pt_br\n#define LCD_LANGUAGE_3 es\n#define LCD_LANGUAGE_4 fr\n#define LCD_LANGUAGE_5 de",
        "Configure five LCD languages",
    )
    regex_once(
        adv,
        r"^[ \t]*//[ \t]*#define[ \t]+LCD_LANGUAGE_AUTO_SAVE\b[^\r\n]*$",
        "#define LCD_LANGUAGE_AUTO_SAVE",
        "Persist the selected LCD language",
    )

    anchor = "//\n// RepRapDiscount FULL GRAPHIC Smart Controller\n"
    replace_once(
        cfg,
        anchor,
        """//
// Nokia 5110 / PCD8544 84x48 - KP3S
//
#define NOKIA5110_LCD
#define USE_SMALL_INFOFONT  // 6x9 status font fits the Nokia 84x48 cleanly
#define KP3S_SMART_UI
#define KP3S_CONTEXT_NAVIGATION
#define KP3S_RUNTIME_DISPLAY
#define KP3S_UE5000
#define TONE_QUEUE_LENGTH 16  // larger queue for non-blocking feedback sequences
//#define NOKIA5110_BL_ACTIVE_LOW  // enable if the backlight is active-low
#define KP3S_UE5000_LED_ACTIVE_LOW  // Samsung board LED is active-low
#define KP3S_UE5000_ROTATION 0      // 0, 90, 180 or 270 degrees
#define KP3S_UE5000_SOFT_POWER      // logical standby: only the red status LED stays on
#define KP3S_UE5000_POWER_HOLD_MS 5000UL // hold KEY1 for 5 s: idle -> standby, standby -> wake
#define KP3S_SERIAL_JOB_IDLE_TIMEOUT_MS 300000UL // inferred serial job expires after 5 min without job traffic
#define KP3S_RUNTIME_BLTOUCH          // OFF by default; enabled from KP3S Setup > BLTouch / Leveling

// PA4 is reserved for filament runout. MPU6050 uses the FFC again.
// Default: SDA=PD9/FFC17, SCL=PD8/FFC16. Runtime menu can swap SDA/SCL.
// VCC=FFC1/3.3V, GND=FFC2.
#define KP3S_MPU6050
#define KP3S_MPU6050_SOFT_I2C_DELAY_US 8
#define KP3S_MPU6050_POLL_IDLE_MS 20UL
#define KP3S_MPU6050_POLL_PRINT_MS 10UL
//#define KP3S_MPU6050_DEBUG  // serial: address, WHO_AM_I and raw accel/gyro
// KEY2 is decoded by RC discharge time on the FFC, with no external pull-up.
// Hardware: KEY2 -- 1k -- PE13 and 100 nF from PE13 to GND.
// Firmware learns the real idle RC value and creates an adaptive neutral region.
// This prevents leakage / RC tolerance from latching a direction.
#define KP3S_UE5000_RC_DOWN_MAX_US      60
#define KP3S_UE5000_RC_UP_MAX_US       220
#define KP3S_UE5000_RC_RIGHT_MAX_US    900
#define KP3S_UE5000_RC_LEFT_MAX_US    5200
#define KP3S_UE5000_RC_TIMEOUT_US     6500
#define KP3S_UE5000_RC_CAL_SAMPLES       9  // startup samples used to learn neutral
#define KP3S_UE5000_RC_NEUTRAL_PCT      92  // >=92% of baseline is neutral
#define KP3S_UE5000_RC_NEUTRAL_MARGIN_US 180 // minimum jitter margin
#define KP3S_UE5000_RC_RELEASE_SAMPLES    3  // stable neutral samples before re-arming
#define KP3S_UE5000_RC_REBASE_SAMPLES     4  // update baseline only after repeated higher samples
//#define KP3S_UE5000_DEBUG           // print RC time, baseline, neutral cutoff and IR codes
//#define NOKIA5110_RAW_DIAG          // enable only for LCD diagnostics

""" + anchor,
        "Enable NOKIA5110_LCD",
    )

    # SHOW_BOOTSCREEN is in Configuration_adv.h for this configuration.
    regex_once(
        adv,
        r"^[ \t]*#define[ \t]+SHOW_BOOTSCREEN\b[^\r\n]*$",
        "  //#define SHOW_BOOTSCREEN  // disabled for the 84x48 LCD",
        "Disable SHOW_BOOTSCREEN",
    )

    regex_once(
        adv,
        r"^[ \t]*//[ \t]*#define[ \t]+LCD_BACKLIGHT_TIMEOUT_MINS\b[^\r\n]*$",
        "#define LCD_BACKLIGHT_TIMEOUT_MINS 2  // turn off after 2 min without interaction; M255 overrides",
        "Enable backlight timeout",
    )

    replace_once(
        c2,
        "#if ANY(MKS_MINI_12864, ENDER2_STOCKDISPLAY)",
        """#if ENABLED(NOKIA5110_LCD)

  #define DOGLCD
  #define IS_ULTIPANEL 1
  // The PCD8544 physical transport is KP3S-specific and implemented in
  // marlinui_DOGM.cpp. Do not use FORCE_SOFT_SPI here: the generic STM32 HAL
  // toggles GPIO too quickly and does not reproduce the validated RAW transport.
  #define LCD_PIXEL_WIDTH 84
  #define LCD_PIXEL_HEIGHT 48
  #define LCD_WIDTH 14
  #define LCD_HEIGHT 4
  #define STD_ENCODER_PULSES_PER_STEP 1
  #define STD_ENCODER_STEPS_PER_MENU_ITEM 1

#elif ANY(MKS_MINI_12864, ENDER2_STOCKDISPLAY)""",
        "Register Nokia display in MarlinUI",
    )

    # Conditionals-5-post.h enables HAS_LCD_CONTRAST. Defining
    # LCD_CONTRAST_DEFAULT in Conditionals-2 alone is not sufficient.
    replace_once(
        c5,
        "#if ENABLED(CARTESIO_UI)",
        """#if ENABLED(NOKIA5110_LCD)
  #define _LCD_CONTRAST_MIN    0
  #define _LCD_CONTRAST_INIT 128
  #define _LCD_CONTRAST_MAX  255
#elif ENABLED(CARTESIO_UI)""",
        "Enable PCD8544 contrast",
    )

    replace_once(
        dogm,
        "#if ENABLED(REPRAPWORLD_GRAPHICAL_LCD)",
        """#if ENABLED(NOKIA5110_LCD)

  // Use U8glib's PCD8544 framebuffer, but keep the physical transport
  // in a KP3S-specific bit-bang routine defined in the .cpp.
  extern u8g_dev_t u8g_dev_pcd8544_84x48_sw_spi;
  #define U8G_CLASS U8GLIB
  #define U8G_PARAM &u8g_dev_pcd8544_84x48_sw_spi, u8g_com_KP3S_PCD8544_sw_spi_fn

#elif ENABLED(REPRAPWORLD_GRAPHICAL_LCD)""",
        "Select U8glib PCD8544 framebuffer",
    )

    # Keep the U8glib framebuffer / menus, but replace only
    # the physical transport with the exact bit-bang timing validated by the RAW self-test.
    # This avoids both the generic Arduino driver and the overly fast STM32 HAL path.
    replace_once(
        ui_dogm_cpp,
        "U8G_CLASS u8g;",
        r"""#if ENABLED(NOKIA5110_LCD)

#include "../../inc/MarlinConfig.h"
#include "../../HAL/shared/Delay.h"

// PCD8544 / Nokia 5110 - physical transport validated on this KP3S board.
// O display amostra DIN na borda de subida do CLK. Por isso cada bit faz:
// CLK LOW -> estabiliza MOSI -> espera 3 us -> CLK HIGH -> espera 3 us.
static inline void kp3s_pcd8544_shift_out(uint8_t value) {
  for (uint8_t mask = 0x80; mask; mask >>= 1) {
    WRITE(DOGLCD_SCK, LOW);
    WRITE(DOGLCD_MOSI, (value & mask) ? HIGH : LOW);
    DELAY_US(3);
    WRITE(DOGLCD_SCK, HIGH);
    DELAY_US(3);
  }
}

static uint8_t u8g_com_KP3S_PCD8544_sw_spi_fn(
  u8g_t *u8g, const uint8_t msg, const uint8_t arg_val, void *arg_ptr
) {
  (void)u8g;

  switch (msg) {
    case U8G_COM_MSG_INIT:
      SET_OUTPUT(DOGLCD_SCK);
      SET_OUTPUT(DOGLCD_MOSI);
      SET_OUTPUT(DOGLCD_CS);
      SET_OUTPUT(DOGLCD_A0);
      #if PIN_EXISTS(LCD_RESET)
        SET_OUTPUT(LCD_RESET_PIN);
        WRITE(LCD_RESET_PIN, HIGH);
      #endif
      WRITE(DOGLCD_SCK, LOW);
      WRITE(DOGLCD_MOSI, LOW);
      WRITE(DOGLCD_CS, HIGH);
      WRITE(DOGLCD_A0, LOW);
      break;

    case U8G_COM_MSG_STOP:
      WRITE(DOGLCD_CS, HIGH);
      break;

    case U8G_COM_MSG_RESET:
      #if PIN_EXISTS(LCD_RESET)
        WRITE(LCD_RESET_PIN, arg_val ? HIGH : LOW);
      #endif
      break;

    case U8G_COM_MSG_CHIP_SELECT:
      WRITE(DOGLCD_CS, arg_val ? LOW : HIGH);
      break;

    case U8G_COM_MSG_WRITE_BYTE:
      kp3s_pcd8544_shift_out(arg_val);
      break;

    case U8G_COM_MSG_WRITE_SEQ: {
      const uint8_t *ptr = static_cast<const uint8_t*>(arg_ptr);
      for (uint8_t i = 0; i < arg_val; ++i)
        kp3s_pcd8544_shift_out(ptr[i]);
    } break;

    case U8G_COM_MSG_WRITE_SEQ_P: {
      const uint8_t *ptr = static_cast<const uint8_t*>(arg_ptr);
      for (uint8_t i = 0; i < arg_val; ++i)
        kp3s_pcd8544_shift_out(u8g_pgm_read(ptr + i));
    } break;

    case U8G_COM_MSG_ADDRESS:
      WRITE(DOGLCD_A0, arg_val ? HIGH : LOW);
      break;
  }

  return 1;
}

U8G_CLASS u8g(U8G_PARAM);
#else
U8G_CLASS u8g;
#endif""",
        "Instantiate PCD8544 with the KP3S bit-bang driver",
    )

    replace_once(
        ui_dogm_cpp,
        '#include "../../HAL/shared/Delay.h"\n',
        '#include "../../HAL/shared/Delay.h"\n#include "../../feature/kp3s_display_runtime.h"\n',
        "Include runtime display rotation support",
    )
    replace_once(
        ui_dogm_cpp,
        'U8G_CLASS u8g;\n#endif',
        r'''U8G_CLASS u8g;
#endif

#if ENABLED(KP3S_RUNTIME_DISPLAY)
  bool kp3s_display_flipped = false;

  void kp3s_display_apply_rotation() {
    u8g.undoRotation();
    if (kp3s_display_flipped) u8g.setRot180();
    ui.refresh();
  }
#endif''',
        "Create runtime LCD 180-degree rotation",
    )
    replace_once(
        ui_dogm_cpp,
        r'''  #if LCD_SCREEN_ROTATE == 90
    u8g.setRot90();
  #elif LCD_SCREEN_ROTATE == 180
    u8g.setRot180();
  #elif LCD_SCREEN_ROTATE == 270
    u8g.setRot270();
  #endif
''',
        r'''  #if LCD_SCREEN_ROTATE == 90
    u8g.setRot90();
  #elif LCD_SCREEN_ROTATE == 180
    u8g.setRot180();
  #elif LCD_SCREEN_ROTATE == 270
    u8g.setRot270();
  #endif

  #if ENABLED(KP3S_RUNTIME_DISPLAY)
    kp3s_display_apply_rotation();
  #endif
''',
        "Apply persisted LCD rotation after display initialization",
    )

    display_runtime_h.write_text(
        r'''#pragma once

#include "../inc/MarlinConfigPre.h"

#if ENABLED(KP3S_RUNTIME_DISPLAY)
  extern bool kp3s_display_flipped;
  void kp3s_display_apply_rotation();
#endif
''',
        encoding="utf-8",
    )
    print("[OK] Create persistent runtime display rotation")

    ui_text_h.write_text(
        r'''#pragma once

#include "../inc/MarlinConfig.h"
#include "../lcd/marlinui.h"

#if ENABLED(KP3S_SMART_UI)
  // Runtime translator for every KP3S-specific LCD string.
  // Language order is fixed by Configuration.h: en, pt_br, es, fr, de.
  static inline FSTR_P kp3s_tr(
    FSTR_P const en, FSTR_P const pt, FSTR_P const es,
    FSTR_P const fr, FSTR_P const de
  ) {
    #if HAS_MULTI_LANGUAGE
      switch (ui.language) {
        case 1: return pt;
        case 2: return es;
        case 3: return fr;
        case 4: return de;
      }
    #endif
    return en;
  }
#endif
''',
        encoding="utf-8",
    )
    print("[OK] Create runtime localization helper for all KP3S LCD text")

    replace_once(
        ui_dogm_cpp,
        '''    if (onpage) lcd_put_u8str(0, baseline, ftpl, itemIndex, itemStringC, itemStringF);
''',
        '''    #if ENABLED(NOKIA5110_LCD)
      // The edit screen itself is the active selection, so long labels scroll here too.
      // Reserve one glyph for the colon/value separator and never draw outside that field.
      const uint8_t kp3s_visible_chars = lcd_chr_fit > 1 ? lcd_chr_fit - 1 : 0;
      const u8g_uint_t kp3s_label_pixel_limit = kp3s_visible_chars * one_chr_width;
      char kp3s_edit_label[MAX_MESSAGE_SIZE * LANG_CHARSIZE + 2] = { 0 };
      expand_u8str(kp3s_edit_label, ftpl, itemIndex, itemStringC, itemStringF, MAX_MESSAGE_SIZE);
      const uint8_t kp3s_edit_len = utf8_strlen(kp3s_edit_label);
      if (onpage && kp3s_edit_len > kp3s_visible_chars) {
        const uint8_t off = kp3s_marquee_offset(ftpl, 0xFE, kp3s_visible_chars, kp3s_edit_len);
        lcd_moveto(0, baseline);
        lcd_put_u8str_max(kp3s_marquee_advance(kp3s_edit_label, off), kp3s_label_pixel_limit);
        ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
      }
      else if (onpage)
        lcd_put_u8str(0, baseline, ftpl, itemIndex, itemStringC, itemStringF, kp3s_label_pixel_limit);
    #else
      if (onpage) lcd_put_u8str(0, baseline, ftpl, itemIndex, itemStringC, itemStringF);
    #endif
''',
        "Clip long DOGM edit labels to the Nokia viewport",
    )

    # Nokia 84x48 selected-label marquee. Keep all drawing inside the original
    # label field and preserve the right-side arrow / editable value.
    replace_once(
        ui_dogm_cpp,
        "#include LANGUAGE_DATA_INCL(LCD_LANGUAGE)\n",
        r'''#if ENABLED(NOKIA5110_LCD)
// Selected-label marquee is deliberately inserted outside the Nokia transport
// #if/#else block. Work on the fully-expanded RAM label, not on MenuItemBase's
// substitution state. Normal Marlin menu items don't call MenuItemBase::init(),
// so itemIndex/itemStringC/itemStringF may legitimately contain state from an
// earlier indexed item. Expanding first makes the marquee deterministic and
// also supports translated/substituted labels.
static const char* kp3s_marquee_advance(const char *p, uint8_t chars) {
  while (chars-- && *p) {
    ++p;
    while ((*p & 0xC0) == 0x80) ++p;
  }
  return p;
}

static uint8_t kp3s_marquee_offset(
  FSTR_P const label_id, const uint8_t row, const uint8_t visible_chars, const uint8_t length
) {
  static PGM_P last_label = nullptr;
  static uint8_t last_row = 0xFF, last_width = 0;
  static millis_t started_ms = 0;
  PGM_P p = FTOP(label_id);
  if (p != last_label || row != last_row || visible_chars != last_width) {
    last_label = p; last_row = row; last_width = visible_chars; started_ms = millis();
  }
  if (length <= visible_chars || !visible_chars) return 0;
  const uint8_t span = length - visible_chars;
  constexpr millis_t START_PAUSE_MS = 900UL, STEP_MS = 420UL, END_PAUSE_MS = 1000UL;
  const millis_t forward_ms = millis_t(span) * STEP_MS;
  const millis_t cycle_ms = START_PAUSE_MS + forward_ms + END_PAUSE_MS;
  const millis_t phase_ms = cycle_ms ? (millis() - started_ms) % cycle_ms : 0;
  if (phase_ms < START_PAUSE_MS) return 0;
  if (phase_ms < START_PAUSE_MS + forward_ms)
    return _MIN(span, uint8_t((phase_ms - START_PAUSE_MS) / STEP_MS + 1));
  return span;
}
#endif

#include LANGUAGE_DATA_INCL(LCD_LANGUAGE)
''',
        "Create selected long-label marquee for Nokia",
    )

    replace_once(
        ui_dogm_cpp,
        '''    uint8_t n = LCD_WIDTH - 1;
    n -= lcd_put_u8str(ftpl, itemIndex, itemStringC, itemStringF, n);
    for (; n; --n) lcd_put_u8str(F(" "));
    lcd_put_lchar(LCD_PIXEL_WIDTH - (MENU_FONT_WIDTH), row_y2, post_char);
''',
        '''    uint8_t n = LCD_WIDTH - 1;
    #if ENABLED(NOKIA5110_LCD)
      char kp3s_label[MAX_MESSAGE_SIZE * LANG_CHARSIZE + 2] = { 0 };
      uint8_t kp3s_len = 0;
      if (sel) {
        expand_u8str(kp3s_label, ftpl, itemIndex, itemStringC, itemStringF, MAX_MESSAGE_SIZE);
        kp3s_len = utf8_strlen(kp3s_label);
      }
      const bool kp3s_scroll = sel && kp3s_len > n;
      if (kp3s_scroll) {
        const uint8_t off = kp3s_marquee_offset(ftpl, row, n, kp3s_len);
        const pixel_len_t used_px = lcd_put_u8str_max(kp3s_marquee_advance(kp3s_label, off), pixel_len_t(n) * MENU_FONT_WIDTH);
        const uint8_t used = _MIN(n, uint8_t((used_px + MENU_FONT_WIDTH - 1) / MENU_FONT_WIDTH));
        n -= used;
        ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
      }
      else
    #endif
        n -= lcd_put_u8str(ftpl, itemIndex, itemStringC, itemStringF, n);
    for (; n; --n) lcd_put_u8str(F(" "));
    lcd_put_lchar(LCD_PIXEL_WIDTH - (MENU_FONT_WIDTH), row_y2, post_char);
''',
        "Scroll selected long menu labels inside reserved field",
    )

    replace_once(
        ui_dogm_cpp,
        '''    uint8_t n = LCD_WIDTH - 2 - vallen * prop;
    n -= lcd_put_u8str(ftpl, itemIndex, itemStringC, itemStringF, n);
    if (vallen) {
''',
        '''    uint8_t n = LCD_WIDTH - 2 - vallen * prop;
    #if ENABLED(NOKIA5110_LCD)
      char kp3s_label[MAX_MESSAGE_SIZE * LANG_CHARSIZE + 2] = { 0 };
      uint8_t kp3s_len = 0;
      if (sel) {
        expand_u8str(kp3s_label, ftpl, itemIndex, itemStringC, itemStringF, MAX_MESSAGE_SIZE);
        kp3s_len = utf8_strlen(kp3s_label);
      }
      const bool kp3s_scroll = sel && kp3s_len > n;
      if (kp3s_scroll) {
        const uint8_t off = kp3s_marquee_offset(ftpl, row, n, kp3s_len);
        const pixel_len_t used_px = lcd_put_u8str_max(kp3s_marquee_advance(kp3s_label, off), pixel_len_t(n) * MENU_FONT_WIDTH);
        const uint8_t used = _MIN(n, uint8_t((used_px + MENU_FONT_WIDTH - 1) / MENU_FONT_WIDTH));
        n -= used;
        ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
      }
      else
    #endif
        n -= lcd_put_u8str(ftpl, itemIndex, itemStringC, itemStringF, n);
    if (vallen) {
''',
        "Scroll selected long edit labels inside value-safe field",
    )

    pin_anchor = "#define BEEPER_PIN                          PC5\n"
    replace_once(
        pins,
        pin_anchor,
        pin_anchor + """
#if ENABLED(NOKIA5110_LCD)
  // Pins reclaimed from the original TFT, which is disabled in this build.
  #define DOGLCD_SCK                        PD5
  #define DOGLCD_MOSI                       PD14
  #define DOGLCD_CS                         PD7
  #define DOGLCD_A0                         PD11
  #define LCD_RESET_PIN                     PC6
  #define LCD_BACKLIGHT_PIN                 PD13
  #if ENABLED(NOKIA5110_BL_ACTIVE_LOW)
    #define KP3S_BACKLIGHT_ON_STATE          LOW
    #define KP3S_BACKLIGHT_OFF_STATE         HIGH
  #else
    #define KP3S_BACKLIGHT_ON_STATE          HIGH
    #define KP3S_BACKLIGHT_OFF_STATE         LOW
  #endif
#endif

#if ENABLED(KP3S_UE5000)
  // Samsung BN41-01840B / BN96-22413B - fully connected through the original FFC.
  // KEY1 is digital with internal pull-up. KEY2 is decoded by RC discharge time.
  // PE13 avoids the EXTI12 conflict with Y_STOP / PA12.
  // IR on PE7 avoids the EXTI4 conflict with Z_MAX / PC4 when endstop interrupts are enabled.
  #define KP3S_UE5000_KEY1_PIN              PE10  // FFC10 - center click
  #define KP3S_UE5000_KEY2_PIN              PE13  // FFC13 - resistive ladder through 1k + 100nF RC
  #define KP3S_UE5000_IR_PIN                PE7   // FFC7 - IR receiver; EXTI7 is available
  #define KP3S_UE5000_LED_PIN               PD10  // FFC18 - status LED
  #if ENABLED(KP3S_UE5000_LED_ACTIVE_LOW)
    #define KP3S_UE5000_LED_ON_STATE         LOW
    #define KP3S_UE5000_LED_OFF_STATE        HIGH
  #else
    #define KP3S_UE5000_LED_ON_STATE         HIGH
    #define KP3S_UE5000_LED_OFF_STATE        LOW
  #endif
  // BTN_ENC is only a logical dummy pin and is not physically wired.
  // PE15 / FFC15 is kept as the internal dummy input. PD8/FFC16 and PD9/FFC17 form the runtime-selectable MPU6050 I2C pair.
  #define BTN_ENC                           PE15
#endif

#if ENABLED(KP3S_MPU6050)
  // Default I2C orientation. The panel may swap these two lines at runtime.
  #define KP3S_MPU6050_SDA_PIN              PD9   // default SDA / FFC17
  #define KP3S_MPU6050_SCL_PIN              PD8   // default SCL / FFC16
#endif

#if ENABLED(KP3S_RUNTIME_BLTOUCH)
  // PA11 remains Z_MIN / microswitch. PC4 is dedicated to the probe input.
  #undef Z_MAX_PIN
  #define Z_MAX_PIN                         -1
  #define Z_MIN_PROBE_PIN                   PC4
#endif
""",
        "Add Nokia + UE5000 + MPU6050 + probe pin assignments",
    )

    replace_once(
        ui_cpp,
        '#include "marlinui.h"\nMarlinUI ui;',
        """#include "marlinui.h"

#if ENABLED(KP3S_UE5000)
  #include "../feature/kp3s_ue5000.h"
  // Implementation is included directly in this compiled translation unit. Marlin's
  // source filter does not automatically compile newly-added feature/*.cpp files.
  // Keeping the implementation here avoids linker undefined-reference errors.
  #include "../feature/kp3s_ue5000_impl.h"
#endif
#if ENABLED(KP3S_SMART_UI)
  #include "../feature/kp3s_feedback.h"
  #include "../feature/kp3s_print_state.h"
  #include "../feature/kp3s_print_state_impl.h"
#endif
#if ENABLED(KP3S_MPU6050)
  #include "../feature/kp3s_mpu6050.h"
  #include "../feature/kp3s_mpu6050_impl.h"
#endif
#if ENABLED(KP3S_RUNTIME_BLTOUCH)
  #include "../feature/kp3s_bltouch_runtime.h"
#endif
#if ENABLED(KP3S_CONTEXT_NAVIGATION)
  #include "../feature/kp3s_ui_context.h"
#endif

MarlinUI ui;

#if ENABLED(KP3S_RUNTIME_BLTOUCH)
  bool kp3s_bltouch_runtime_enabled = false;
#endif""",
        "Include UE5000 support in MarlinUI",
    )

    replace_once(
        ui_cpp,
        """void MarlinUI::update() {

    static uint16_t max_display_update_time = 0;
    const millis_t ms = millis();
""",
        """void MarlinUI::update() {

    static uint16_t max_display_update_time = 0;
    const millis_t ms = millis();

    #if ENABLED(KP3S_SMART_UI)
      const bool kp3s_printing_now = printingIsActive() || kp3s_serial_printing(ms);
      const bool kp3s_paused_now = printingIsPaused() || kp3s_serial_print_paused();
    #endif

    #if ENABLED(KP3S_UE5000_SOFT_POWER)
      // Logical standby is allowed only with no print, no queued motion and no heat target.
      // This makes the 5-second gesture impossible to interrupt an active machine action.
      const bool kp3s_can_standby = !kp3s_printing_now && !kp3s_paused_now
        && !planner.has_blocks_queued()
        && thermalManager.degTargetHotend(0) <= 0
        && thermalManager.degTargetBed() <= 0;
      const KP3SUE5000PowerEvent kp3s_power_event = kp3s_ue5000_power_task(ms, kp3s_can_standby);

      if (kp3s_power_event == KP3SUE5000PowerEvent::SLEPT) {
        clear_lcd();
        #if PIN_EXISTS(LCD_BACKLIGHT)
          WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_OFF_STATE);
          #if HAS_BACKLIGHT_TIMEOUT
            backlight_off_ms = 0;
          #endif
        #endif
        return;
      }

      if (!kp3s_ue5000_is_awake()) {
        #if PIN_EXISTS(LCD_BACKLIGHT)
          WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_OFF_STATE);
          #if HAS_BACKLIGHT_TIMEOUT
            backlight_off_ms = 0;
          #endif
        #endif
        return;
      }

      if (kp3s_power_event == KP3SUE5000PowerEvent::WOKE) {
        clear_lcd();
        #if PIN_EXISTS(LCD_BACKLIGHT)
          #if HAS_BACKLIGHT_TIMEOUT
            refresh_backlight_timeout();
          #else
            WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_ON_STATE);
          #endif
        #endif
        #if ENABLED(KP3S_SMART_UI)
          kp3s_feedback_sound(KP3SFeedback::BOOT);
        #endif
        TERN_(HAS_MARLINUI_MENU, refresh());
      }
    #endif

    #if ENABLED(KP3S_MPU6050)
      // Start only after leaving standby so the red-LED-only state is preserved.
      static bool kp3s_mpu_started = false;
      if (!kp3s_mpu_started) {
        kp3s_mpu6050_init();
        kp3s_mpu_started = true;
      }
      kp3s_mpu6050_task(ms);
    #endif

    #if ENABLED(KP3S_SMART_UI) && PIN_EXISTS(LCD_BACKLIGHT)
      // Wake the display when the print state changes. Normal inactivity
      // timeout remains in control afterwards, including during printing.
      static bool kp3s_was_printing = false, kp3s_was_paused = false;
      if (kp3s_printing_now != kp3s_was_printing || kp3s_paused_now != kp3s_was_paused) {
        #if HAS_BACKLIGHT_TIMEOUT
          refresh_backlight_timeout();
        #else
          WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_ON_STATE);
        #endif
        refresh();
        kp3s_was_printing = kp3s_printing_now;
        kp3s_was_paused = kp3s_paused_now;
      }
    #endif

    #if ENABLED(KP3S_UE5000) && HAS_ENCODER_ACTION
      // Context-aware navigation for the Samsung 4-way JOG and IR remote.
      // Lists use UP/DOWN. Confirmation and value-edit screens use LEFT/RIGHT.
      kp3s_ue5000_led_task(ms, kp3s_printing_now, kp3s_paused_now);
      const KP3SUE5000Action ue_action = kp3s_ue5000_poll(ms);

      if (ue_action != KP3SUE5000Action::NONE) {
        kp3s_ue5000_activity(ms);
        #if HAS_BACKLIGHT_TIMEOUT
          refresh_backlight_timeout();
        #endif

        switch (ue_action) {
          case KP3SUE5000Action::UP:
            #if ENABLED(KP3S_CONTEXT_NAVIGATION)
              if (!kp3s_ui_selection_mode && !kp3s_ui_edit_mode)
            #endif
              encoderDiff = -int8_t(ENCODER_STEPS_PER_MENU_ITEM * epps);
            kp3s_feedback_sound(KP3SFeedback::NAV);
            TERN_(HAS_MARLINUI_MENU, refresh());
            break;

          case KP3SUE5000Action::DOWN:
            #if ENABLED(KP3S_CONTEXT_NAVIGATION)
              if (!kp3s_ui_selection_mode && !kp3s_ui_edit_mode)
            #endif
              encoderDiff = int8_t(ENCODER_STEPS_PER_MENU_ITEM * epps);
            kp3s_feedback_sound(KP3SFeedback::NAV);
            TERN_(HAS_MARLINUI_MENU, refresh());
            break;

          case KP3SUE5000Action::LEFT:
            #if HAS_MARLINUI_MENU
              #if ENABLED(KP3S_CONTEXT_NAVIGATION)
                if (kp3s_ui_selection_mode || kp3s_ui_edit_mode) {
                  encoderDiff = -int8_t(ENCODER_STEPS_PER_MENU_ITEM * epps);
                  kp3s_feedback_sound(KP3SFeedback::NAV);
                  refresh();
                  break;
                }
              #endif
              if (!on_status_screen()) {
                goto_previous_screen();
                refresh();
              }
            #endif
            kp3s_feedback_sound(KP3SFeedback::BACK);
            break;

          case KP3SUE5000Action::BACK:
            #if HAS_MARLINUI_MENU
              if (!on_status_screen()) {
                goto_previous_screen();
                refresh();
              }
            #endif
            kp3s_feedback_sound(KP3SFeedback::BACK);
            break;

          case KP3SUE5000Action::RIGHT:
            #if HAS_MARLINUI_MENU
              #if ENABLED(KP3S_CONTEXT_NAVIGATION)
                if (kp3s_ui_selection_mode || kp3s_ui_edit_mode) {
                  encoderDiff = int8_t(ENCODER_STEPS_PER_MENU_ITEM * epps);
                  kp3s_feedback_sound(KP3SFeedback::NAV);
                  refresh();
                  break;
                }
              #endif
              lcd_clicked = true;
              refresh();
            #endif
            kp3s_feedback_sound(KP3SFeedback::SELECT);
            break;

          case KP3SUE5000Action::ENTER:
            #if HAS_MARLINUI_MENU
              lcd_clicked = true;
              refresh();
            #endif
            kp3s_feedback_sound(KP3SFeedback::SELECT);
            break;

          case KP3SUE5000Action::MENU:
            #if HAS_MARLINUI_MENU
              if (!on_status_screen()) return_to_status();
              lcd_clicked = true;
              refresh();
            #endif
            kp3s_feedback_sound(KP3SFeedback::SELECT);
            break;

          case KP3SUE5000Action::STATUS:
            #if HAS_MARLINUI_MENU
              return_to_status();
              refresh();
            #endif
            kp3s_feedback_sound(KP3SFeedback::BACK);
            break;

          case KP3SUE5000Action::PAUSE:
            #if HAS_MEDIA
              if (printingIsActive() && card.isFileOpen()) queue.inject(F("M25"));
            #endif
            break;

          case KP3SUE5000Action::RESUME:
            #if HAS_MEDIA
              if (printingIsPaused() && card.isFileOpen()) queue.inject(F("M24"));
            #endif
            break;

          case KP3SUE5000Action::NONE:
            break;
        }
      }
    #endif
""",
        "Add context-aware UE5000 JOG + IR navigation",
    )

    replace_once(
        marlin_core,
        """#include "lcd/marlinui.h"
""",
        """#include "lcd/marlinui.h"
#if ENABLED(KP3S_SMART_UI)
  #include "feature/kp3s_feedback.h"
#endif
#if ENABLED(KP3S_UE5000)
  #include "feature/kp3s_ue5000.h"
#endif
#if ENABLED(KP3S_RUNTIME_BLTOUCH)
  #include "feature/kp3s_bltouch_runtime.h"
#endif
""",
        "Include feedback support in Marlin core",
    )

    replace_once(
        marlin_core,
        """void startOrResumeJob() {
  if (!printingIsPaused()) {
""",
        """void startOrResumeJob() {
  #if ENABLED(KP3S_SMART_UI)
    const bool kp3s_was_paused = printingIsPaused();
  #endif
  if (!printingIsPaused()) {
""",
        "Distinguish print start from resume",
    )

    replace_once(
        marlin_core,
        """  print_job_timer.start();
}

#if HAS_MEDIA
""",
        """  print_job_timer.start();
  #if ENABLED(KP3S_SMART_UI)
    kp3s_feedback_sound(kp3s_was_paused ? KP3SFeedback::RESUME : KP3SFeedback::PRINT_START);
    #if PIN_EXISTS(LCD_BACKLIGHT)
      WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_OFF_STATE);
      #if HAS_BACKLIGHT_TIMEOUT
        ui.backlight_off_ms = 0;
      #endif
    #endif
  #endif
}

#if HAS_MEDIA
""",
        "Add start/resume feedback and turn off backlight",
    )

    replace_once(
        marlin_core,
        """  inline void abortSDPrinting() {
    IF_DISABLED(NO_SD_AUTOSTART, card.autofile_cancel());
""",
        """  inline void abortSDPrinting() {
    #if ENABLED(KP3S_SMART_UI)
      kp3s_feedback_sound(KP3SFeedback::ABORT);
    #endif
    IF_DISABLED(NO_SD_AUTOSTART, card.autofile_cancel());
""",
        "Add distinct abort feedback",
    )

    replace_once(
        marlin_core,
        """    if (queue.enqueue_one(F("M1001"))) {      // Keep trying until it gets queued
      marlin_state = MarlinState::MF_RUNNING; // Signal to stop trying
""",
        """    if (queue.enqueue_one(F("M1001"))) {      // Keep trying until it gets queued
      #if ENABLED(KP3S_SMART_UI)
        kp3s_feedback_sound(KP3SFeedback::DONE);
        #if HAS_BACKLIGHT_TIMEOUT
          ui.refresh_backlight_timeout();
        #endif
      #endif
      marlin_state = MarlinState::MF_RUNNING; // Signal to stop trying
""",
        "Add completion beep and restore backlight",
    )

    replace_once(
        ui_cpp,
        """  void MarlinUI::refresh_backlight_timeout() {
    backlight_off_ms = backlight_timeout_minutes ? millis() + MIN_TO_MS(backlight_timeout_minutes) : 0;
""",
        """  void MarlinUI::refresh_backlight_timeout() {
    // V1: the normal inactivity timer remains active in idle, pause and print states.
    backlight_off_ms = backlight_timeout_minutes ? millis() + MIN_TO_MS(backlight_timeout_minutes) : 0;
""",
        "Keep one consistent backlight timeout in every machine state",
    )

    replace_once(
        ui_cpp,
        """    #elif PIN_EXISTS(LCD_BACKLIGHT)
      WRITE(LCD_BACKLIGHT_PIN, HIGH);
    #endif
  }

#elif HAS_DISPLAY_SLEEP""",
        """    #elif PIN_EXISTS(LCD_BACKLIGHT)
      #if ENABLED(KP3S_SMART_UI)
        WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_ON_STATE);
      #else
        WRITE(LCD_BACKLIGHT_PIN, HIGH);
      #endif
    #endif
  }

#elif HAS_DISPLAY_SLEEP""",
        "Apply configured backlight polarity",
    )

    replace_once(
        ui_cpp,
        """          #elif PIN_EXISTS(LCD_BACKLIGHT)
            WRITE(LCD_BACKLIGHT_PIN, LOW); // Backlight off
          #endif""",
        """          #elif PIN_EXISTS(LCD_BACKLIGHT)
            #if ENABLED(KP3S_SMART_UI)
              WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_OFF_STATE);
            #else
              WRITE(LCD_BACKLIGHT_PIN, LOW); // Backlight off
            #endif
          #endif""",
        "Apply configured polarity when turning off backlight",
    )

    replace_once(
        ui_cpp,
        """  init_lcd();
  clear_lcd();
""",
        """  init_lcd();
  clear_lcd();

  #if ENABLED(KP3S_UE5000)
    kp3s_ue5000_init();
  #endif

  #if ENABLED(KP3S_SMART_UI) && PIN_EXISTS(LCD_BACKLIGHT)
    // V1 boots ready for use. Standby is an explicit 5-second idle gesture.
    OUT_WRITE(LCD_BACKLIGHT_PIN, KP3S_BACKLIGHT_ON_STATE);
    #if HAS_BACKLIGHT_TIMEOUT
      refresh_backlight_timeout();
    #endif
  #endif
""",
        "Inicializar backlight e painel UE5000",
    )

    regex_once(
        ui_cpp,
        r'^[ \t]+chirp\(\);[ \t]*//[ \t]*Buzz and wait\. Is the delay needed for buttons to settle\?[ \t]*$',
        """    #if ENABLED(KP3S_SMART_UI)
      kp3s_feedback_sound(KP3SFeedback::SELECT);
      #if HAS_BACKLIGHT_TIMEOUT
        refresh_backlight_timeout();
      #endif
    #else
      chirp();  // Buzz and wait. Is the delay needed for buttons to settle?
    #endif""",
        "Add distinct confirmation / click feedback",
    )

    replace_once(
        ui_cpp,
        """    draw_kill_screen();
  }

  void MarlinUI::quick_feedback""",
        """    #if ENABLED(KP3S_SMART_UI)
      kp3s_feedback_sound(KP3SFeedback::ERROR);
    #endif
    #if ENABLED(KP3S_UE5000)
      kp3s_ue5000_error();
    #endif
    draw_kill_screen();
  }

  void MarlinUI::quick_feedback""",
        "Add error-screen alarm feedback",
    )

    replace_once(
        m24m25,
        """#include "../../MarlinCore.h" // for startOrResumeJob
""",
        """#include "../../MarlinCore.h" // for startOrResumeJob
#if ENABLED(KP3S_SMART_UI)
  #include "../../feature/kp3s_feedback.h"
#endif
""",
        "Incluir feedback V1 no pause/resume SD",
    )

    replace_once(
        m24m25,
        """void GcodeSuite::M25() {

""",
        """void GcodeSuite::M25() {

  #if ENABLED(KP3S_SMART_UI)
    kp3s_feedback_sound(KP3SFeedback::PAUSE);
  #endif

""",
        "Bip de pausa para qualquer modo de pause",
    )

    # V6: low-level self-test independent of U8glib / MarlinUI.
    # If this pattern does not appear, the fault is below the menu-rendering layer.
    replace_once(
        marlin_core,
        "void setup() {",
        """#if ENABLED(NOKIA5110_RAW_DIAG)

static inline void nokia5110_raw_byte(const uint8_t value, const bool is_data) {
  WRITE(DOGLCD_CS, LOW);
  WRITE(DOGLCD_A0, is_data ? HIGH : LOW);
  for (uint8_t mask = 0x80; mask; mask >>= 1) {
    WRITE(DOGLCD_SCK, LOW);
    WRITE(DOGLCD_MOSI, (value & mask) ? HIGH : LOW);
    DELAY_US(3);
    WRITE(DOGLCD_SCK, HIGH);
    DELAY_US(3);
  }
  WRITE(DOGLCD_CS, HIGH);
}

static inline void nokia5110_raw_cmd(const uint8_t value) { nokia5110_raw_byte(value, false); }
static inline void nokia5110_raw_data(const uint8_t value) { nokia5110_raw_byte(value, true); }

static void nokia5110_raw_fill(const uint8_t a, const uint8_t b) {
  nokia5110_raw_cmd(0x40); // Y = 0
  nokia5110_raw_cmd(0x80); // X = 0
  for (uint16_t i = 0; i < 504; ++i)
    nokia5110_raw_data((i & 1) ? b : a);
}

static void nokia5110_raw_set_vop(const uint8_t vop) {
  nokia5110_raw_cmd(0x21);
  nokia5110_raw_cmd(0x80 | (vop & 0x7F));
  nokia5110_raw_cmd(0x06);
  nokia5110_raw_cmd(0x13);
  nokia5110_raw_cmd(0x20);
  nokia5110_raw_cmd(0x0C);
}

static void nokia5110_diag_beep() {
  #if HAS_BEEPER
    SET_OUTPUT(BEEPER_PIN);
    for (uint8_t n = 0; n < 3; ++n) {
      for (uint16_t i = 0; i < 180; ++i) {
        WRITE(BEEPER_PIN, HIGH); DELAY_US(250);
        WRITE(BEEPER_PIN, LOW);  DELAY_US(250);
      }
      delay(110);
    }
  #endif
}

static void nokia5110_raw_selftest() {
  SET_OUTPUT(DOGLCD_SCK);
  SET_OUTPUT(DOGLCD_MOSI);
  SET_OUTPUT(DOGLCD_CS);
  SET_OUTPUT(DOGLCD_A0);
  SET_OUTPUT(LCD_RESET_PIN);

  WRITE(DOGLCD_SCK, LOW);
  WRITE(DOGLCD_MOSI, LOW);
  WRITE(DOGLCD_CS, HIGH);
  WRITE(DOGLCD_A0, LOW);
  WRITE(LCD_RESET_PIN, HIGH);

  nokia5110_diag_beep();

  WRITE(LCD_RESET_PIN, LOW);
  delay(20);
  WRITE(LCD_RESET_PIN, HIGH);
  delay(50);

  nokia5110_raw_set_vop(0x30);
  nokia5110_raw_fill(0xFF, 0xFF);
  delay(1200);

  nokia5110_raw_set_vop(0x40);
  nokia5110_raw_fill(0xAA, 0x55);
  delay(1500);

  nokia5110_raw_set_vop(0x50);
  nokia5110_raw_fill(0xF0, 0x0F);
  delay(1500);

  nokia5110_raw_fill(0x00, 0x00);
  delay(200);
}

#endif // NOKIA5110_RAW_DIAG

void setup() {""",
        "Add optional PCD8544 RAW self-test",
    )

    replace_once(
        marlin_core,
        """  #if ENABLED(SOVOL_SV06_RTS)
    SETUP_RUN(RTS_Update());
  #else
    SETUP_RUN(ui.init());
  #endif
""",
        """  #if ENABLED(SOVOL_SV06_RTS)
    SETUP_RUN(RTS_Update());
  #else
    SETUP_RUN(ui.init());
  #endif

  #if ENABLED(KP3S_SMART_UI)
    kp3s_feedback_sound(KP3SFeedback::BOOT);
  #endif
""",
        "Add startup feedback",
    )

    replace_once(
        marlin_core,
        """  // UI must be initialized before EEPROM
  // (because EEPROM code calls the UI).
  #if ENABLED(SOVOL_SV06_RTS)""",
        """  #if ENABLED(NOKIA5110_RAW_DIAG)
    nokia5110_raw_selftest();
  #endif

  // UI must be initialized before EEPROM
  // (because EEPROM code calls the UI).
  #if ENABLED(SOVOL_SV06_RTS)""",
        "Run RAW LCD self-test before MarlinUI",
    )

    replace_once(
        marlin_core,
        "    queue.advance();\n",
        """    #if ENABLED(KP3S_UE5000_SOFT_POWER)
      // Standby is an interface state, never a data-loss state. Any queued
      // command wakes the UI and is then processed normally.
      if (!kp3s_ue5000_is_awake() && queue.has_commands_queued())
        kp3s_ue5000_wake();
      if (kp3s_ue5000_is_awake()) queue.advance();
    #else
      queue.advance();
    #endif
""",
        "Wake logical standby before processing queued G-code",
    )

    replace_once(
        status_cpp,
        "#if HAS_MARLINUI_U8GLIB && DISABLED(LIGHTWEIGHT_UI)",
        "#if HAS_MARLINUI_U8GLIB && DISABLED(LIGHTWEIGHT_UI) && DISABLED(NOKIA5110_LCD)",
        "Disable 128x64 status screen for Nokia",
    )

    feedback_h.write_text(
        r"""/**
 * KP3S Marlin Firmware - non-blocking audio feedback for the PC5 buzzer.
 */
#pragma once

#include "../inc/MarlinConfig.h"

#if ENABLED(KP3S_SMART_UI)

#include "../libs/buzzer.h"

enum class KP3SFeedback : uint8_t {
  BOOT, NAV, SELECT, BACK, PRINT_START, PAUSE, RESUME, DONE, ABORT, ERROR
};

inline void kp3s_feedback_sound(const KP3SFeedback event) {
  #if HAS_BEEPER
    switch (event) {
      case KP3SFeedback::BOOT:
        BUZZ(45, 1100); BUZZ(30, 0); BUZZ(45, 1550); BUZZ(30, 0); BUZZ(80, 2200);
        break;
      case KP3SFeedback::NAV:
        BUZZ(8, 2300);
        break;
      case KP3SFeedback::SELECT:
        BUZZ(30, 1750); BUZZ(25, 0); BUZZ(55, 2550);
        break;
      case KP3SFeedback::BACK:
        BUZZ(70, 950);
        break;
      case KP3SFeedback::PRINT_START:
        BUZZ(50, 1200); BUZZ(25, 0); BUZZ(50, 1650); BUZZ(25, 0); BUZZ(90, 2150);
        break;
      case KP3SFeedback::PAUSE:
        BUZZ(90, 900); BUZZ(80, 0); BUZZ(90, 900);
        break;
      case KP3SFeedback::RESUME:
        BUZZ(50, 1350); BUZZ(35, 0); BUZZ(95, 1950);
        break;
      case KP3SFeedback::DONE:
        BUZZ(70, 1550); BUZZ(40, 0); BUZZ(70, 1950); BUZZ(40, 0); BUZZ(150, 2550);
        break;
      case KP3SFeedback::ABORT:
        BUZZ(130, 850); BUZZ(60, 0); BUZZ(220, 520);
        break;
      case KP3SFeedback::ERROR:
        BUZZ(160, 650); BUZZ(70, 0); BUZZ(160, 480); BUZZ(70, 0); BUZZ(300, 320);
        break;
    }
  #else
    (void)event;
  #endif
}

#endif // KP3S_SMART_UI
""",
        encoding="utf-8",
    )
    print("[OK] Create non-blocking audio feedback")

    ue5000_h.write_text(
        r'''/**
 * KP3S Marlin Firmware - Samsung BN41-01840B / BN96-22413B control board.
 * Resistive JOG + IR receiver + status LED.
 */
#pragma once

#include "../inc/MarlinConfig.h"

#if ENABLED(KP3S_UE5000)

enum class KP3SUE5000Action : uint8_t {
  NONE, UP, DOWN, LEFT, RIGHT, ENTER, BACK, MENU, STATUS, PAUSE, RESUME
};

enum class KP3SUE5000PowerEvent : uint8_t { NONE, WOKE, SLEPT };

void kp3s_ue5000_init();
bool kp3s_ue5000_is_awake();
void kp3s_ue5000_wake(const millis_t now=millis());
KP3SUE5000PowerEvent kp3s_ue5000_power_task(const millis_t now, const bool allow_standby);
KP3SUE5000Action kp3s_ue5000_poll(const millis_t now);
void kp3s_ue5000_activity(const millis_t now=millis());
void kp3s_ue5000_led_task(const millis_t now, const bool printing, const bool paused);
void kp3s_ue5000_error();

#endif
''',
        encoding="utf-8",
    )

    ue5000_impl_h.write_text(
        r'''/**
 * KP3S Marlin Firmware Samsung control-board implementation over the original FFC.
 *
 * KEY1: FFC10 / PE10, digital input with internal pull-up.
 * KEY2: FFC13 / PE13, non-blocking RC discharge-time measurement.
 *        Hardware: KEY2 -- 1k -- PE13; 100 nF from PE13 to GND.
 * IR:   FFC7 / PE7, Samsung IR receiver.
 * LED:  FFC18 / PD10, status LED.
 *
 * PE13/EXTI13 and PE7/EXTI7 avoid EXTI lines used by the KP3S endstops.
 *
 * This implementation header is included by Marlin/src/lcd/marlinui.cpp so
 * it remains inside a source file compiled by Marlin's build_src_filter.
 */
#pragma once

#include "../inc/MarlinConfig.h"
#include "../HAL/shared/Delay.h"  // V1: define DELAY_US used by the RC charge pulse

#if ENABLED(KP3S_UE5000)

#include "kp3s_ue5000.h"

static volatile uint32_t ue_ir_last_edge_us = 0;
static volatile uint32_t ue_ir_code = 0;
static volatile bool ue_ir_ready = false;
static volatile bool ue_ir_repeat_ready = false;
static volatile bool ue_ir_header_mark = false;
static volatile bool ue_ir_receiving = false;
static volatile uint8_t ue_ir_bit = 0;
static volatile uint8_t ue_ir_bytes[4] = { 0, 0, 0, 0 };

static volatile uint32_t ue_rc_started_us = 0;
static volatile uint16_t ue_rc_value_us = KP3S_UE5000_RC_TIMEOUT_US;
static volatile bool ue_rc_measuring = false;
static volatile bool ue_rc_ready = false;

// Adaptive idle baseline prevents phantom KEY2 events.
static uint16_t ue_rc_baseline_us = 0;
static uint16_t ue_rc_cal_values[KP3S_UE5000_RC_CAL_SAMPLES];
static uint8_t ue_rc_cal_count = 0;
static uint8_t ue_rc_rebase_count = 0;
static uint16_t ue_rc_rebase_value = 0;
static bool ue_rc_armed = false;

static millis_t ue_boot_until = 0, ue_activity_until = 0;
static bool ue_error_latched = false, ue_led_state = false;
static bool ue_power_awake = true;
static bool ue_external_wake_pending = false;
static bool ue_power_holding = false;
static bool ue_power_ignore_key1_until_release = false;
static bool ue_key1_click_ready = false;
static millis_t ue_power_hold_started = 0;

static inline bool ue_between_us(const uint32_t v, const uint32_t lo, const uint32_t hi) {
  return v >= lo && v <= hi;
}

static uint16_t ue_median_calibration() {
  uint16_t v[KP3S_UE5000_RC_CAL_SAMPLES];
  for (uint8_t i = 0; i < ue_rc_cal_count; ++i) v[i] = ue_rc_cal_values[i];
  for (uint8_t i = 1; i < ue_rc_cal_count; ++i) {
    const uint16_t key = v[i];
    int8_t j = int8_t(i) - 1;
    while (j >= 0 && v[j] > key) { v[j + 1] = v[j]; --j; }
    v[j + 1] = key;
  }
  return ue_rc_cal_count ? v[ue_rc_cal_count >> 1] : KP3S_UE5000_RC_TIMEOUT_US;
}

static uint16_t ue_neutral_cutoff_us() {
  if (!ue_rc_baseline_us) return KP3S_UE5000_RC_TIMEOUT_US;
  uint16_t delta = uint16_t((uint32_t(ue_rc_baseline_us) * (100U - KP3S_UE5000_RC_NEUTRAL_PCT)) / 100U);
  if (delta < KP3S_UE5000_RC_NEUTRAL_MARGIN_US) delta = KP3S_UE5000_RC_NEUTRAL_MARGIN_US;
  return ue_rc_baseline_us > delta ? uint16_t(ue_rc_baseline_us - delta) : 0;
}

static void ue_consider_rebase(const uint16_t rc_us) {
  if (!ue_rc_baseline_us) return;
  const uint16_t rise = uint16_t(_MAX(uint16_t(KP3S_UE5000_RC_NEUTRAL_MARGIN_US), uint16_t(ue_rc_baseline_us >> 4)));
  if (rc_us <= uint16_t(_MIN(uint32_t(0xFFFF), uint32_t(ue_rc_baseline_us) + rise))) {
    ue_rc_rebase_count = 0;
    return;
  }

  const uint16_t tol = uint16_t(_MAX(uint16_t(120), uint16_t(rc_us >> 4)));
  const uint16_t diff = rc_us > ue_rc_rebase_value ? rc_us - ue_rc_rebase_value : ue_rc_rebase_value - rc_us;
  if (!ue_rc_rebase_count || diff <= tol) {
    ue_rc_rebase_value = rc_us;
    if (ue_rc_rebase_count < KP3S_UE5000_RC_REBASE_SAMPLES) ++ue_rc_rebase_count;
  }
  else {
    ue_rc_rebase_value = rc_us;
    ue_rc_rebase_count = 1;
  }

  if (ue_rc_rebase_count >= KP3S_UE5000_RC_REBASE_SAMPLES) {
    ue_rc_baseline_us = ue_rc_rebase_value;
    ue_rc_rebase_count = 0;
    ue_rc_armed = false;
  }
}

static void kp3s_ue5000_key2_isr() {
  if (!ue_rc_measuring) return;
  uint32_t dt = micros() - ue_rc_started_us;
  if (dt > 0xFFFFUL) dt = 0xFFFFUL;
  ue_rc_value_us = uint16_t(dt);
  ue_rc_measuring = false;
  ue_rc_ready = true;
}

static void ue_key2_rc_start() {
  if (ue_rc_measuring || ue_rc_ready) return;

  SET_OUTPUT(KP3S_UE5000_KEY2_PIN);
  WRITE(KP3S_UE5000_KEY2_PIN, HIGH);
  DELAY_US(500);

  ue_rc_started_us = micros();
  ue_rc_measuring = true;
  SET_INPUT(KP3S_UE5000_KEY2_PIN);

  if (!READ(KP3S_UE5000_KEY2_PIN) && ue_rc_measuring) {
    uint32_t dt = micros() - ue_rc_started_us;
    if (dt > 0xFFFFUL) dt = 0xFFFFUL;
    ue_rc_value_us = uint16_t(dt);
    ue_rc_measuring = false;
    ue_rc_ready = true;
  }
}

static void ue_key2_rc_timeout_service() {
  if (!ue_rc_measuring) return;
  if ((micros() - ue_rc_started_us) < uint32_t(KP3S_UE5000_RC_TIMEOUT_US)) return;

  noInterrupts();
  if (ue_rc_measuring) {
    ue_rc_value_us = KP3S_UE5000_RC_TIMEOUT_US;
    ue_rc_measuring = false;
    ue_rc_ready = true;
  }
  interrupts();
}

static bool ue_key2_rc_take(uint16_t &value) {
  bool ready;
  noInterrupts();
  ready = ue_rc_ready;
  if (ready) {
    value = ue_rc_value_us;
    ue_rc_ready = false;
  }
  interrupts();
  return ready;
}

static void kp3s_ue5000_ir_isr() {
  const uint32_t now = micros();
  const uint32_t dt = now - ue_ir_last_edge_us;
  ue_ir_last_edge_us = now;
  const bool level_high = READ(KP3S_UE5000_IR_PIN);

  if (level_high) {
    if (ue_between_us(dt, 3500, 5500)) {
      ue_ir_header_mark = true;
      ue_ir_receiving = false;
      ue_ir_bit = 0;
    }
    else if (ue_ir_receiving && !ue_between_us(dt, 300, 900)) {
      ue_ir_receiving = false;
      ue_ir_bit = 0;
    }
    return;
  }

  if (ue_ir_header_mark) {
    ue_ir_header_mark = false;
    if (ue_between_us(dt, 3500, 5500)) {
      ue_ir_receiving = true;
      ue_ir_bit = 0;
      ue_ir_bytes[0] = ue_ir_bytes[1] = ue_ir_bytes[2] = ue_ir_bytes[3] = 0;
    }
    else if (ue_between_us(dt, 1800, 2800)) {
      ue_ir_repeat_ready = true;
      ue_ir_receiving = false;
      ue_ir_bit = 0;
    }
    return;
  }

  if (!ue_ir_receiving) return;

  bool one;
  if (ue_between_us(dt, 300, 900)) one = false;
  else if (ue_between_us(dt, 1100, 2200)) one = true;
  else {
    ue_ir_receiving = false;
    ue_ir_bit = 0;
    return;
  }

  if (one) ue_ir_bytes[ue_ir_bit >> 3] |= uint8_t(1U << (ue_ir_bit & 7));
  if (++ue_ir_bit >= 32) {
    ue_ir_code = (uint32_t(ue_ir_bytes[0]) << 24)
               | (uint32_t(ue_ir_bytes[1]) << 16)
               | (uint32_t(ue_ir_bytes[2]) << 8)
               |  uint32_t(ue_ir_bytes[3]);
    ue_ir_ready = true;
    ue_ir_receiving = false;
    ue_ir_bit = 0;
  }
}

static inline void ue_led_write(const bool on) {
  if (on == ue_led_state) return;
  ue_led_state = on;
  WRITE(KP3S_UE5000_LED_PIN, on ? KP3S_UE5000_LED_ON_STATE : KP3S_UE5000_LED_OFF_STATE);
}

static KP3SUE5000Action ue_rotate(KP3SUE5000Action a) {
  // KEY2 is classified directly by the measured physical directions.
  // measured on this project hardware. Do not apply L/R mirroring here.

  #if KP3S_UE5000_ROTATION == 90
    switch (a) {
      case KP3SUE5000Action::UP:    return KP3SUE5000Action::RIGHT;
      case KP3SUE5000Action::RIGHT: return KP3SUE5000Action::DOWN;
      case KP3SUE5000Action::DOWN:  return KP3SUE5000Action::LEFT;
      case KP3SUE5000Action::LEFT:  return KP3SUE5000Action::UP;
      default: return a;
    }
  #elif KP3S_UE5000_ROTATION == 180
    switch (a) {
      case KP3SUE5000Action::UP:    return KP3SUE5000Action::DOWN;
      case KP3SUE5000Action::DOWN:  return KP3SUE5000Action::UP;
      case KP3SUE5000Action::LEFT:  return KP3SUE5000Action::RIGHT;
      case KP3SUE5000Action::RIGHT: return KP3SUE5000Action::LEFT;
      default: return a;
    }
  #elif KP3S_UE5000_ROTATION == 270
    switch (a) {
      case KP3SUE5000Action::UP:    return KP3SUE5000Action::LEFT;
      case KP3SUE5000Action::LEFT:  return KP3SUE5000Action::DOWN;
      case KP3SUE5000Action::DOWN:  return KP3SUE5000Action::RIGHT;
      case KP3SUE5000Action::RIGHT: return KP3SUE5000Action::UP;
      default: return a;
    }
  #else
    return a;
  #endif
}

static KP3SUE5000Action ue_ir_to_action(const uint32_t code) {
  switch (code) {
    case 0xE0E006F9UL: return KP3SUE5000Action::UP;
    case 0xE0E08679UL: return KP3SUE5000Action::DOWN;
    case 0xE0E0A659UL: return KP3SUE5000Action::LEFT;
    case 0xE0E046B9UL: return KP3SUE5000Action::RIGHT;
    case 0xE0E016E9UL: return KP3SUE5000Action::ENTER;
    case 0xE0E01AE5UL: return KP3SUE5000Action::BACK;
    case 0xE0E058A7UL: return KP3SUE5000Action::MENU;
    case 0xE0E0B44BUL: return KP3SUE5000Action::STATUS;
    case 0xE0E0F807UL: return KP3SUE5000Action::STATUS;
    case 0xE0E052ADUL: return KP3SUE5000Action::PAUSE;
    case 0xE0E0E21DUL: return KP3SUE5000Action::RESUME;
    case 0xE0E0629DUL: return KP3SUE5000Action::STATUS;
    case 0xE0E040BFUL: return KP3SUE5000Action::STATUS;
    default: return KP3SUE5000Action::NONE;
  }
}

void kp3s_ue5000_init() {
  SET_INPUT_PULLUP(KP3S_UE5000_KEY1_PIN);
  SET_INPUT(KP3S_UE5000_KEY2_PIN);
  SET_INPUT_PULLUP(KP3S_UE5000_IR_PIN);

  // V1 always boots awake. A 5-second KEY1 hold toggles logical standby
  // only while the printer is idle; the same hold wakes it again.
  OUT_WRITE(KP3S_UE5000_LED_PIN, KP3S_UE5000_LED_OFF_STATE);
  ue_led_state = false;
  ue_power_awake = true;
  ue_external_wake_pending = false;
  ue_power_holding = false;
  ue_power_ignore_key1_until_release = false;
  ue_key1_click_ready = false;
  ue_power_hold_started = 0;
  ue_boot_until = millis() + 900;

  ue_activity_until = 0;
  ue_error_latched = false;
  ue_ir_last_edge_us = micros();
  ue_rc_baseline_us = 0;
  ue_rc_cal_count = 0;
  ue_rc_rebase_count = 0;
  ue_rc_rebase_value = 0;
  ue_rc_armed = false;

  attachInterrupt(digitalPinToInterrupt(KP3S_UE5000_IR_PIN), kp3s_ue5000_ir_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(KP3S_UE5000_KEY2_PIN), kp3s_ue5000_key2_isr, FALLING);
}

bool kp3s_ue5000_is_awake() {
  return ue_power_awake;
}

void kp3s_ue5000_wake(const millis_t now) {
  #if ENABLED(KP3S_UE5000_SOFT_POWER)
    if (ue_power_awake) return;
    ue_power_awake = true;
    ue_external_wake_pending = true;
    ue_boot_until = now + 900;
    ue_activity_until = 0;
    ue_rc_baseline_us = 0;
    ue_rc_cal_count = 0;
    ue_rc_rebase_count = 0;
    ue_rc_rebase_value = 0;
    ue_rc_armed = false;
    noInterrupts();
    ue_rc_measuring = false;
    ue_rc_ready = false;
    interrupts();
  #else
    (void)now;
  #endif
}

KP3SUE5000PowerEvent kp3s_ue5000_power_task(const millis_t now, const bool allow_standby) {
  #if DISABLED(KP3S_UE5000_SOFT_POWER)
    (void)now;
    (void)allow_standby;
    return KP3SUE5000PowerEvent::NONE;
  #else
    if (ue_external_wake_pending) {
      ue_external_wake_pending = false;
      return KP3SUE5000PowerEvent::WOKE;
    }
    const bool key1_pressed = !READ(KP3S_UE5000_KEY1_PIN);

    // Ignore the physical release after a long-press transition so it can never
    // turn into a synthetic ENTER event on the next UI scan.
    if (ue_power_ignore_key1_until_release) {
      if (!key1_pressed) ue_power_ignore_key1_until_release = false;
      return KP3SUE5000PowerEvent::NONE;
    }

    if (key1_pressed) {
      if (!ue_power_holding) {
        ue_power_holding = true;
        ue_power_hold_started = now;
        ue_key1_click_ready = false;
      }
      else if (ELAPSED(now, ue_power_hold_started + KP3S_UE5000_POWER_HOLD_MS)) {
        ue_power_holding = false;
        ue_power_hold_started = 0;
        ue_power_ignore_key1_until_release = true;
        ue_key1_click_ready = false;

        if (!ue_power_awake) {
          kp3s_ue5000_wake(now);
          ue_external_wake_pending = false;
          return KP3SUE5000PowerEvent::WOKE;
        }

        // Enter standby only when the caller confirms that the machine is fully idle.
        // A blocked long press is deliberately consumed instead of becoming ENTER.
        if (allow_standby) {
          ue_power_awake = false;
          ue_activity_until = 0;
          noInterrupts();
          ue_rc_measuring = false;
          ue_rc_ready = false;
          interrupts();
          ue_led_write(true);
          return KP3SUE5000PowerEvent::SLEPT;
        }
      }
    }
    else if (ue_power_holding) {
      // A short KEY1 press is delivered only on release. This makes the 5-second
      // power gesture unambiguous and prevents an ENTER before standby is decided.
      ue_power_holding = false;
      ue_power_hold_started = 0;
      if (ue_power_awake) ue_key1_click_ready = true;
    }

    if (!ue_power_awake) ue_led_write(true);
    return KP3SUE5000PowerEvent::NONE;
  #endif
}

void kp3s_ue5000_activity(const millis_t now) { ue_activity_until = now + 90; }
void kp3s_ue5000_error() { ue_error_latched = true; }

void kp3s_ue5000_led_task(const millis_t now, const bool printing, const bool paused) {
  #if ENABLED(KP3S_UE5000_SOFT_POWER)
    if (!ue_power_awake) {
      ue_led_write(true);
      return;
    }
  #endif

  bool on;
  if (ue_error_latched)
    on = ((now / 140) & 1U) == 0;
  else if (PENDING(now, ue_boot_until))
    on = ((now / 120) & 1U) == 0;
  else if (paused) {
    const uint16_t phase = uint16_t(now % 1200UL);
    on = phase < 120 || (phase >= 240 && phase < 360);
  }
  else if (printing)
    on = (now % 1400UL) < 100;
  else
    on = true;

  if (PENDING(now, ue_activity_until)) on = !on;
  ue_led_write(on);
}

static KP3SUE5000Action ue_classify_rc(const uint16_t rc_us) {
  // First recognize the learned idle state. Timeout is always treated as neutral.
  if (!ue_rc_baseline_us) return KP3SUE5000Action::NONE;
  if (rc_us >= uint16_t(KP3S_UE5000_RC_TIMEOUT_US - 20U)) return KP3SUE5000Action::NONE;
  if (rc_us >= ue_neutral_cutoff_us()) return KP3SUE5000Action::NONE;

  // Corrected from direct hardware testing.
  // Measured behavior showed the two vertical RC windows were swapped.
  // Therefore the first two RC windows map to DOWN and UP, in that order.
  if (rc_us < KP3S_UE5000_RC_DOWN_MAX_US)     return KP3SUE5000Action::DOWN;
  if (rc_us < KP3S_UE5000_RC_UP_MAX_US)       return KP3SUE5000Action::UP;
  if (rc_us < KP3S_UE5000_RC_RIGHT_MAX_US)    return KP3SUE5000Action::RIGHT;
  if (rc_us < KP3S_UE5000_RC_LEFT_MAX_US)     return KP3SUE5000Action::LEFT;
  return KP3SUE5000Action::NONE;
}

KP3SUE5000Action kp3s_ue5000_poll(const millis_t now) {
  #if ENABLED(KP3S_UE5000_SOFT_POWER)
    if (!ue_power_awake) return KP3SUE5000Action::NONE;
    if (ue_power_ignore_key1_until_release) {
      if (READ(KP3S_UE5000_KEY1_PIN))
        ue_power_ignore_key1_until_release = false;
      else
        return KP3SUE5000Action::NONE;
    }
  #endif

  // KEY1 / CENTER is a discrete release event, not an RC level. It MUST bypass
  // the two-sample JOG debounce below. Requiring two samples here made every
  // generic Marlin edit screen impossible to accept because a short CENTER
  // release existed for exactly one poll. This atomic ENTER is consumed once
  // and reaches ui.use_click() independently of directional hold state.
  if (ue_key1_click_ready) {
    ue_key1_click_ready = false;
    return KP3SUE5000Action::ENTER;
  }

  static KP3SUE5000Action last_ir_action = KP3SUE5000Action::NONE;
  static millis_t last_ir_at = 0;

  // IR input remains independent from the JOG / RC decoder.
  if (ue_ir_repeat_ready) {
    noInterrupts(); ue_ir_repeat_ready = false; interrupts();
    if (ELAPSED(now, last_ir_at + 95) &&
        (last_ir_action == KP3SUE5000Action::UP || last_ir_action == KP3SUE5000Action::DOWN ||
         last_ir_action == KP3SUE5000Action::LEFT || last_ir_action == KP3SUE5000Action::RIGHT)) {
      last_ir_at = now;
      return last_ir_action;
    }
  }

  if (ue_ir_ready) {
    uint32_t code;
    noInterrupts(); code = ue_ir_code; ue_ir_ready = false; interrupts();
    const KP3SUE5000Action ia = ue_ir_to_action(code);
    #if ENABLED(KP3S_UE5000_DEBUG)
      SERIAL_ECHOPGM("UE5000 IR=0x"); SERIAL_PRINT(code, HEX); SERIAL_EOL();
    #endif
    if (ia != KP3SUE5000Action::NONE) {
      last_ir_action = ia;
      last_ir_at = now;
      return ia;
    }
  }

  ue_key2_rc_timeout_service();

  static millis_t next_sample = 0, repeat_at = 0, hold_started = 0, debug_at = 0;
  static KP3SUE5000Action last_candidate = KP3SUE5000Action::NONE;
  static KP3SUE5000Action stable = KP3SUE5000Action::NONE;
  static uint8_t same_count = 0, neutral_count = 0;
  static bool need_release = false;

  KP3SUE5000Action candidate = KP3SUE5000Action::NONE;
  bool have_candidate = false;
  uint16_t rc_us = KP3S_UE5000_RC_TIMEOUT_US;

  if (ue_key2_rc_take(rc_us)) {
    // Startup cycles learn the real idle RC value of KEY2 + 1k + 100nF.
    if (ue_rc_cal_count < KP3S_UE5000_RC_CAL_SAMPLES) {
      ue_rc_cal_values[ue_rc_cal_count++] = rc_us;
      if (ue_rc_cal_count >= KP3S_UE5000_RC_CAL_SAMPLES) {
        ue_rc_baseline_us = ue_median_calibration();
        ue_rc_armed = false;
        neutral_count = 0;
        stable = last_candidate = KP3SUE5000Action::NONE;
        same_count = 0;
        need_release = false;
      }
      #if ENABLED(KP3S_UE5000_DEBUG)
        SERIAL_ECHOPGM("UE5000 CAL "); SERIAL_ECHO(ue_rc_cal_count);
        SERIAL_ECHOPGM("/"); SERIAL_ECHO(KP3S_UE5000_RC_CAL_SAMPLES);
        SERIAL_ECHOPGM(" RCus="); SERIAL_ECHOLN(rc_us);
      #endif
      return KP3SUE5000Action::NONE;
    }

    // If the true idle level rises above the learned baseline, accept a rebase
    // only after several consecutive samples. A single timeout never recalibrates.
    ue_consider_rebase(rc_us);
    candidate = ue_classify_rc(rc_us);
    have_candidate = true;
  }

  if (!have_candidate && !ue_rc_measuring && PENDING(now, next_sample))
    return KP3SUE5000Action::NONE;

  if (!have_candidate && !ue_rc_measuring && ELAPSED(now, next_sample)) {
    next_sample = now + 40;
    ue_key2_rc_start();
    return KP3SUE5000Action::NONE;
  }

  if (!have_candidate) return KP3SUE5000Action::NONE;

  candidate = ue_rotate(candidate);

  #if ENABLED(KP3S_UE5000_DEBUG)
    if (ELAPSED(now, debug_at)) {
      debug_at = now + 350;
      SERIAL_ECHOPGM("UE5000 KEY1="); SERIAL_ECHO(READ(KP3S_UE5000_KEY1_PIN));
      SERIAL_ECHOPGM(" RCus="); SERIAL_ECHO(rc_us);
      SERIAL_ECHOPGM(" BASE="); SERIAL_ECHO(ue_rc_baseline_us);
      SERIAL_ECHOPGM(" Ncut="); SERIAL_ECHO(ue_neutral_cutoff_us());
      SERIAL_ECHOPGM(" ARMED="); SERIAL_ECHOLN(ue_rc_armed ? 1 : 0);
    }
  #else
    (void)debug_at;
  #endif

  // Explicit neutral state. Three neutral samples arm / re-arm the JOG.
  if (candidate == KP3SUE5000Action::NONE) {
    if (neutral_count < KP3S_UE5000_RC_RELEASE_SAMPLES) ++neutral_count;
    if (neutral_count >= KP3S_UE5000_RC_RELEASE_SAMPLES) {
      ue_rc_armed = true;
      stable = KP3SUE5000Action::NONE;
      last_candidate = KP3SUE5000Action::NONE;
      same_count = 0;
      repeat_at = 0;
      hold_started = 0;
      need_release = false;
    }
    return KP3SUE5000Action::NONE;
  }

  neutral_count = 0;

  // Until a reliable idle state is observed, KEY2 produces no command.
  // KEY1 also respects re-arming to avoid a phantom ENTER at boot.
  if (!ue_rc_armed) return KP3SUE5000Action::NONE;

  // Directional holds auto-repeat on all four directions. The repeat cadence
  // accelerates with hold time so LEFT/RIGHT behave exactly like UP/DOWN.
  if (need_release) {
    const bool directional = stable == KP3SUE5000Action::UP || stable == KP3SUE5000Action::DOWN
                          || stable == KP3SUE5000Action::LEFT || stable == KP3SUE5000Action::RIGHT;
    if (directional && candidate == stable && repeat_at && ELAPSED(now, repeat_at)) {
      const millis_t held_ms = now - hold_started;
      const millis_t repeat_ms = held_ms >= 2500 ? 45 : held_ms >= 1000 ? 75 : 110;
      repeat_at = now + repeat_ms;
      return stable;
    }
    return KP3SUE5000Action::NONE;
  }

  if (candidate == last_candidate) {
    if (same_count < 3) ++same_count;
  }
  else {
    last_candidate = candidate;
    same_count = 1;
  }

  if (same_count >= 2) {
    stable = candidate;
    need_release = true;
    hold_started = now;
    const bool directional = stable == KP3SUE5000Action::UP || stable == KP3SUE5000Action::DOWN
                          || stable == KP3SUE5000Action::LEFT || stable == KP3SUE5000Action::RIGHT;
    repeat_at = directional ? now + 320 : 0;
    return stable;
  }

  return KP3SUE5000Action::NONE;
}

#endif // KP3S_UE5000
''',
        encoding="utf-8",
    )
    print("[OK] Create Samsung control-board driver: FFC + RC 1k/100nF + IR + LED")

    mpu6050_h.write_text(
        r'''/**
 * KP3S Marlin Firmware V1 - MPU6050 / IMU runtime interface.
 */
#pragma once

#include "../inc/MarlinConfig.h"

#if ENABLED(KP3S_MPU6050)
enum class KP3SMPU6050BusStatus : uint8_t {
  DISABLED,
  OK,
  SDA_STUCK_LOW,
  SCL_STUCK_LOW,
  NO_ACK
};

struct KP3SMPU6050Sample {
  int16_t ax, ay, az;
  int16_t temperature;
  int16_t gx, gy, gz;
  millis_t updated_ms;
  bool valid;
};

extern bool kp3s_mpu6050_runtime_enabled;
extern bool kp3s_mpu6050_swap_lines;
extern float kp3s_mpu6050_temp_offset_c;
extern float kp3s_mpu6050_level_zero_roll_deg;
extern float kp3s_mpu6050_level_zero_pitch_deg;
extern bool kp3s_mpu6050_level_zero_valid;

void kp3s_mpu6050_init();
void kp3s_mpu6050_set_enabled(const bool enabled);
void kp3s_mpu6050_set_swap_lines(const bool swap_lines);
bool kp3s_mpu6050_lines_swapped();
void kp3s_mpu6050_task(const millis_t now);
KP3SMPU6050BusStatus kp3s_mpu6050_test_bus();
bool kp3s_mpu6050_detect_now();
bool kp3s_mpu6050_detected();
uint8_t kp3s_mpu6050_address();
uint8_t kp3s_mpu6050_last_bus_address();
uint8_t kp3s_mpu6050_who_am_i();
bool kp3s_mpu6050_who_valid();

// Filtered orientation. When a level zero is stored the result is relative to it.
bool kp3s_mpu6050_level(float &roll_x_deg, float &pitch_y_deg);
bool kp3s_mpu6050_level_raw(float &roll_x_deg, float &pitch_y_deg);
bool kp3s_mpu6050_motion_stable();
bool kp3s_mpu6050_level_zero_candidate(float &roll_x_deg, float &pitch_y_deg);
bool kp3s_mpu6050_set_level_zero();
void kp3s_mpu6050_clear_level_zero();

// Startup level is evaluated only after a stationary sample window.
bool kp3s_mpu6050_startup_level(float &roll_x_deg, float &pitch_y_deg, bool &level_ok);
bool kp3s_mpu6050_startup_notice(float &roll_x_deg, float &pitch_y_deg, bool &level_ok);
uint8_t kp3s_mpu6050_startup_progress_pct();

// IMU die temperature. Offset is user-calibrated; delta is relative to startup baseline.
bool kp3s_mpu6050_temperature_raw_c(float &temperature_c);
bool kp3s_mpu6050_temperature_c(float &temperature_c);
bool kp3s_mpu6050_temperature_delta_c(float &delta_c);

// Dynamic toolhead acceleration/vibration indicators in g.
bool kp3s_mpu6050_motion(float &rms_g, float &peak_g, float &instant_g);
uint16_t kp3s_mpu6050_sample_rate_hz(const millis_t now=millis());

// Bounded 200 Hz capture for the V1 resonance assistant.
void kp3s_mpu6050_resonance_capture_start();
bool kp3s_mpu6050_resonance_capture_analyze(float &frequency_hz, uint8_t &confidence_pct);
uint16_t kp3s_mpu6050_resonance_samples();
bool kp3s_mpu6050_resonance_capturing();

const KP3SMPU6050Sample& kp3s_mpu6050_sample();
#endif
''',
        encoding="utf-8",
    )

    mpu6050_impl_h.write_text(
        r'''/**
 * KP3S Marlin Firmware V1 - MPU6050 / IMU software I2C on the PD8 + PD9 pair.
 * Default is SDA=PD9 / SCL=PD8; the LCD can permanently swap the two lines.
 *
 * The MPU is fixed to the toolhead, so three different signals are kept apart:
 *  1) filtered orientation (gravity + gyro complementary filter),
 *  2) dynamic acceleration/vibration (high-pass RMS/peak),
 *  3) MPU die temperature (not ambient air temperature).
 */
#pragma once
#include "../inc/MarlinConfig.h"
#include "../HAL/shared/Delay.h"
#include "../MarlinCore.h"
#if ENABLED(KP3S_SMART_UI)
  #include "kp3s_print_state.h"
#endif
#include <math.h>
#if ENABLED(KP3S_MPU6050)

#ifndef KP3S_MPU6050_SOFT_I2C_DELAY_US
  #define KP3S_MPU6050_SOFT_I2C_DELAY_US 8
#endif
#ifndef KP3S_MPU6050_POLL_IDLE_MS
  #define KP3S_MPU6050_POLL_IDLE_MS 20UL
#endif
#ifndef KP3S_MPU6050_POLL_PRINT_MS
  #define KP3S_MPU6050_POLL_PRINT_MS 10UL
#endif

bool kp3s_mpu6050_runtime_enabled = true;
bool kp3s_mpu6050_swap_lines = false;
float kp3s_mpu6050_temp_offset_c = 0.0f;
float kp3s_mpu6050_level_zero_roll_deg = 0.0f;
float kp3s_mpu6050_level_zero_pitch_deg = 0.0f;
bool kp3s_mpu6050_level_zero_valid = false;

static uint8_t kp3s_mpu_addr = 0;
static uint8_t kp3s_mpu_last_bus_addr = 0;
static uint8_t kp3s_mpu_last_who = 0;
static bool kp3s_mpu_last_who_valid = false;
static bool kp3s_mpu_present = false;
static uint8_t kp3s_mpu_faults = 0;
static millis_t kp3s_mpu_next_poll = 0, kp3s_mpu_next_retry = 0;
static KP3SMPU6050Sample kp3s_mpu_data = { 0,0,0,0,0,0,0,0,false };

// Derived/fused state
static bool kp3s_mpu_fusion_valid = false, kp3s_mpu_is_stable = false;
static float kp3s_mpu_roll_deg = 0.0f, kp3s_mpu_pitch_deg = 0.0f;
static float kp3s_mpu_gyro_bias_x = 0.0f, kp3s_mpu_gyro_bias_y = 0.0f, kp3s_mpu_gyro_bias_z = 0.0f;
static bool kp3s_mpu_gyro_bias_valid = false;
static uint8_t kp3s_mpu_gyro_bias_samples = 0;
static float kp3s_mpu_gyro_bias_sum_x = 0.0f, kp3s_mpu_gyro_bias_sum_y = 0.0f, kp3s_mpu_gyro_bias_sum_z = 0.0f;
static millis_t kp3s_mpu_fusion_ms = 0, kp3s_mpu_stable_since = 0;
static float kp3s_mpu_stable_roll_deg = 0.0f, kp3s_mpu_stable_pitch_deg = 0.0f;
static bool kp3s_mpu_motion_lp_valid = false;
static float kp3s_mpu_lp_ax = 0.0f, kp3s_mpu_lp_ay = 0.0f, kp3s_mpu_lp_az = 0.0f;
static float kp3s_mpu_vib_rms2 = 0.0f, kp3s_mpu_vib_peak_g = 0.0f, kp3s_mpu_vib_now_g = 0.0f;

// Startup level assessment. Good samples must stay temporally coherent; a
// long gap or obvious motion restarts the window instead of mixing positions.
static constexpr uint8_t KP3S_MPU_BOOT_SAMPLES_REQUIRED = 40;
static uint8_t kp3s_mpu_boot_samples = 0;
static float kp3s_mpu_boot_roll_sum = 0.0f, kp3s_mpu_boot_pitch_sum = 0.0f;
static bool kp3s_mpu_boot_level_ready = false, kp3s_mpu_boot_level_ok = false;
static float kp3s_mpu_boot_roll_deg = 0.0f, kp3s_mpu_boot_pitch_deg = 0.0f;
static millis_t kp3s_mpu_boot_notice_until = 0, kp3s_mpu_boot_last_good_ms = 0;

// Temperature baseline is independent from level calibration. It represents
// the IMU die temperature shortly after sensor startup and is not cleared by
// changing the angular zero.
static constexpr uint8_t KP3S_MPU_TEMP_BASELINE_SAMPLES = 20;
static uint8_t kp3s_mpu_temp_baseline_samples = 0;
static float kp3s_mpu_temp_baseline_sum = 0.0f, kp3s_mpu_boot_temp_raw_c = 0.0f;
static bool kp3s_mpu_boot_temp_valid = false;

// Resonance capture: 192 samples x 3 axes = 1152 bytes (~0.96 s at 200 Hz).
static constexpr uint16_t KP3S_RESONANCE_CAPTURE_MAX = 192;
static int16_t kp3s_res_ax[KP3S_RESONANCE_CAPTURE_MAX], kp3s_res_ay[KP3S_RESONANCE_CAPTURE_MAX], kp3s_res_az[KP3S_RESONANCE_CAPTURE_MAX];
static uint16_t kp3s_res_count = 0;
static bool kp3s_res_capture = false;
static millis_t kp3s_res_first_ms = 0, kp3s_res_last_ms = 0;

static inline void kp3s_i2c_delay() { DELAY_US(KP3S_MPU6050_SOFT_I2C_DELAY_US); }
static inline pin_t kp3s_i2c_sda_pin() { return kp3s_mpu6050_swap_lines ? KP3S_MPU6050_SCL_PIN : KP3S_MPU6050_SDA_PIN; }
static inline pin_t kp3s_i2c_scl_pin() { return kp3s_mpu6050_swap_lines ? KP3S_MPU6050_SDA_PIN : KP3S_MPU6050_SCL_PIN; }
static inline void kp3s_i2c_sda_low() { const pin_t pin = kp3s_i2c_sda_pin(); SET_OUTPUT(pin); WRITE(pin, LOW); }
static inline void kp3s_i2c_sda_release() { SET_INPUT_PULLUP(kp3s_i2c_sda_pin()); }
static inline void kp3s_i2c_scl_low() { const pin_t pin = kp3s_i2c_scl_pin(); SET_OUTPUT(pin); WRITE(pin, LOW); }
static inline void kp3s_i2c_scl_release() { SET_INPUT_PULLUP(kp3s_i2c_scl_pin()); }
static inline void kp3s_i2c_release_bus() {
  SET_INPUT(KP3S_MPU6050_SDA_PIN);
  SET_INPUT(KP3S_MPU6050_SCL_PIN);
}

static bool kp3s_i2c_wait_scl_high() {
  kp3s_i2c_scl_release();
  for (uint8_t i=0; i<80; ++i) {
    if (READ(kp3s_i2c_scl_pin())) return true;
    DELAY_US(2);
  }
  return false;
}

static void kp3s_i2c_bus_recover() {
  kp3s_i2c_sda_release(); kp3s_i2c_scl_release(); kp3s_i2c_delay();
  for (uint8_t i=0; i<9 && !READ(kp3s_i2c_sda_pin()); ++i) {
    kp3s_i2c_scl_low(); kp3s_i2c_delay();
    kp3s_i2c_scl_release(); kp3s_i2c_delay();
  }
  kp3s_i2c_sda_low(); kp3s_i2c_delay();
  kp3s_i2c_scl_release(); kp3s_i2c_delay();
  kp3s_i2c_sda_release(); kp3s_i2c_delay();
}

static bool kp3s_i2c_start() {
  kp3s_i2c_sda_release();
  if (!kp3s_i2c_wait_scl_high()) return false;
  kp3s_i2c_delay();
  if (!READ(kp3s_i2c_sda_pin())) return false;
  kp3s_i2c_sda_low(); kp3s_i2c_delay(); kp3s_i2c_scl_low();
  return true;
}
static void kp3s_i2c_stop() {
  kp3s_i2c_sda_low(); kp3s_i2c_delay();
  kp3s_i2c_wait_scl_high(); kp3s_i2c_delay();
  kp3s_i2c_sda_release(); kp3s_i2c_delay();
}

static bool kp3s_i2c_write_byte(uint8_t v) {
  for (uint8_t mask=0x80; mask; mask>>=1) {
    if (v & mask) kp3s_i2c_sda_release(); else kp3s_i2c_sda_low();
    kp3s_i2c_delay();
    if (!kp3s_i2c_wait_scl_high()) { kp3s_i2c_stop(); return false; }
    kp3s_i2c_delay(); kp3s_i2c_scl_low();
  }
  kp3s_i2c_sda_release(); kp3s_i2c_delay();
  if (!kp3s_i2c_wait_scl_high()) { kp3s_i2c_stop(); return false; }
  kp3s_i2c_delay();
  const bool ack = !READ(kp3s_i2c_sda_pin());
  kp3s_i2c_scl_low();
  return ack;
}

static bool kp3s_i2c_read_byte(uint8_t &v, const bool ack) {
  v=0; kp3s_i2c_sda_release();
  for (uint8_t i=0; i<8; ++i) {
    v <<= 1; kp3s_i2c_delay();
    if (!kp3s_i2c_wait_scl_high()) { kp3s_i2c_sda_release(); return false; }
    if (READ(kp3s_i2c_sda_pin())) v |= 1;
    kp3s_i2c_delay(); kp3s_i2c_scl_low();
  }
  if (ack) kp3s_i2c_sda_low(); else kp3s_i2c_sda_release();
  kp3s_i2c_delay();
  if (!kp3s_i2c_wait_scl_high()) { kp3s_i2c_sda_release(); return false; }
  kp3s_i2c_delay(); kp3s_i2c_scl_low(); kp3s_i2c_sda_release();
  return true;
}

static bool kp3s_i2c_probe_ack(const uint8_t addr) {
  if (!kp3s_i2c_start()) return false;
  const bool ack = kp3s_i2c_write_byte(uint8_t(addr << 1));
  kp3s_i2c_stop();
  return ack;
}

static bool kp3s_mpu_write_reg(const uint8_t reg, const uint8_t val) {
  if (!kp3s_mpu_addr) return false;
  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (!kp3s_i2c_start()) { kp3s_i2c_bus_recover(); continue; }
    if (!kp3s_i2c_write_byte(uint8_t(kp3s_mpu_addr << 1))
        || !kp3s_i2c_write_byte(reg)
        || !kp3s_i2c_write_byte(val)) {
      kp3s_i2c_stop(); kp3s_i2c_bus_recover(); continue;
    }
    kp3s_i2c_stop();
    return true;
  }
  return false;
}

static bool kp3s_mpu_read_regs_mode(const uint8_t reg, uint8_t *dst, const uint8_t count, const bool stop_before_read) {
  if (!kp3s_i2c_start()) return false;
  if (!kp3s_i2c_write_byte(uint8_t(kp3s_mpu_addr << 1)) || !kp3s_i2c_write_byte(reg)) {
    kp3s_i2c_stop(); return false;
  }
  if (stop_before_read) { kp3s_i2c_stop(); DELAY_US(12); }
  if (!kp3s_i2c_start()) { kp3s_i2c_stop(); return false; }
  if (!kp3s_i2c_write_byte(uint8_t((kp3s_mpu_addr << 1) | 1U))) { kp3s_i2c_stop(); return false; }
  for (uint8_t i = 0; i < count; ++i) {
    if (!kp3s_i2c_read_byte(dst[i], i + 1 < count)) { kp3s_i2c_stop(); return false; }
  }
  kp3s_i2c_stop();
  return true;
}

static bool kp3s_mpu_read_regs(const uint8_t reg, uint8_t *dst, const uint8_t count) {
  if (!kp3s_mpu_addr || !count) return false;
  for (uint8_t attempt = 0; attempt < 3; ++attempt) {
    if (kp3s_mpu_read_regs_mode(reg, dst, count, false)) return true;
    kp3s_i2c_bus_recover();
    if (kp3s_mpu_read_regs_mode(reg, dst, count, true)) return true;
    kp3s_i2c_bus_recover();
  }
  return false;
}

static void kp3s_mpu_delay_ms(uint16_t ms) { while (ms--) DELAY_US(1000); }

static constexpr uint8_t KP3S_I2C_SCAN_FIRST = 0x08, KP3S_I2C_SCAN_LAST = 0x77;

static bool kp3s_i2c_find_first_ack(uint8_t &found_addr) {
  found_addr = 0;
  for (uint8_t addr = KP3S_I2C_SCAN_FIRST; addr <= KP3S_I2C_SCAN_LAST; ++addr)
    if (kp3s_i2c_probe_ack(addr)) { found_addr = addr; return true; }
  return false;
}

static float kp3s_mpu_raw_temperature_c() {
  return float(kp3s_mpu_data.temperature) / 340.0f + 36.53f;
}

static bool kp3s_mpu_printing(const millis_t now);

static void kp3s_mpu_reset_derived(const bool reset_temperature_baseline=true) {
  kp3s_mpu_fusion_valid = false;
  kp3s_mpu_fusion_ms = kp3s_mpu_stable_since = 0;
  kp3s_mpu_is_stable = false;
  kp3s_mpu_roll_deg = kp3s_mpu_pitch_deg = 0.0f;
  kp3s_mpu_stable_roll_deg = kp3s_mpu_stable_pitch_deg = 0.0f;
  kp3s_mpu_gyro_bias_x = kp3s_mpu_gyro_bias_y = kp3s_mpu_gyro_bias_z = 0.0f;
  kp3s_mpu_gyro_bias_valid = false;
  kp3s_mpu_gyro_bias_samples = 0;
  kp3s_mpu_gyro_bias_sum_x = kp3s_mpu_gyro_bias_sum_y = kp3s_mpu_gyro_bias_sum_z = 0.0f;
  kp3s_mpu_motion_lp_valid = false;
  kp3s_mpu_lp_ax = kp3s_mpu_lp_ay = kp3s_mpu_lp_az = 0.0f;
  kp3s_mpu_vib_rms2 = kp3s_mpu_vib_peak_g = kp3s_mpu_vib_now_g = 0.0f;
  kp3s_mpu_boot_samples = 0;
  kp3s_mpu_boot_roll_sum = kp3s_mpu_boot_pitch_sum = 0.0f;
  kp3s_mpu_boot_level_ready = kp3s_mpu_boot_level_ok = false;
  kp3s_mpu_boot_notice_until = kp3s_mpu_boot_last_good_ms = 0;
  if (reset_temperature_baseline) {
    kp3s_mpu_temp_baseline_samples = 0;
    kp3s_mpu_temp_baseline_sum = kp3s_mpu_boot_temp_raw_c = 0.0f;
    kp3s_mpu_boot_temp_valid = false;
  }
  kp3s_res_capture = false;
  kp3s_res_count = 0;
  kp3s_res_first_ms = kp3s_res_last_ms = 0;
}

static void kp3s_mpu_update_derived(const millis_t now) {
  constexpr float ACC_LSB_PER_G = 16384.0f, GYRO_LSB_PER_DPS = 131.0f, RAD_TO_DEG_F = 57.2957795f;
  const float ax = float(kp3s_mpu_data.ax) / ACC_LSB_PER_G,
              ay = float(kp3s_mpu_data.ay) / ACC_LSB_PER_G,
              az = float(kp3s_mpu_data.az) / ACC_LSB_PER_G,
              gx = float(kp3s_mpu_data.gx) / GYRO_LSB_PER_DPS,
              gy = float(kp3s_mpu_data.gy) / GYRO_LSB_PER_DPS,
              gz = float(kp3s_mpu_data.gz) / GYRO_LSB_PER_DPS;
  const float amag = sqrtf(ax*ax + ay*ay + az*az);
  const float cgx = gx - (kp3s_mpu_gyro_bias_valid ? kp3s_mpu_gyro_bias_x : 0.0f),
              cgy = gy - (kp3s_mpu_gyro_bias_valid ? kp3s_mpu_gyro_bias_y : 0.0f),
              cgz = gz - (kp3s_mpu_gyro_bias_valid ? kp3s_mpu_gyro_bias_z : 0.0f);
  const float accel_roll = atan2f(ay, az) * RAD_TO_DEG_F;
  const float accel_pitch = atan2f(-ax, sqrtf(ay*ay + az*az)) * RAD_TO_DEG_F;

  float dt = kp3s_mpu_fusion_ms ? float(now - kp3s_mpu_fusion_ms) * 0.001f : 0.01f;
  if (dt < 0.001f) dt = 0.001f;
  if (dt > 0.050f) dt = 0.050f;
  kp3s_mpu_fusion_ms = now;

  if (!kp3s_mpu_fusion_valid) {
    kp3s_mpu_roll_deg = accel_roll;
    kp3s_mpu_pitch_deg = accel_pitch;
    kp3s_mpu_fusion_valid = true;
  }
  else {
    kp3s_mpu_roll_deg += cgx * dt;
    kp3s_mpu_pitch_deg += cgy * dt;

    // Acceleration of the moving carriage is not gravity. Only use the accel
    // angle strongly when magnitude is close to 1g; during fast moves let gyro
    // carry short-term orientation to avoid a false "tilt" indication.
    const bool accel_trust = fabsf(amag - 1.0f) < 0.12f;
    if (accel_trust) {
      const bool gyro_quiet = fabsf(cgx) < 3.0f && fabsf(cgy) < 3.0f && fabsf(cgz) < 3.0f;
      // Keep the complementary filter time constant invariant when polling
      // changes between 50 Hz idle and 100 Hz printing.
      const float tau_s = gyro_quiet ? 0.48f : 3.5f;
      const float alpha = tau_s / (tau_s + dt);
      kp3s_mpu_roll_deg = alpha * kp3s_mpu_roll_deg + (1.0f - alpha) * accel_roll;
      kp3s_mpu_pitch_deg = alpha * kp3s_mpu_pitch_deg + (1.0f - alpha) * accel_pitch;
      // Gyro bias is learned after the vibration residual below, where a
      // stationary window can be identified without using stale vibration data.
    }
  }

  // Low-frequency baseline follows gravity / slow carriage motion. The
  // residual is a useful real-time toolhead acceleration / vibration metric.
  if (!kp3s_mpu_motion_lp_valid) {
    kp3s_mpu_lp_ax = ax; kp3s_mpu_lp_ay = ay; kp3s_mpu_lp_az = az;
    kp3s_mpu_motion_lp_valid = true;
  }
  const float lp_k = _MIN(0.12f, _MAX(0.02f, dt * 4.0f));
  kp3s_mpu_lp_ax += (ax - kp3s_mpu_lp_ax) * lp_k;
  kp3s_mpu_lp_ay += (ay - kp3s_mpu_lp_ay) * lp_k;
  kp3s_mpu_lp_az += (az - kp3s_mpu_lp_az) * lp_k;
  const float dx = ax - kp3s_mpu_lp_ax, dy = ay - kp3s_mpu_lp_ay, dz = az - kp3s_mpu_lp_az;
  kp3s_mpu_vib_now_g = sqrtf(dx*dx + dy*dy + dz*dz);
  const float rms_k = _MIN(0.10f, _MAX(0.01f, dt * 2.5f));
  kp3s_mpu_vib_rms2 += (kp3s_mpu_vib_now_g * kp3s_mpu_vib_now_g - kp3s_mpu_vib_rms2) * rms_k;
  // Peak decay is time-based so its visual persistence is the same at 50/100 Hz.
  kp3s_mpu_vib_peak_g *= _MAX(0.0f, 1.0f - dt * 0.50f);
  if (kp3s_mpu_vib_now_g > kp3s_mpu_vib_peak_g) kp3s_mpu_vib_peak_g = kp3s_mpu_vib_now_g;

  // Learn the stationary gyro zero from a short coherent window, then only
  // make very slow corrections. This avoids both startup bias and learning a
  // deliberate slow tilt as if it were sensor offset.
  const bool bias_sample_ok = !kp3s_res_capture
                           && fabsf(amag - 1.0f) < 0.06f
                           && kp3s_mpu_vib_now_g < 0.035f
                           && fabsf(gx) < 5.0f && fabsf(gy) < 5.0f && fabsf(gz) < 5.0f;
  if (!kp3s_mpu_gyro_bias_valid) {
    if (bias_sample_ok) {
      kp3s_mpu_gyro_bias_sum_x += gx; kp3s_mpu_gyro_bias_sum_y += gy; kp3s_mpu_gyro_bias_sum_z += gz;
      if (++kp3s_mpu_gyro_bias_samples >= 12) {
        const float inv_bias_n = 1.0f / float(kp3s_mpu_gyro_bias_samples);
        kp3s_mpu_gyro_bias_x = kp3s_mpu_gyro_bias_sum_x * inv_bias_n;
        kp3s_mpu_gyro_bias_y = kp3s_mpu_gyro_bias_sum_y * inv_bias_n;
        kp3s_mpu_gyro_bias_z = kp3s_mpu_gyro_bias_sum_z * inv_bias_n;
        kp3s_mpu_gyro_bias_valid = true;
      }
    }
    else if (fabsf(amag - 1.0f) > 0.12f || kp3s_mpu_vib_now_g > 0.08f) {
      kp3s_mpu_gyro_bias_samples = 0;
      kp3s_mpu_gyro_bias_sum_x = kp3s_mpu_gyro_bias_sum_y = kp3s_mpu_gyro_bias_sum_z = 0.0f;
    }
  }
  else if (bias_sample_ok && fabsf(cgx) < 0.8f && fabsf(cgy) < 0.8f && fabsf(cgz) < 0.8f) {
    const float bias_k = _MIN(0.004f, dt * 0.08f);
    kp3s_mpu_gyro_bias_x += (gx - kp3s_mpu_gyro_bias_x) * bias_k;
    kp3s_mpu_gyro_bias_y += (gy - kp3s_mpu_gyro_bias_y) * bias_k;
    kp3s_mpu_gyro_bias_z += (gz - kp3s_mpu_gyro_bias_z) * bias_k;
  }

  const float sgx = gx - (kp3s_mpu_gyro_bias_valid ? kp3s_mpu_gyro_bias_x : 0.0f),
              sgy = gy - (kp3s_mpu_gyro_bias_valid ? kp3s_mpu_gyro_bias_y : 0.0f),
              sgz = gz - (kp3s_mpu_gyro_bias_valid ? kp3s_mpu_gyro_bias_z : 0.0f);
  const bool stable_now = fabsf(amag - 1.0f) < 0.08f
                       && fabsf(sgx) < 2.5f && fabsf(sgy) < 2.5f && fabsf(sgz) < 2.5f
                       && kp3s_mpu_vib_now_g < 0.06f;
  if (stable_now) {
    if (!kp3s_mpu_stable_since) {
      kp3s_mpu_stable_since = now;
      kp3s_mpu_stable_roll_deg = kp3s_mpu_roll_deg;
      kp3s_mpu_stable_pitch_deg = kp3s_mpu_pitch_deg;
    }
    else {
      const float zero_k = _MIN(0.20f, dt * 4.0f);
      kp3s_mpu_stable_roll_deg += (kp3s_mpu_roll_deg - kp3s_mpu_stable_roll_deg) * zero_k;
      kp3s_mpu_stable_pitch_deg += (kp3s_mpu_pitch_deg - kp3s_mpu_stable_pitch_deg) * zero_k;
    }
  }
  else kp3s_mpu_stable_since = 0;
  kp3s_mpu_is_stable = kp3s_mpu_stable_since && ELAPSED(now, kp3s_mpu_stable_since + 500UL);

  // Establish die-temperature delta independently of angular level. Level-zero
  // calibration must never redefine what "delta since startup" means.
  if (!kp3s_mpu_boot_temp_valid) {
    const float raw_temp = kp3s_mpu_raw_temperature_c();
    if (WITHIN(raw_temp, -50.0f, 110.0f)) {
      kp3s_mpu_temp_baseline_sum += raw_temp;
      if (++kp3s_mpu_temp_baseline_samples >= KP3S_MPU_TEMP_BASELINE_SAMPLES) {
        kp3s_mpu_boot_temp_raw_c = kp3s_mpu_temp_baseline_sum / float(kp3s_mpu_temp_baseline_samples);
        kp3s_mpu_boot_temp_valid = true;
      }
    }
  }

  // Startup inclination is accepted only from a coherent idle window. Small
  // vibration gaps are tolerated, but a long gap, printing, resonance capture,
  // or obvious motion prevents samples from different positions being averaged.
  if (!kp3s_mpu_boot_level_ready && !kp3s_mpu_printing(now) && !kp3s_res_capture) {
    const bool startup_sample_ok = fabsf(amag - 1.0f) < 0.12f
                                && fabsf(sgx) < 4.0f && fabsf(sgy) < 4.0f && fabsf(sgz) < 4.0f
                                && kp3s_mpu_vib_now_g < 0.10f;
    const bool startup_hard_motion = fabsf(amag - 1.0f) > 0.25f
                                  || fabsf(sgx) > 10.0f || fabsf(sgy) > 10.0f || fabsf(sgz) > 10.0f
                                  || kp3s_mpu_vib_now_g > 0.20f;
    if (startup_sample_ok) {
      if (kp3s_mpu_boot_samples && ELAPSED(now, kp3s_mpu_boot_last_good_ms + 250UL)) {
        kp3s_mpu_boot_samples = 0;
        kp3s_mpu_boot_roll_sum = kp3s_mpu_boot_pitch_sum = 0.0f;
      }
      kp3s_mpu_boot_last_good_ms = now;
      const float roll = kp3s_mpu_roll_deg - (kp3s_mpu6050_level_zero_valid ? kp3s_mpu6050_level_zero_roll_deg : 0.0f);
      const float pitch = kp3s_mpu_pitch_deg - (kp3s_mpu6050_level_zero_valid ? kp3s_mpu6050_level_zero_pitch_deg : 0.0f);
      kp3s_mpu_boot_roll_sum += roll;
      kp3s_mpu_boot_pitch_sum += pitch;
      if (++kp3s_mpu_boot_samples >= KP3S_MPU_BOOT_SAMPLES_REQUIRED) {
        const float inv = 1.0f / float(kp3s_mpu_boot_samples);
        kp3s_mpu_boot_roll_deg = kp3s_mpu_boot_roll_sum * inv;
        kp3s_mpu_boot_pitch_deg = kp3s_mpu_boot_pitch_sum * inv;
        kp3s_mpu_boot_level_ok = fabsf(kp3s_mpu_boot_roll_deg) <= 0.5f && fabsf(kp3s_mpu_boot_pitch_deg) <= 0.5f;
        kp3s_mpu_boot_level_ready = true;
        kp3s_mpu_boot_notice_until = now + 60000UL;
      }
    }
    else if (startup_hard_motion && kp3s_mpu_boot_samples) {
      kp3s_mpu_boot_samples = 0;
      kp3s_mpu_boot_roll_sum = kp3s_mpu_boot_pitch_sum = 0.0f;
      kp3s_mpu_boot_last_good_ms = 0;
    }
  }
}

static bool kp3s_mpu_parse_sample(const uint8_t * const b, const millis_t now) {
  kp3s_mpu_data.ax=int16_t((uint16_t(b[0])<<8)|b[1]);
  kp3s_mpu_data.ay=int16_t((uint16_t(b[2])<<8)|b[3]);
  kp3s_mpu_data.az=int16_t((uint16_t(b[4])<<8)|b[5]);
  kp3s_mpu_data.temperature=int16_t((uint16_t(b[6])<<8)|b[7]);
  kp3s_mpu_data.gx=int16_t((uint16_t(b[8])<<8)|b[9]);
  kp3s_mpu_data.gy=int16_t((uint16_t(b[10])<<8)|b[11]);
  kp3s_mpu_data.gz=int16_t((uint16_t(b[12])<<8)|b[13]);
  const bool accel_signal = ABS(kp3s_mpu_data.ax) > 32 || ABS(kp3s_mpu_data.ay) > 32 || ABS(kp3s_mpu_data.az) > 32;
  const bool all_minus_one = kp3s_mpu_data.ax == -1 && kp3s_mpu_data.ay == -1 && kp3s_mpu_data.az == -1
                          && kp3s_mpu_data.temperature == -1 && kp3s_mpu_data.gx == -1
                          && kp3s_mpu_data.gy == -1 && kp3s_mpu_data.gz == -1;
  const bool all_zero = kp3s_mpu_data.ax == 0 && kp3s_mpu_data.ay == 0 && kp3s_mpu_data.az == 0
                     && kp3s_mpu_data.temperature == 0 && kp3s_mpu_data.gx == 0
                     && kp3s_mpu_data.gy == 0 && kp3s_mpu_data.gz == 0;
  const float raw_ax_g = float(kp3s_mpu_data.ax) / 16384.0f,
              raw_ay_g = float(kp3s_mpu_data.ay) / 16384.0f,
              raw_az_g = float(kp3s_mpu_data.az) / 16384.0f;
  const float raw_amag = sqrtf(raw_ax_g*raw_ax_g + raw_ay_g*raw_ay_g + raw_az_g*raw_az_g);
  kp3s_mpu_data.updated_ms=now;
  kp3s_mpu_data.valid=accel_signal && !all_minus_one && !all_zero && raw_amag > 0.05f && raw_amag < 3.70f;
  if (kp3s_mpu_data.valid) {
    if (kp3s_res_capture && kp3s_res_count < KP3S_RESONANCE_CAPTURE_MAX) {
      if (!kp3s_res_count) kp3s_res_first_ms = now;
      kp3s_res_ax[kp3s_res_count] = kp3s_mpu_data.ax;
      kp3s_res_ay[kp3s_res_count] = kp3s_mpu_data.ay;
      kp3s_res_az[kp3s_res_count] = kp3s_mpu_data.az;
      kp3s_res_last_ms = now;
      ++kp3s_res_count;
      if (kp3s_res_count >= KP3S_RESONANCE_CAPTURE_MAX) kp3s_res_capture = false;
    }
    kp3s_mpu_update_derived(now);
  }
  return kp3s_mpu_data.valid;
}

static bool kp3s_mpu_read_sample_now(const millis_t now) {
  uint8_t b[14];
  if (!kp3s_mpu_read_regs(0x3B, b, uint8_t(sizeof(b)))) { kp3s_mpu_data.valid=false; return false; }
  return kp3s_mpu_parse_sample(b, now);
}

static bool kp3s_mpu_configure_and_verify() {
  if (!kp3s_mpu_write_reg(0x6B, 0x80)) return false;
  kp3s_mpu_delay_ms(100);
  if (!kp3s_mpu_write_reg(0x6B, 0x01)) return false;
  kp3s_mpu_delay_ms(20);
  // CONFIG=3 -> ~44Hz accel / ~42Hz gyro DLPF. SMPLRT_DIV=4 -> 200Hz
  // internal register update; firmware reads at 50Hz idle / 100Hz printing.
  if (!kp3s_mpu_write_reg(0x6C, 0x00)
      || !kp3s_mpu_write_reg(0x19, 0x04)
      || !kp3s_mpu_write_reg(0x1A, 0x03)
      || !kp3s_mpu_write_reg(0x1B, 0x00)
      || !kp3s_mpu_write_reg(0x1C, 0x00)) return false;
  kp3s_mpu_delay_ms(10);
  uint8_t cfg[4] = { 0xFF,0xFF,0xFF,0xFF }, pwr[2] = { 0xFF,0xFF };
  if (!kp3s_mpu_read_regs(0x19, cfg, 4) || !kp3s_mpu_read_regs(0x6B, pwr, 2)) return false;
  if (cfg[0] != 0x04 || (cfg[1] & 0x07) != 0x03 || (cfg[2] & 0x18) || (cfg[3] & 0x18)) return false;
  if ((pwr[0] & 0x7F) != 0x01 || pwr[1] != 0x00) return false;
  return kp3s_mpu_read_sample_now(millis());
}

static bool kp3s_mpu_probe_address(const uint8_t addr) {
  kp3s_mpu_addr = addr;
  kp3s_mpu_last_bus_addr = addr;
  uint8_t who = 0;
  kp3s_mpu_last_who_valid = kp3s_mpu_read_regs(0x75, &who, 1);
  if (kp3s_mpu_last_who_valid) kp3s_mpu_last_who = who;
  const bool normal_identity = kp3s_mpu_last_who_valid && ((who & 0x7E) == 0x68);
  if (!normal_identity) {
    // Non-destructive clone fallback is intentionally restricted to the two
    // official MPU-60X0 strap addresses. Never write RESET/config registers to
    // an arbitrary ACKing I2C device merely because register 0x6B is readable.
    if (addr != 0x68 && addr != 0x69) return false;
    uint8_t pwr = 0xFF, gyro_cfg = 0xFF, accel_cfg = 0xFF;
    if (!kp3s_mpu_read_regs(0x6B, &pwr, 1)
        || !kp3s_mpu_read_regs(0x1B, &gyro_cfg, 1)
        || !kp3s_mpu_read_regs(0x1C, &accel_cfg, 1)) return false;
    if (pwr == 0xFF || (gyro_cfg & 0x07) || (accel_cfg & 0x07)) return false;
  }
  return kp3s_mpu_configure_and_verify();
}

static bool kp3s_mpu_scan_bus() {
  kp3s_mpu_addr = 0;
  kp3s_mpu_last_bus_addr = 0;
  kp3s_mpu_last_who = 0;
  kp3s_mpu_last_who_valid = false;
  for (uint8_t addr = KP3S_I2C_SCAN_FIRST; addr <= KP3S_I2C_SCAN_LAST; ++addr) {
    if (!kp3s_i2c_probe_ack(addr)) continue;
    if (!kp3s_mpu_last_bus_addr) kp3s_mpu_last_bus_addr = addr;
    if (kp3s_mpu_probe_address(addr)) return true;
  }
  kp3s_mpu_addr = 0;
  return false;
}

static bool kp3s_mpu_try_detect() {
  if (!kp3s_mpu6050_runtime_enabled) return false;
  kp3s_i2c_bus_recover();
  if (!kp3s_mpu_scan_bus()) { kp3s_mpu_present=false; kp3s_mpu_data.valid=false; return false; }
  kp3s_mpu_present=true; kp3s_mpu_faults=0; return true;
}

static bool kp3s_mpu_printing(const millis_t now) {
  bool active = printingIsActive();
  #if ENABLED(KP3S_SMART_UI)
    active |= kp3s_serial_printing(now);
  #else
    UNUSED(now);
  #endif
  return active;
}

uint16_t kp3s_mpu6050_sample_rate_hz(const millis_t now) {
  if (kp3s_res_capture) return 200;
  return kp3s_mpu_printing(now) ? uint16_t(1000UL / KP3S_MPU6050_POLL_PRINT_MS)
                                : uint16_t(1000UL / KP3S_MPU6050_POLL_IDLE_MS);
}

void kp3s_mpu6050_init() {
  kp3s_mpu_reset_derived();
  if (!kp3s_mpu6050_runtime_enabled) {
    kp3s_mpu_addr = kp3s_mpu_last_bus_addr = kp3s_mpu_last_who = 0;
    kp3s_mpu_last_who_valid = kp3s_mpu_present = kp3s_mpu_data.valid = false;
    kp3s_i2c_release_bus();
    return;
  }
  kp3s_i2c_sda_release(); kp3s_i2c_scl_release(); DELAY_US(100);
  const bool ok = kp3s_mpu_try_detect();
  const millis_t now = millis();
  kp3s_mpu_next_poll = now + KP3S_MPU6050_POLL_IDLE_MS;
  kp3s_mpu_next_retry = now + 2000UL;
  #if ENABLED(KP3S_MPU6050_DEBUG)
    SERIAL_ECHOPGM("MPU6050 init: ");
    if (ok) { SERIAL_ECHOPGM("OK addr=0x"); SERIAL_PRINT(kp3s_mpu_addr, HEX); SERIAL_ECHOPGM(" WHO=0x"); SERIAL_PRINTLN(kp3s_mpu_last_who, HEX); }
    else SERIAL_ECHOLNPGM("NOT FOUND on I2C scan");
  #else
    (void)ok;
  #endif
}

void kp3s_mpu6050_set_enabled(const bool enabled) {
  kp3s_mpu6050_runtime_enabled = enabled;
  kp3s_mpu_addr = kp3s_mpu_last_bus_addr = kp3s_mpu_last_who = 0;
  kp3s_mpu_last_who_valid = kp3s_mpu_present = false;
  kp3s_mpu_faults = 0; kp3s_mpu_data.valid = false;
  kp3s_mpu_reset_derived();
  if (enabled) kp3s_mpu6050_init(); else kp3s_i2c_release_bus();
}

void kp3s_mpu6050_set_swap_lines(const bool swap_lines) {
  kp3s_i2c_release_bus();
  kp3s_mpu6050_swap_lines = swap_lines;
  kp3s_mpu_addr = kp3s_mpu_last_bus_addr = kp3s_mpu_last_who = 0;
  kp3s_mpu_last_who_valid = kp3s_mpu_present = false;
  kp3s_mpu_faults = 0; kp3s_mpu_data.valid = false;
  kp3s_mpu_reset_derived();
  if (kp3s_mpu6050_runtime_enabled) kp3s_mpu6050_init(); else kp3s_i2c_release_bus();
}

bool kp3s_mpu6050_lines_swapped() { return kp3s_mpu6050_swap_lines; }

KP3SMPU6050BusStatus kp3s_mpu6050_test_bus() {
  kp3s_mpu_last_bus_addr = 0;
  if (!kp3s_mpu6050_runtime_enabled) return KP3SMPU6050BusStatus::DISABLED;
  kp3s_i2c_bus_recover(); kp3s_i2c_sda_release(); kp3s_i2c_scl_release(); DELAY_US(20);
  if (!READ(kp3s_i2c_scl_pin())) return KP3SMPU6050BusStatus::SCL_STUCK_LOW;
  if (!READ(kp3s_i2c_sda_pin())) return KP3SMPU6050BusStatus::SDA_STUCK_LOW;
  uint8_t found_addr = 0;
  if (!kp3s_i2c_find_first_ack(found_addr)) return KP3SMPU6050BusStatus::NO_ACK;
  kp3s_mpu_last_bus_addr = found_addr;
  return KP3SMPU6050BusStatus::OK;
}

bool kp3s_mpu6050_detect_now() {
  if (!kp3s_mpu6050_runtime_enabled) return false;
  kp3s_mpu_reset_derived(false); // a diagnostic re-detect must not redefine the startup temperature baseline
  const bool ok = kp3s_mpu_try_detect();
  const millis_t now = millis();
  kp3s_mpu_next_poll = now;
  kp3s_mpu_next_retry = now + (ok ? 2000UL : 1000UL);
  return ok;
}

void kp3s_mpu6050_task(const millis_t now) {
  if (!kp3s_mpu6050_runtime_enabled) return;
  if (!kp3s_mpu_present) {
    if (!ELAPSED(now, kp3s_mpu_next_retry)) return;
    kp3s_mpu_next_retry = now + 2000UL;
    kp3s_mpu_try_detect(); return;
  }
  if (!ELAPSED(now, kp3s_mpu_next_poll)) return;
  // Use the MPU's full configured 200 Hz only during the short resonance test.
  kp3s_mpu_next_poll = now + (kp3s_res_capture ? 5UL : (kp3s_mpu_printing(now) ? KP3S_MPU6050_POLL_PRINT_MS : KP3S_MPU6050_POLL_IDLE_MS));
  if (!kp3s_mpu_read_sample_now(now)) {
    kp3s_mpu_data.valid=false;
    if (++kp3s_mpu_faults >= 3) {
      kp3s_mpu_present=false;
      kp3s_mpu_reset_derived(false); // keep the original die-temperature baseline across transient reconnects
      kp3s_mpu_next_retry=now+1000UL;
    }
    return;
  }
  kp3s_mpu_faults=0;
}

bool kp3s_mpu6050_detected() { return kp3s_mpu_present; }
uint8_t kp3s_mpu6050_address() { return kp3s_mpu_addr; }
uint8_t kp3s_mpu6050_last_bus_address() { return kp3s_mpu_last_bus_addr; }
uint8_t kp3s_mpu6050_who_am_i() { return kp3s_mpu_last_who; }
bool kp3s_mpu6050_who_valid() { return kp3s_mpu_last_who_valid; }

bool kp3s_mpu6050_level_raw(float &roll_x_deg, float &pitch_y_deg) {
  if (!kp3s_mpu_present || !kp3s_mpu_data.valid || !kp3s_mpu_fusion_valid) return false;
  roll_x_deg = kp3s_mpu_roll_deg;
  pitch_y_deg = kp3s_mpu_pitch_deg;
  return true;
}

bool kp3s_mpu6050_level(float &roll_x_deg, float &pitch_y_deg) {
  if (!kp3s_mpu6050_level_raw(roll_x_deg, pitch_y_deg)) return false;
  roll_x_deg -= kp3s_mpu6050_level_zero_valid ? kp3s_mpu6050_level_zero_roll_deg : 0.0f;
  pitch_y_deg -= kp3s_mpu6050_level_zero_valid ? kp3s_mpu6050_level_zero_pitch_deg : 0.0f;
  return true;
}

bool kp3s_mpu6050_motion_stable() { return kp3s_mpu_present && kp3s_mpu_data.valid && kp3s_mpu_is_stable; }

bool kp3s_mpu6050_level_zero_candidate(float &roll_x_deg, float &pitch_y_deg) {
  if (!kp3s_mpu6050_motion_stable()) return false;
  roll_x_deg = kp3s_mpu_stable_roll_deg;
  pitch_y_deg = kp3s_mpu_stable_pitch_deg;
  return true;
}

bool kp3s_mpu6050_set_level_zero() {
  float zero_roll=0.0f, zero_pitch=0.0f;
  if (!kp3s_mpu6050_level_zero_candidate(zero_roll, zero_pitch)) return false;
  // Save exactly the settled candidate exposed to the calibration screen.
  kp3s_mpu6050_level_zero_roll_deg = zero_roll;
  kp3s_mpu6050_level_zero_pitch_deg = zero_pitch;
  kp3s_mpu6050_level_zero_valid = true;
  kp3s_mpu_boot_samples = 0;
  kp3s_mpu_boot_roll_sum = kp3s_mpu_boot_pitch_sum = 0.0f;
  kp3s_mpu_boot_level_ready = kp3s_mpu_boot_level_ok = false;
  kp3s_mpu_boot_notice_until = kp3s_mpu_boot_last_good_ms = 0;
  return true;
}

void kp3s_mpu6050_clear_level_zero() {
  kp3s_mpu6050_level_zero_roll_deg = kp3s_mpu6050_level_zero_pitch_deg = 0.0f;
  kp3s_mpu6050_level_zero_valid = false;
  kp3s_mpu_boot_samples = 0;
  kp3s_mpu_boot_roll_sum = kp3s_mpu_boot_pitch_sum = 0.0f;
  kp3s_mpu_boot_level_ready = kp3s_mpu_boot_level_ok = false;
  kp3s_mpu_boot_notice_until = kp3s_mpu_boot_last_good_ms = 0;
}

bool kp3s_mpu6050_startup_level(float &roll_x_deg, float &pitch_y_deg, bool &level_ok) {
  if (!kp3s_mpu_boot_level_ready) return false;
  roll_x_deg = kp3s_mpu_boot_roll_deg;
  pitch_y_deg = kp3s_mpu_boot_pitch_deg;
  level_ok = kp3s_mpu_boot_level_ok;
  return true;
}

bool kp3s_mpu6050_startup_notice(float &roll_x_deg, float &pitch_y_deg, bool &level_ok) {
  if (!kp3s_mpu6050_startup_level(roll_x_deg, pitch_y_deg, level_ok)) return false;
  return PENDING(millis(), kp3s_mpu_boot_notice_until);
}

uint8_t kp3s_mpu6050_startup_progress_pct() {
  if (kp3s_mpu_boot_level_ready) return 100;
  return uint8_t(_MIN(99U, (uint16_t(kp3s_mpu_boot_samples) * 100U) / KP3S_MPU_BOOT_SAMPLES_REQUIRED));
}

bool kp3s_mpu6050_temperature_raw_c(float &temperature_c) {
  if (!kp3s_mpu_present || !kp3s_mpu_data.valid) return false;
  temperature_c = kp3s_mpu_raw_temperature_c();
  return true;
}

bool kp3s_mpu6050_temperature_c(float &temperature_c) {
  if (!kp3s_mpu6050_temperature_raw_c(temperature_c)) return false;
  temperature_c += kp3s_mpu6050_temp_offset_c;
  return true;
}

bool kp3s_mpu6050_temperature_delta_c(float &delta_c) {
  float raw = 0;
  if (!kp3s_mpu_boot_temp_valid || !kp3s_mpu6050_temperature_raw_c(raw)) return false;
  delta_c = raw - kp3s_mpu_boot_temp_raw_c;
  return true;
}

bool kp3s_mpu6050_motion(float &rms_g, float &peak_g, float &instant_g) {
  if (!kp3s_mpu_present || !kp3s_mpu_data.valid || !kp3s_mpu_motion_lp_valid) return false;
  rms_g = sqrtf(_MAX(0.0f, kp3s_mpu_vib_rms2));
  peak_g = kp3s_mpu_vib_peak_g;
  instant_g = kp3s_mpu_vib_now_g;
  return true;
}

void kp3s_mpu6050_resonance_capture_start() {
  kp3s_res_count = 0;
  kp3s_res_first_ms = kp3s_res_last_ms = 0;
  kp3s_res_capture = kp3s_mpu_present && kp3s_mpu_data.valid;
  if (kp3s_res_capture) {
    // Normal operation uses DLPF_CFG=3 (~44 Hz accel / ~42 Hz gyro).
    // Widen only during resonance capture so the 20-80 Hz scan is observable.
    if (!kp3s_mpu_write_reg(0x1A, 0x02)) kp3s_res_capture = false; // ~94 Hz accel / ~98 Hz gyro bandwidth
    else kp3s_mpu_delay_ms(5);
  }
  kp3s_mpu_next_poll = millis();
}

bool kp3s_mpu6050_resonance_capturing() { return kp3s_res_capture; }
uint16_t kp3s_mpu6050_resonance_samples() { return kp3s_res_count; }

static float kp3s_res_goertzel_power(const int16_t * const data, const uint16_t n, const float mean, const float frequency_hz, const float sample_rate_hz) {
  const float omega = 6.28318530718f * frequency_hz / sample_rate_hz;
  const float coeff = 2.0f * cosf(omega);
  float q0 = 0.0f, q1 = 0.0f, q2 = 0.0f;
  const float mid = float(n - 1) * 0.5f;
  for (uint16_t i = 0; i < n; ++i) {
    // Bartlett window reduces leakage from the short impulse/ring-down capture
    // without the RAM/cost of a second floating-point window table.
    const float window = mid > 0.0f ? _MAX(0.0f, 1.0f - fabsf((float(i) - mid) / mid)) : 1.0f;
    q0 = (float(data[i]) - mean) * window + coeff * q1 - q2;
    q2 = q1; q1 = q0;
  }
  const float power = q1*q1 + q2*q2 - coeff*q1*q2;
  return power > 0.0f ? power : 0.0f;
}

bool kp3s_mpu6050_resonance_capture_analyze(float &frequency_hz, uint8_t &confidence_pct) {
  kp3s_res_capture = false;
  // Restore the normal low-noise bandwidth even when the analysis later fails.
  if (kp3s_mpu_present) {
    kp3s_mpu_write_reg(0x1A, 0x03);
    kp3s_mpu_delay_ms(5);
  }
  frequency_hz = 0.0f; confidence_pct = 0;
  const uint16_t n = kp3s_res_count;
  if (n < 120 || kp3s_res_last_ms <= kp3s_res_first_ms) return false;
  const float sample_rate = float(n - 1) * 1000.0f / float(kp3s_res_last_ms - kp3s_res_first_ms);
  if (sample_rate < 140.0f || sample_rate > 240.0f) return false;

  float mean_x=0, mean_y=0, mean_z=0;
  for (uint16_t i=0; i<n; ++i) { mean_x += kp3s_res_ax[i]; mean_y += kp3s_res_ay[i]; mean_z += kp3s_res_az[i]; }
  const float inv_n = 1.0f / float(n);
  mean_x *= inv_n; mean_y *= inv_n; mean_z *= inv_n;

  float best_power=0.0f, best_freq=0.0f;
  for (uint8_t f=20; f<=80; ++f) {
    const float power = kp3s_res_goertzel_power(kp3s_res_ax,n,mean_x,float(f),sample_rate)
                      + kp3s_res_goertzel_power(kp3s_res_ay,n,mean_y,float(f),sample_rate)
                      + kp3s_res_goertzel_power(kp3s_res_az,n,mean_z,float(f),sample_rate);
    if (power > best_power) { best_power = power; best_freq = float(f); }
  }
  if (best_power <= 0.0f) return false;

  float refined_power = best_power, refined_freq = best_freq;
  for (int8_t q=-3; q<=3; ++q) {
    const float f = best_freq + float(q) * 0.25f;
    if (f < 20.0f || f > 80.0f) continue;
    const float power = kp3s_res_goertzel_power(kp3s_res_ax,n,mean_x,f,sample_rate)
                      + kp3s_res_goertzel_power(kp3s_res_ay,n,mean_y,f,sample_rate)
                      + kp3s_res_goertzel_power(kp3s_res_az,n,mean_z,f,sample_rate);
    if (power > refined_power) { refined_power = power; refined_freq = f; }
  }

  float noise_sum = 0.0f; uint8_t noise_bins = 0;
  for (uint8_t f=20; f<=80; ++f) {
    if (fabsf(float(f) - refined_freq) <= 2.0f) continue; // don't call the resonance skirt "noise"
    noise_sum += kp3s_res_goertzel_power(kp3s_res_ax,n,mean_x,float(f),sample_rate)
               + kp3s_res_goertzel_power(kp3s_res_ay,n,mean_y,float(f),sample_rate)
               + kp3s_res_goertzel_power(kp3s_res_az,n,mean_z,float(f),sample_rate);
    ++noise_bins;
  }
  const float noise = _MAX(1.0f, noise_sum / float(_MAX(1, int(noise_bins))));
  const float snr = refined_power / noise;
  confidence_pct = uint8_t(_MIN(100.0f, _MAX(0.0f, (snr - 1.0f) * 10.0f)));
  frequency_hz = refined_freq;
  return confidence_pct >= 25 && WITHIN(frequency_hz, 20.0f, 80.0f);
}

const KP3SMPU6050Sample& kp3s_mpu6050_sample() { return kp3s_mpu_data; }
#endif
''',
        encoding="utf-8",
    )

    print("[OK] Create MPU6050 fused level + startup assessment + live vibration + resonance capture + calibrated die temperature")

    print_state_h.write_text(
        r'''#pragma once

#include "../inc/MarlinConfigPre.h"

#if ENABLED(KP3S_SMART_UI)
  void kp3s_print_state_note_serial(const char *command, const millis_t now);
  bool kp3s_serial_printing(const millis_t now=millis());
  bool kp3s_serial_print_paused();
#endif
''',
        encoding="utf-8",
    )

    print_state_impl_h.write_text(
        r'''#pragma once

#include "kp3s_print_state.h"

#if ENABLED(KP3S_SMART_UI)
  static bool kp3s_serial_job_active = false;
  static bool kp3s_serial_job_paused = false;
  static millis_t kp3s_serial_job_last_activity = 0;

  static void kp3s_normalize_serial_line(char *command) {
    for (char *p = command; *p; ++p) {
      if (*p == ';' || *p == '*') { *p = '\0'; break; }
      if (*p >= 'a' && *p <= 'z') *p = char(*p - ('a' - 'A'));
    }
  }

  static char *kp3s_find_code(char *command, const char code) {
    while (*command == ' ' || *command == '\t') ++command;
    if (*command == 'N') {
      ++command;
      while (NUMERIC_SIGNED(*command)) ++command;
    }
    while (*command == ' ' || *command == '\t') ++command;
    return *command == code ? command : nullptr;
  }

  static void kp3s_serial_job_touch(const millis_t now) {
    if (kp3s_serial_job_active) kp3s_serial_job_last_activity = now;
  }

  void kp3s_print_state_note_serial(const char *command, const millis_t now) {
    if (!command || !*command) return;

    char local[MAX_CMD_SIZE];
    strlcpy(local, command, sizeof(local));
    kp3s_normalize_serial_line(local);

    if (char * const g = kp3s_find_code(local, 'G')) {
      const long code = strtol(g + 1, nullptr, 10);
      const bool print_motion = code == 0 || code == 1
        || TERN0(ARC_SUPPORT, code == 2 || code == 3)
        || TERN0(BEZIER_CURVE_SUPPORT, code == 5);
      if (print_motion) {
        const bool has_extrusion = strchr(g, 'E') != nullptr;
        const bool has_machine_axis = strchr(g, 'X') || strchr(g, 'Y') || strchr(g, 'Z');
        if (has_extrusion && has_machine_axis) kp3s_serial_job_active = true;
        if (kp3s_serial_job_active) kp3s_serial_job_paused = false;
      }
      kp3s_serial_job_touch(now);
      return;
    }

    if (char * const m = kp3s_find_code(local, 'M')) {
      const long code = strtol(m + 1, nullptr, 10);
      switch (code) {
        case 75:
          kp3s_serial_job_active = true;
          kp3s_serial_job_paused = false;
          kp3s_serial_job_last_activity = now;
          break;
        case 0:
        case 1:
        case 25:
        case 76:
          if (kp3s_serial_job_active) {
            kp3s_serial_job_paused = true;
            kp3s_serial_job_last_activity = now;
          }
          break;
        case 24:
          if (kp3s_serial_job_active) {
            kp3s_serial_job_paused = false;
            kp3s_serial_job_last_activity = now;
          }
          break;
        case 2:
        case 18:
        case 30:
        case 77:
        case 84:
          kp3s_serial_job_active = false;
          kp3s_serial_job_paused = false;
          kp3s_serial_job_last_activity = 0;
          break;
        default:
          if (code == 104 || code == 106 || code == 107 || code == 109
           || code == 140 || code == 190 || code == 204 || code == 205
           || code == 220 || code == 221 || code == 400 || code == 593
           || code == 600 || code == 701 || code == 702 || code == 900)
            kp3s_serial_job_touch(now);
          break;
      }
    }
  }

  bool kp3s_serial_printing(const millis_t now) {
    if (!kp3s_serial_job_active || kp3s_serial_job_paused) return false;
    if (kp3s_serial_job_last_activity
        && ELAPSED(now, kp3s_serial_job_last_activity + KP3S_SERIAL_JOB_IDLE_TIMEOUT_MS)) {
      kp3s_serial_job_active = false;
      kp3s_serial_job_paused = false;
      kp3s_serial_job_last_activity = 0;
      return false;
    }
    return true;
  }

  bool kp3s_serial_print_paused() { return kp3s_serial_job_active && kp3s_serial_job_paused; }
#endif
''',
        encoding="utf-8",
    )
    print("[OK] Create generic serial print-state detector")

    replace_once(
        queue_cpp,
        '#include "../MarlinCore.h"\n',
        '#include "../MarlinCore.h"\n#if ENABLED(KP3S_SMART_UI)\n  #include "../feature/kp3s_print_state.h"\n#endif\n',
        "Include serial print-state detector in G-code queue",
    )
    replace_once(
        queue_cpp,
        '''        // Add the command to the queue
        ring_buffer.enqueue(serial.line_buffer, false OPTARG(HAS_MULTI_SERIAL, p));
''',
        '''        #if ENABLED(KP3S_SMART_UI)
          kp3s_print_state_note_serial(command, millis());
        #endif

        // Add the command to the queue
        ring_buffer.enqueue(serial.line_buffer, false OPTARG(HAS_MULTI_SERIAL, p));
''',
        "Detect streamed print commands before enqueue",
    )

    replace_once(
        eeprom_gcode,
        '#include "../../inc/MarlinConfig.h"\n',
        '#include "../../inc/MarlinConfig.h"\n#include "../../MarlinCore.h"\n#if ENABLED(KP3S_SMART_UI)\n  #include "../../feature/kp3s_print_state.h"\n#endif\n',
        "Include V1 runtime state in EEPROM G-code",
    )
    replace_once(
        eeprom_gcode,
        '/**\n * M500: Store settings in EEPROM\n */\n',
        '''static bool kp3s_eeprom_mutation_busy() {\n  bool busy = printer_busy() || printingIsPaused();\n  #if ENABLED(KP3S_SMART_UI)\n    busy |= kp3s_serial_printing() || kp3s_serial_print_paused();\n  #endif\n  return busy;\n}\n\n/**\n * M500: Store settings in EEPROM\n */\n''',
        "Create guarded EEPROM mutation state",
    )
    for code in ("M500", "M501", "M502"):
        replace_once(
            eeprom_gcode,
            f'''void GcodeSuite::{code}() {{\n''',
            f'''void GcodeSuite::{code}() {{\n  if (kp3s_eeprom_mutation_busy()) {{\n    SERIAL_ERROR_MSG("{code} blocked while printer is active");\n    return;\n  }}\n''',
            f"Block {code} while printer is active",
        )

    set_define(
        settings_cpp,
        "EEPROM_VERSION",
        '#define EEPROM_VERSION "V10"',
        "Set V1 EEPROM schema",
    )
    replace_once(
        settings_cpp,
        '#include "../lcd/marlinui.h"\n',
        '#include "../lcd/marlinui.h"\n#if ENABLED(KP3S_RUNTIME_DISPLAY)\n  #include "../feature/kp3s_display_runtime.h"\n#endif\n#if ENABLED(KP3S_MPU6050)\n  #include "../feature/kp3s_mpu6050.h"\n#endif\n#if ENABLED(KP3S_RUNTIME_BLTOUCH)\n  #include "../feature/kp3s_bltouch_runtime.h"\n#endif\n',
        "Include persistent KP3S runtime settings",
    )
    insert_before_regex_once(
        settings_cpp,
        r"^} SettingsData;\s*$",
        '''  // KP3S V1 persistent hardware / UI options
  #if ENABLED(KP3S_RUNTIME_DISPLAY)
    bool kp3s_display_flipped;
  #endif
  #if ENABLED(KP3S_RUNTIME_BLTOUCH)
    bool kp3s_bltouch_enabled;
  #endif
  #if ENABLED(KP3S_MPU6050)
    bool kp3s_mpu6050_enabled;
    bool kp3s_mpu6050_swap_lines;
    float kp3s_mpu6050_temp_offset_c;
    float kp3s_mpu6050_level_zero_roll_deg;
    float kp3s_mpu6050_level_zero_pitch_deg;
    bool kp3s_mpu6050_level_zero_valid;
  #endif

''',
        "Add KP3S runtime options to EEPROM layout",
    )
    insert_before_regex_once(
        settings_cpp,
        r"^[ \t]*// Report final CRC and Data Size\s*$",
        '''    // KP3S V1 persistent hardware / UI options
    #if ENABLED(KP3S_RUNTIME_DISPLAY)
      _FIELD_TEST(kp3s_display_flipped);
      EEPROM_WRITE(kp3s_display_flipped);
    #endif
    #if ENABLED(KP3S_RUNTIME_BLTOUCH)
      _FIELD_TEST(kp3s_bltouch_enabled);
      EEPROM_WRITE(kp3s_bltouch_runtime_enabled);
    #endif
    #if ENABLED(KP3S_MPU6050)
      _FIELD_TEST(kp3s_mpu6050_enabled);
      EEPROM_WRITE(kp3s_mpu6050_runtime_enabled);
      _FIELD_TEST(kp3s_mpu6050_swap_lines);
      EEPROM_WRITE(kp3s_mpu6050_swap_lines);
      _FIELD_TEST(kp3s_mpu6050_temp_offset_c);
      EEPROM_WRITE(kp3s_mpu6050_temp_offset_c);
      _FIELD_TEST(kp3s_mpu6050_level_zero_roll_deg);
      EEPROM_WRITE(kp3s_mpu6050_level_zero_roll_deg);
      _FIELD_TEST(kp3s_mpu6050_level_zero_pitch_deg);
      EEPROM_WRITE(kp3s_mpu6050_level_zero_pitch_deg);
      _FIELD_TEST(kp3s_mpu6050_level_zero_valid);
      EEPROM_WRITE(kp3s_mpu6050_level_zero_valid);
    #endif

    //
''',
        "Save KP3S runtime options in EEPROM",
    )
    insert_before_regex_once(
        settings_cpp,
        r"^[ \t]*// Validate Final Size and CRC\s*$",
        '''      // KP3S V1 persistent hardware / UI options
      #if ENABLED(KP3S_RUNTIME_DISPLAY)
      {
        bool stored_display_flipped;
        _FIELD_TEST(kp3s_display_flipped);
        EEPROM_READ(stored_display_flipped);
        if (!validating) kp3s_display_flipped = stored_display_flipped;
      }
      #endif
      #if ENABLED(KP3S_RUNTIME_BLTOUCH)
      {
        bool stored_bltouch_enabled;
        _FIELD_TEST(kp3s_bltouch_enabled);
        EEPROM_READ(stored_bltouch_enabled);
        if (!validating) kp3s_bltouch_runtime_enabled = stored_bltouch_enabled;
      }
      #endif
      #if ENABLED(KP3S_MPU6050)
      {
        bool stored_mpu6050_enabled, stored_mpu6050_swap_lines, stored_level_zero_valid;
        float stored_temp_offset_c, stored_zero_roll, stored_zero_pitch;
        _FIELD_TEST(kp3s_mpu6050_enabled);
        EEPROM_READ(stored_mpu6050_enabled);
        _FIELD_TEST(kp3s_mpu6050_swap_lines);
        EEPROM_READ(stored_mpu6050_swap_lines);
        _FIELD_TEST(kp3s_mpu6050_temp_offset_c);
        EEPROM_READ(stored_temp_offset_c);
        _FIELD_TEST(kp3s_mpu6050_level_zero_roll_deg);
        EEPROM_READ(stored_zero_roll);
        _FIELD_TEST(kp3s_mpu6050_level_zero_pitch_deg);
        EEPROM_READ(stored_zero_pitch);
        _FIELD_TEST(kp3s_mpu6050_level_zero_valid);
        EEPROM_READ(stored_level_zero_valid);
        if (!validating) {
          kp3s_mpu6050_runtime_enabled = stored_mpu6050_enabled;
          kp3s_mpu6050_swap_lines = stored_mpu6050_swap_lines;
          kp3s_mpu6050_temp_offset_c = stored_temp_offset_c;
          kp3s_mpu6050_level_zero_roll_deg = stored_zero_roll;
          kp3s_mpu6050_level_zero_pitch_deg = stored_zero_pitch;
          kp3s_mpu6050_level_zero_valid = stored_level_zero_valid;
        }
      }
      #endif

      //
''',
        "Load KP3S runtime options from EEPROM",
    )
    replace_once(
        settings_cpp,
        '''  TERN_(HAS_LCD_CONTRAST, ui.refresh_contrast());\n  TERN_(HAS_LCD_BRIGHTNESS, ui.refresh_brightness());\n  TERN_(HAS_BACKLIGHT_TIMEOUT, ui.refresh_backlight_timeout());\n  TERN_(HAS_DISPLAY_SLEEP, ui.refresh_screen_timeout());\n}\n''',
        '''  TERN_(HAS_LCD_CONTRAST, ui.refresh_contrast());\n  TERN_(HAS_LCD_BRIGHTNESS, ui.refresh_brightness());\n  TERN_(HAS_BACKLIGHT_TIMEOUT, ui.refresh_backlight_timeout());\n  TERN_(HAS_DISPLAY_SLEEP, ui.refresh_screen_timeout());\n  #if ENABLED(KP3S_RUNTIME_DISPLAY)\n    kp3s_display_apply_rotation();\n  #endif\n  #if ENABLED(KP3S_MPU6050)\n    // During startup settings are loaded before the main runtime loop. Defer\n    // sensor re-initialization so the first normal UI cycle uses the loaded\n    // enable/wiring state exactly once. Runtime M501/M502 applies immediately.\n    if (IsRunning()) kp3s_mpu6050_set_enabled(kp3s_mpu6050_runtime_enabled);\n  #endif\n  #if ENABLED(KP3S_RUNTIME_BLTOUCH)\n    // settings.first_load() runs before servo/probe initialization. Never move\n    // BLTouch from here during boot. Runtime loads may apply/stow safely.\n    if (IsRunning()) kp3s_bltouch_runtime_apply(/*stow_when_disabling=*/true);\n  #endif\n}\n''',
        "Apply KP3S runtime options after EEPROM load/reset",
    )
    replace_once(
        settings_cpp,
        '''  //\n  // LCD Contrast\n  //\n  TERN_(HAS_LCD_CONTRAST, ui.contrast = LCD_CONTRAST_DEFAULT);\n''',
        '''  //\n  // KP3S Marlin Firmware V1 runtime hardware/UI defaults\n  //\n  #if ENABLED(KP3S_RUNTIME_DISPLAY)\n    kp3s_display_flipped = false;\n  #endif\n  #if ENABLED(KP3S_RUNTIME_BLTOUCH)\n    kp3s_bltouch_runtime_enabled = false;\n  #endif\n  #if ENABLED(KP3S_MPU6050)\n    kp3s_mpu6050_runtime_enabled = true;\n    kp3s_mpu6050_swap_lines = false;\n    kp3s_mpu6050_temp_offset_c = 0.0f;\n    kp3s_mpu6050_level_zero_roll_deg = 0.0f;\n    kp3s_mpu6050_level_zero_pitch_deg = 0.0f;\n    kp3s_mpu6050_level_zero_valid = false;\n  #endif\n\n  //\n  // LCD Contrast\n  //\n  TERN_(HAS_LCD_CONTRAST, ui.contrast = LCD_CONTRAST_DEFAULT);\n''',
        "Reset KP3S runtime options to safe defaults",
    )
    print("[OK] Persist display rotation, BLTouch state, MPU enable/wiring and IMU calibration in EEPROM")

    ui_context_h.write_text(
        r'''/**
 * KP3S Marlin Firmware UI navigation context.
 *
 * Normal menus are vertical. Two-choice confirmation screens and numeric
 * edit screens are horizontal when driven by the Samsung 4-way JOG.
 */
#pragma once

#include "../inc/MarlinConfigPre.h"

#if ENABLED(KP3S_CONTEXT_NAVIGATION)
  extern bool kp3s_ui_selection_mode;
  extern bool kp3s_ui_edit_mode;
#endif
''',
        encoding="utf-8",
    )
    print("[OK] Create context-aware UI navigation state")

    replace_once(
        menu_cpp,
        '#include "menu.h"\n',
        '#include "menu.h"\n#if ENABLED(KP3S_CONTEXT_NAVIGATION)\n  #include "../../feature/kp3s_ui_context.h"\n#endif\n',
        "Include KP3S UI navigation context",
    )
    replace_once(
        menu_cpp,
        'uint8_t screen_history_depth = 0;\n',
        'uint8_t screen_history_depth = 0;\n\n#if ENABLED(KP3S_CONTEXT_NAVIGATION)\n  bool kp3s_ui_selection_mode = false;\n  bool kp3s_ui_edit_mode = false;\n#endif\n',
        "Define KP3S UI navigation context",
    )
    replace_once(
        menu_cpp,
        ') {\n  TERN_(HAS_TOUCH_BUTTONS, ui.on_edit_screen = true);\n',
        ') {\n  #if ENABLED(KP3S_CONTEXT_NAVIGATION)\n    kp3s_ui_selection_mode = false;\n    kp3s_ui_edit_mode = true;\n  #endif\n  TERN_(HAS_TOUCH_BUTTONS, ui.on_edit_screen = true);\n',
        "Mark value-edit screens as horizontal",
    )
    replace_once(
        menu_cpp,
        '  if (currentScreen == screen) return;\n\n  wake_display();\n',
        '  if (currentScreen == screen) return;\n\n  #if ENABLED(KP3S_CONTEXT_NAVIGATION)\n    kp3s_ui_selection_mode = false;\n    kp3s_ui_edit_mode = false;\n  #endif\n\n  wake_display();\n',
        "Reset KP3S UI navigation context when changing screens",
    )
    replace_once(
        menu_cpp,
        ') {\n  ui.defer_status_screen();\n  const bool ui_selection = !yes ? false : !no || ui.update_selection(),\n',
        ') {\n  #if ENABLED(KP3S_CONTEXT_NAVIGATION)\n    kp3s_ui_selection_mode = true;\n    kp3s_ui_edit_mode = false;\n  #endif\n  ui.defer_status_screen();\n  const bool ui_selection = !yes ? false : !no || ui.update_selection(),\n',
        "Mark two-choice confirmation screens as horizontal",
    )

    bltouch_runtime_h.write_text(
        r'''#pragma once

#include "../inc/MarlinConfig.h"

#if ENABLED(KP3S_RUNTIME_BLTOUCH)
  #include "bltouch.h"
  #include "bedlevel/bedlevel.h"

  extern bool kp3s_bltouch_runtime_enabled;

  inline void kp3s_bltouch_runtime_apply(const bool stow_when_disabling=false) {
    if (kp3s_bltouch_runtime_enabled)
      bltouch.init(/*set_voltage=*/true);
    else {
      set_bed_leveling_enabled(false);
      if (stow_when_disabling) bltouch._stow();
    }
  }
#endif
''',
        encoding="utf-8",
    )
    print("[OK] Create runtime BLTouch control")

    replace_once(
        menu_config,
        '#include "../../module/temperature.h"\n',
        '#include "../../module/temperature.h"\n#if ENABLED(EEPROM_SETTINGS)\n  #include "../../module/settings.h"\n#endif\n#if ENABLED(KP3S_SMART_UI)\n  #include "../../feature/kp3s_ui_text.h"\n  #include "../../feature/kp3s_print_state.h"\n#endif\n\n#if ENABLED(KP3S_RUNTIME_BLTOUCH)\n  #include "../../feature/kp3s_bltouch_runtime.h"\n  #include "../../feature/bedlevel/bedlevel.h"\n#endif\n#if ENABLED(KP3S_RUNTIME_DISPLAY)\n  #include "../../feature/kp3s_display_runtime.h"\n#endif\n#if ENABLED(KP3S_MPU6050)\n  #include "../../feature/kp3s_mpu6050.h"\n  #include "../../module/motion.h"\n  #include "../../gcode/gcode.h"\n#endif\n',
        "Include KP3S runtime controls in menu",
    )
    # V1 menu organization: keep runtime controls under one compact KP3S entry
    # instead of scattering duplicate controls across Configuration.
    replace_once(
        menu_config,
        '  SUBMENU(MSG_ADVANCED_SETTINGS, menu_advanced_settings);\n',
        '  SUBMENU_F(kp3s_tr(F("KP3S Setup"), F("Ajustes KP3S"), F("Ajustes KP3S"), F("Reglages KP3S"), F("Einst. KP3S")), menu_kp3s_v1_settings);\n',
        "Group runtime and advanced settings under KP3S Setup",
    )
    replace_once(
        menu_config,
        '''  #if ENABLED(FWRETRACT)
    SUBMENU(MSG_RETRACT, menu_config_retract);
  #endif
''',
        '''  // Firmware Retract is grouped under KP3S Setup.
''',
        "Group Firmware Retract under KP3S Setup",
    )
    replace_once(
        menu_config,
        '''  #if HAS_FILAMENT_SENSOR
    EDIT_ITEM(bool, MSG_RUNOUT_SENSOR, &runout.enabled, runout.reset);
  #endif
''',
        '''  // Filament Runout is grouped under KP3S Setup.
''',
        "Group filament runout under KP3S Setup",
    )
    replace_once(
        menu_config,
        '''  #if ENABLED(POWER_LOSS_RECOVERY)
    EDIT_ITEM(bool, MSG_OUTAGE_RECOVERY, &recovery.enabled, recovery.changed);
    #if HAS_PLR_BED_THRESHOLD
      EDIT_ITEM(int3, MSG_RESUME_BED_TEMP, &recovery.bed_temp_threshold, 0, BED_MAX_TARGET);
    #endif
  #endif
''',
        '''  // Power-loss recovery is grouped under KP3S Setup.
''',
        "Group power-loss recovery under KP3S Setup",
    )

    replace_once(
        menu_config,
        '''  #if HAS_LCD_BRIGHTNESS
    EDIT_ITEM_FAST(uint8, MSG_BRIGHTNESS, &ui.brightness, LCD_BRIGHTNESS_MIN, LCD_BRIGHTNESS_MAX, ui.refresh_brightness, true);
  #endif
  #if HAS_LCD_CONTRAST && LCD_CONTRAST_MIN < LCD_CONTRAST_MAX
    EDIT_ITEM_FAST(uint8, MSG_CONTRAST, &ui.contrast, LCD_CONTRAST_MIN, LCD_CONTRAST_MAX, ui.refresh_contrast, true);
  #endif
''',
        '''  // Display controls are grouped under KP3S Setup > Display.
''',
        "Group display controls under KP3S Setup",
    )
    replace_once(
        menu_config,
        '''  #if ENABLED(EDITABLE_DISPLAY_TIMEOUT)
    #if HAS_BACKLIGHT_TIMEOUT
      EDIT_ITEM(uint8, MSG_SCREEN_TIMEOUT, &ui.backlight_timeout_minutes, ui.backlight_timeout_min, ui.backlight_timeout_max, ui.refresh_backlight_timeout);
    #elif HAS_DISPLAY_SLEEP
      EDIT_ITEM(uint8, MSG_SCREEN_TIMEOUT, &ui.sleep_timeout_minutes, ui.sleep_timeout_min, ui.sleep_timeout_max, ui.refresh_screen_timeout);
    #endif
  #endif
''',
        '''  // Display timeout is grouped under KP3S Setup > Display.
''',
        "Group display timeout under KP3S Setup",
    )
    replace_once(
        menu_config,
        '''  #if ENABLED(EEPROM_SETTINGS)
    ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);
    if (!busy) ACTION_ITEM(MSG_LOAD_EEPROM, ui.load_settings);
  #endif

  if (!busy) ACTION_ITEM(MSG_RESTORE_DEFAULTS, ui.reset_settings);
''',
        '''  // EEPROM actions are grouped under KP3S Setup > Storage.
''',
        "Group EEPROM actions under KP3S Setup",
    )

    replace_once(
        menu_config,
        'void menu_configuration() {\n',
        '''static bool kp3s_runtime_machine_busy() {
  bool busy = printer_busy() || printingIsPaused();
  #if ENABLED(KP3S_SMART_UI)
    busy |= kp3s_serial_printing() || kp3s_serial_print_paused();
  #endif
  return busy;
}

#if ENABLED(KP3S_RUNTIME_BLTOUCH) && ENABLED(BLTOUCH)
  static void kp3s_runtime_bltouch_changed() {
    kp3s_bltouch_runtime_apply(/*stow_when_disabling=*/true);
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
    ui.refresh();
  }
#endif

#if ENABLED(KP3S_RUNTIME_DISPLAY)
  static void kp3s_display_rotation_changed() {
    kp3s_display_apply_rotation();
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
  }
#endif

#if ENABLED(KP3S_MPU6050)
  static void kp3s_mpu6050_changed() {
    kp3s_mpu6050_set_enabled(kp3s_mpu6050_runtime_enabled);
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
  }
  static void kp3s_mpu6050_wiring_changed() {
    kp3s_mpu6050_set_swap_lines(kp3s_mpu6050_swap_lines);
    // SDA/SCL orientation is a permanent machine wiring choice. Save it now.
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
  }
  static void kp3s_mpu6050_calibration_changed() {
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
  }

  // Shared capacity for every dynamic MPU/IMU line rendered by this menu block.
  // Keep this declaration before the first screen that allocates one of these
  // buffers so the generated C++ is valid independently of helper order.
  static constexpr uint8_t KP3S_MPU_UI_LINE_CAP = 24;

  static bool kp3s_mpu_zero_saved = false, kp3s_mpu_zero_attempted = false;
  static void kp3s_format_angle(char * const out, const char axis, const float angle);

  static void screen_kp3s_mpu_zero_calibration() {
    float raw_roll=0, raw_pitch=0;
    char xline[KP3S_MPU_UI_LINE_CAP], yline[KP3S_MPU_UI_LINE_CAP];
    const bool raw_ok = kp3s_mpu6050_level_raw(raw_roll, raw_pitch);
    const bool stable = kp3s_mpu6050_motion_stable();
    // Once stable, show the same settled candidate that OK will persist. While
    // moving, keep showing the instantaneous raw fused angles in real time.
    if (stable) kp3s_mpu6050_level_zero_candidate(raw_roll, raw_pitch);

    if (ui.use_click()) {
      if (kp3s_mpu_zero_saved) {
        kp3s_mpu_zero_saved = kp3s_mpu_zero_attempted = false;
        return ui.goto_previous_screen();
      }
      kp3s_mpu_zero_attempted = true;
      if (raw_ok && stable && kp3s_mpu6050_set_level_zero()) {
        kp3s_mpu_zero_saved = true;
        kp3s_mpu6050_calibration_changed();
      }
    }

    if (raw_ok) {
      kp3s_format_angle(xline, 'X', raw_roll);
      kp3s_format_angle(yline, 'Y', raw_pitch);
    }
    else { strcpy_P(xline, PSTR("X: --.-")); strcpy_P(yline, PSTR("Y: --.-")); }

    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("CALIBRATE ZERO"), F("CALIBRAR ZERO"), F("CALIBRAR CERO"), F("CALIBRER ZERO"), F("NULL KALIBR.")), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(xline, SS_CENTER);
    STATIC_ITEM_C(yline, SS_CENTER);
    if (kp3s_mpu_zero_saved)
      STATIC_ITEM_F(kp3s_tr(F("SAVED - OK BACK"), F("SALVO - OK VOLTA"), F("GUARD. - OK VOLV"), F("SAUVE - OK RET."), F("GESPEI. - OK ZUR")), SS_CENTER);
    else if (!raw_ok)
      STATIC_ITEM_F(kp3s_tr(F("NO MPU DATA"), F("SEM DADOS MPU"), F("SIN DATOS MPU"), F("PAS DONNEES MPU"), F("KEINE MPU DAT.")), SS_CENTER);
    else if (!stable)
      STATIC_ITEM_F(kp3s_mpu_zero_attempted
        ? kp3s_tr(F("STILL - TRY OK"), F("PARE - TENTE OK"), F("QUIETO - OK"), F("IMMOBILE - OK"), F("STILL - OK"))
        : kp3s_tr(F("WAIT UNTIL STILL"), F("AGUARDE PARADO"), F("ESPERE QUIETO"), F("RESTER IMMOBILE"), F("STILL HALTEN")), SS_CENTER);
    else
      STATIC_ITEM_F(kp3s_tr(F("OK = SAVE ZERO"), F("OK = GRAVAR ZERO"), F("OK = GUARDAR"), F("OK = SAUVER ZERO"), F("OK = NULL SPEICH.")), SS_CENTER);
    END_SCREEN();

    // Keep the calibration values genuinely live. CALL_REDRAW_NEXT must be
    // re-armed on every invocation; a one-shot timed refresh freezes after the
    // following draw in Marlin's menu state machine.
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void kp3s_open_mpu_zero_calibration() {
    kp3s_mpu_zero_saved = kp3s_mpu_zero_attempted = false;
    ui.push_current_screen();
    ui.goto_screen(screen_kp3s_mpu_zero_calibration);
  }

  static void kp3s_run_mpu_clear_zero() {
    kp3s_mpu6050_clear_level_zero();
    kp3s_mpu6050_calibration_changed();
    ui.refresh();
  }

  static KP3SMPU6050BusStatus kp3s_mpu_bus_test_result = KP3SMPU6050BusStatus::DISABLED;
  static bool kp3s_mpu_detect_test_result = false;

  static void kp3s_format_angle(char * const out, const char axis, const float angle) {
    const int16_t tenths = int16_t(angle * 10.0f + (angle >= 0 ? 0.5f : -0.5f));
    const uint16_t mag = uint16_t(tenths < 0 ? -tenths : tenths);
    snprintf_P(out, KP3S_MPU_UI_LINE_CAP, PSTR("%c:%c%u.%u"), axis, tenths < 0 ? '-' : '+', unsigned(mag / 10), unsigned(mag % 10));
  }

  static void kp3s_format_mpu_temperature(char * const out, const float temperature_c) {
    const int16_t tenths = int16_t(temperature_c * 10.0f + (temperature_c >= 0 ? 0.5f : -0.5f));
    const uint16_t mag = uint16_t(tenths < 0 ? -tenths : tenths);
    snprintf_P(out, KP3S_MPU_UI_LINE_CAP, PSTR("T:%c%u.%u C"), tenths < 0 ? '-' : '+', unsigned(mag / 10), unsigned(mag % 10));
  }

  static void screen_kp3s_mpu_bus_test() {
    if (ui.use_click()) return ui.goto_previous_screen();
    char addr[KP3S_MPU_UI_LINE_CAP];
    const uint8_t a = kp3s_mpu6050_last_bus_address();
    if (a) snprintf_P(addr, sizeof(addr), PSTR("I2C: 0x%02X"), unsigned(a));
    else strcpy_P(addr, PSTR("I2C: --"));

    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("I2C CHECK"), F("TESTE I2C"), F("PRUEBA I2C"), F("TEST I2C"), F("I2C TEST")), SS_CENTER | SS_INVERT);
    switch (kp3s_mpu_bus_test_result) {
      case KP3SMPU6050BusStatus::OK:
        STATIC_ITEM_F(kp3s_tr(F("BUS OK"), F("BARRA OK"), F("BUS OK"), F("BUS OK"), F("BUS OK")), SS_CENTER); break;
      case KP3SMPU6050BusStatus::DISABLED:
        STATIC_ITEM_F(kp3s_tr(F("MPU DISABLED"), F("MPU DESATIV."), F("MPU DESACT."), F("MPU INACTIF"), F("MPU INAKTIV")), SS_CENTER); break;
      case KP3SMPU6050BusStatus::SDA_STUCK_LOW:
        STATIC_ITEM_F(kp3s_tr(F("SDA STUCK"), F("SDA TRAVADA"), F("SDA BLOQUEA"), F("SDA BLOQUEE"), F("SDA BLOCK.")), SS_CENTER); break;
      case KP3SMPU6050BusStatus::SCL_STUCK_LOW:
        STATIC_ITEM_F(kp3s_tr(F("SCL STUCK"), F("SCL TRAVADA"), F("SCL BLOQUEA"), F("SCL BLOQUEE"), F("SCL BLOCK.")), SS_CENTER); break;
      default:
        STATIC_ITEM_F(kp3s_tr(F("NO I2C ACK"), F("SEM ACK I2C"), F("SIN ACK I2C"), F("PAS ACK I2C"), F("KEIN I2C ACK")), SS_CENTER); break;
    }
    STATIC_ITEM_C(addr, SS_CENTER);
    STATIC_ITEM_F(kp3s_tr(F("OK = BACK"), F("OK = VOLTAR"), F("OK = VOLVER"), F("OK = RETOUR"), F("OK = ZURUCK")), SS_CENTER);
    END_SCREEN();
  }

  static void kp3s_run_mpu_bus_test() {
    kp3s_mpu_bus_test_result = kp3s_mpu6050_test_bus();
    ui.push_current_screen();
    ui.goto_screen(screen_kp3s_mpu_bus_test);
  }

  static void screen_kp3s_mpu_detect_test() {
    if (ui.use_click()) return ui.goto_previous_screen();
    char identity[KP3S_MPU_UI_LINE_CAP];
    const uint8_t bus_addr = kp3s_mpu6050_address() ? kp3s_mpu6050_address() : kp3s_mpu6050_last_bus_address();
    if (bus_addr && kp3s_mpu6050_who_valid())
      snprintf_P(identity, sizeof(identity), PSTR("I2C:%02X ID:%02X"), unsigned(bus_addr), unsigned(kp3s_mpu6050_who_am_i()));
    else if (bus_addr)
      snprintf_P(identity, sizeof(identity), PSTR("I2C:%02X ID:--"), unsigned(bus_addr));
    else
      strcpy_P(identity, PSTR("I2C:-- ID:--"));

    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("DETECT MPU"), F("DETECTAR MPU"), F("DETECTAR MPU"), F("DETECTER MPU"), F("MPU PRUEFEN")), SS_CENTER | SS_INVERT);
    STATIC_ITEM_F(!kp3s_mpu6050_runtime_enabled
      ? kp3s_tr(F("MPU DISABLED"), F("MPU DESATIV."), F("MPU DESACT."), F("MPU INACTIF"), F("MPU INAKTIV"))
      : (kp3s_mpu_detect_test_result
          ? kp3s_tr(F("MPU + DATA OK"), F("MPU + DADOS OK"), F("MPU + DATOS OK"), F("MPU + DONNEES"), F("MPU + DATEN OK"))
          : (bus_addr
              ? kp3s_tr(F("I2C, NO MPU DATA"), F("I2C, SEM DADOS"), F("I2C, SIN DATOS"), F("I2C, PAS DONN."), F("I2C, KEIN DAT."))
              : kp3s_tr(F("NO I2C DEVICE"), F("SEM DISP. I2C"), F("SIN DISP. I2C"), F("PAS DISP. I2C"), F("KEIN I2C GER.")))), SS_CENTER);
    STATIC_ITEM_C(identity, SS_CENTER);
    STATIC_ITEM_F(kp3s_tr(F("OK = BACK"), F("OK = VOLTAR"), F("OK = VOLVER"), F("OK = RETOUR"), F("OK = ZURUCK")), SS_CENTER);
    END_SCREEN();
  }

  static void kp3s_run_mpu_detect_test() {
    kp3s_mpu_detect_test_result = kp3s_mpu6050_detect_now();
    ui.push_current_screen();
    ui.goto_screen(screen_kp3s_mpu_detect_test);
  }

  static void screen_kp3s_digital_level() {
    if (ui.use_click()) return ui.goto_previous_screen();
    float roll = 0, pitch = 0, rms = 0, peak = 0, instant = 0;
    char xline[KP3S_MPU_UI_LINE_CAP], yline[KP3S_MPU_UI_LINE_CAP], state_line[KP3S_MPU_UI_LINE_CAP];
    const bool ok = kp3s_mpu6050_level(roll, pitch);
    const bool motion_ok = kp3s_mpu6050_motion(rms, peak, instant);
    if (ok) {
      kp3s_format_angle(xline, 'X', roll);
      kp3s_format_angle(yline, 'Y', pitch);
    }
    else { strcpy_P(xline, PSTR("X: --.-")); strcpy_P(yline, PSTR("Y: --.-")); }

    const bool leveled = ok && WITHIN(roll, -0.5f, 0.5f) && WITHIN(pitch, -0.5f, 0.5f);
    if (!kp3s_mpu6050_runtime_enabled)
      strcpy_P(state_line, FTOP(kp3s_tr(F("MPU OFF"), F("MPU DESL."), F("MPU APAG."), F("MPU ARRET"), F("MPU AUS"))));
    else if (!ok)
      strcpy_P(state_line, FTOP(kp3s_tr(F("NO MPU DATA"), F("SEM DADOS MPU"), F("SIN DATOS MPU"), F("PAS DONNEES"), F("KEINE DATEN"))));
    else if (!kp3s_mpu6050_motion_stable())
      strcpy_P(state_line, FTOP(kp3s_tr(F("LIVE / MOVING"), F("AO VIVO/MOV."), F("EN VIVO/MOV."), F("LIVE/MOUV."), F("LIVE/BEWEGT"))));
    else
      strcpy_P(state_line, FTOP(leveled ? F("OK") : kp3s_tr(F("ADJUST BASE"), F("AJUSTE BASE"), F("AJUSTE BASE"), F("REGLER BASE"), F("BASIS JUST."))));
    if (motion_ok && strlen(state_line) < 10) {
      char v[8]; const uint16_t centi=uint16_t(_MIN(9.99f, rms)*100.0f+0.5f);
      snprintf_P(v,sizeof(v),PSTR(" V:%u.%02u"),unsigned(centi/100),unsigned(centi%100)); strlcat(state_line,v,KP3S_MPU_UI_LINE_CAP);
    }

    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("LIVE LEVEL"), F("NIVEL AO VIVO"), F("NIVEL EN VIVO"), F("NIVEAU LIVE"), F("LIVE NIVEAU")), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(xline, SS_CENTER);
    STATIC_ITEM_C(yline, SS_CENTER);
    STATIC_ITEM_C(state_line, SS_CENTER);
    END_SCREEN();

    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void screen_kp3s_mpu_motion() {
    if (ui.use_click()) return ui.goto_previous_screen();
    float rms=0, peak=0, instant=0;
    char rmsline[KP3S_MPU_UI_LINE_CAP], peakline[KP3S_MPU_UI_LINE_CAP], nowline[KP3S_MPU_UI_LINE_CAP];
    const bool ok=kp3s_mpu6050_motion(rms,peak,instant);
    if (ok) {
      const uint16_t r=uint16_t(_MIN(9.99f,rms)*100.0f+0.5f), p=uint16_t(_MIN(9.99f,peak)*100.0f+0.5f), n=uint16_t(_MIN(9.99f,instant)*100.0f+0.5f);
      snprintf_P(rmsline,sizeof(rmsline),PSTR("RMS:%u.%02ug"),unsigned(r/100),unsigned(r%100));
      snprintf_P(peakline,sizeof(peakline),PSTR("MAX:%u.%02ug"),unsigned(p/100),unsigned(p%100));
      snprintf_P(nowline,sizeof(nowline),PSTR("A:%u.%02ug %uHz"),unsigned(n/100),unsigned(n%100),unsigned(kp3s_mpu6050_sample_rate_hz()));
    }
    else { strcpy_P(rmsline,PSTR("RMS:--")); strcpy_P(peakline,PSTR("MAX:--")); strcpy_P(nowline,PSTR("A:--")); }
    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("TOOLHEAD IMU"), F("IMU CABECOTE"), F("IMU CABEZAL"), F("IMU TETE"), F("IMU KOPF")), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(rmsline, SS_CENTER);
    STATIC_ITEM_C(peakline, SS_CENTER);
    STATIC_ITEM_C(nowline, SS_CENTER);
    END_SCREEN();
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void screen_kp3s_startup_level() {
    if (ui.use_click()) return ui.goto_previous_screen();
    float roll=0,pitch=0; bool level_ok=false;
    char xline[KP3S_MPU_UI_LINE_CAP], yline[KP3S_MPU_UI_LINE_CAP];
    const bool ok=kp3s_mpu6050_startup_level(roll,pitch,level_ok);
    if (ok) { kp3s_format_angle(xline,'X',roll); kp3s_format_angle(yline,'Y',pitch); }
    else {
      const uint8_t pct = kp3s_mpu6050_startup_progress_pct();
      snprintf_P(xline,sizeof(xline),PSTR("PROG:%u%%"),unsigned(pct));
      strcpy_P(yline,PSTR("X/Y: ..."));
    }
    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("START LEVEL"), F("NIVEL INICIAL"), F("NIVEL INICIAL"), F("NIV. DEPART"), F("STARTNIVEAU")), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(xline,SS_CENTER);
    STATIC_ITEM_C(yline,SS_CENTER);
    STATIC_ITEM_F(!ok ? kp3s_tr(F("WAIT STILL"),F("AGUARDE PARADO"),F("ESPERE QUIETO"),F("RESTER FIXE"),F("STILL HALTEN"))
                      : (level_ok ? kp3s_tr(F("BASE LEVEL OK"),F("BASE NIVEL OK"),F("BASE NIVEL OK"),F("BASE A NIVEAU"),F("BASIS OK"))
                                  : kp3s_tr(F("ADJUST BASE"),F("AJUSTE BASE"),F("AJUSTE BASE"),F("REGLER BASE"),F("BASIS JUST."))),SS_CENTER);
    END_SCREEN();
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void screen_kp3s_mpu_temperature() {
    if (ui.use_click()) return ui.goto_previous_screen();
    float temp_c=0, raw_c=0, delta_c=0;
    char tline[KP3S_MPU_UI_LINE_CAP], off[KP3S_MPU_UI_LINE_CAP], delta[KP3S_MPU_UI_LINE_CAP];
    const bool ok=kp3s_mpu6050_temperature_c(temp_c), raw_ok=kp3s_mpu6050_temperature_raw_c(raw_c), delta_ok=kp3s_mpu6050_temperature_delta_c(delta_c);
    if (ok) kp3s_format_mpu_temperature(tline,temp_c); else strcpy_P(tline,PSTR("T: --.- C"));
    const int16_t off_t=int16_t(kp3s_mpu6050_temp_offset_c*10.0f+(kp3s_mpu6050_temp_offset_c>=0?0.5f:-0.5f));
    snprintf_P(off,sizeof(off),PSTR("OFF:%c%u.%uC"),off_t<0?'-':'+',unsigned(ABS(off_t)/10),unsigned(ABS(off_t)%10));
    if (delta_ok) { const int16_t d=int16_t(delta_c*10.0f+(delta_c>=0?0.5f:-0.5f)); snprintf_P(delta,sizeof(delta),PSTR("DT:%c%u.%uC"),d<0?'-':'+',unsigned(ABS(d)/10),unsigned(ABS(d)%10)); }
    else strcpy_P(delta,PSTR("DT: --.-C"));
    UNUSED(raw_ok); UNUSED(raw_c);
    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("IMU TEMP."),F("TEMP. IMU"),F("TEMP. IMU"),F("TEMP. IMU"),F("IMU TEMP.")),SS_CENTER|SS_INVERT);
    STATIC_ITEM_C(tline,SS_CENTER);
    STATIC_ITEM_C(off,SS_CENTER);
    STATIC_ITEM_C(delta,SS_CENTER);
    END_SCREEN();
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  enum class KP3SResonanceUIState : uint8_t { NONE, HOMING, RUNNING, APPLIED, LOW_CONF, HOME_FAIL, SAFE_Z_FAIL, BUSY, NO_MPU, NO_SPACE, CAPTURE_FAIL, SAVE_FAIL };
  static KP3SResonanceUIState kp3s_res_state = KP3SResonanceUIState::NONE;
  static AxisEnum kp3s_res_axis = X_AXIS;
  static float kp3s_res_frequency_hz = 0.0f;
  static uint8_t kp3s_res_confidence = 0;
  static uint16_t kp3s_res_sample_count = 0;

  static void screen_kp3s_resonance_result() {
    if (ui.use_click()) return ui.goto_previous_screen();
    char freq[KP3S_MPU_UI_LINE_CAP], conf[KP3S_MPU_UI_LINE_CAP];
    if (kp3s_res_frequency_hz > 0.0f) {
      const uint16_t fq = uint16_t(kp3s_res_frequency_hz * 10.0f + 0.5f);
      snprintf_P(freq, sizeof(freq), PSTR("%c:%u.%u Hz"), kp3s_res_axis == X_AXIS ? 'X' : 'Y', unsigned(fq/10), unsigned(fq%10));
      snprintf_P(conf, sizeof(conf), PSTR("CONF:%u%%"), unsigned(kp3s_res_confidence));
    }
    else {
      strcpy_P(freq, PSTR("FREQ: --.-"));
      if (kp3s_res_sample_count) snprintf_P(conf, sizeof(conf), PSTR("SAMP:%u"), unsigned(kp3s_res_sample_count));
      else strcpy_P(conf, PSTR("CONF: --"));
    }
    FSTR_P status = kp3s_tr(F("NO RESULT"),F("SEM RESULTADO"),F("SIN RESULTADO"),F("PAS RESULTAT"),F("KEIN ERGEB."));
    switch (kp3s_res_state) {
      case KP3SResonanceUIState::HOMING: status = kp3s_tr(F("HOMING..."),F("FAZENDO HOME..."),F("HACIENDO HOME"),F("ORIGINE..."),F("HOMING...")); break;
      case KP3SResonanceUIState::RUNNING: status = kp3s_tr(F("MEASURING..."),F("MEDINDO..."),F("MIDIENDO..."),F("MESURE..."),F("MESSUNG...")); break;
      case KP3SResonanceUIState::APPLIED: status = kp3s_tr(F("APPLIED+SAVED"),F("APLICADO+SALVO"),F("APLIC.+GUARD."),F("APPLIQUE+SAUV"),F("AKTIV+GESPEI.")); break;
      case KP3SResonanceUIState::LOW_CONF: status = kp3s_tr(F("LOW CONFIDENCE"),F("BAIXA CONFIANCA"),F("BAJA CONFIANZA"),F("FIABIL. FAIBLE"),F("WENIG SICHER")); break;
      case KP3SResonanceUIState::HOME_FAIL: status = kp3s_tr(F("HOME FAILED"),F("FALHA NO HOME"),F("FALLO HOME"),F("ECHEC ORIGINE"),F("HOME FEHLER")); break;
      case KP3SResonanceUIState::SAFE_Z_FAIL: status = kp3s_tr(F("SAFE Z FAILED"),F("FALHA Z SEGURO"),F("FALLO Z SEGURO"),F("ECHEC Z SUR"),F("Z SICHER FEHL.")); break;
      case KP3SResonanceUIState::BUSY: status = kp3s_tr(F("PRINTER BUSY"),F("IMPRESSORA OCUP."),F("IMPRESORA OCUP."),F("IMPRIMANTE OCC."),F("DRUCKER BELEGT")); break;
      case KP3SResonanceUIState::NO_MPU: status = kp3s_tr(F("NO MPU DATA"),F("SEM DADOS MPU"),F("SIN DATOS MPU"),F("PAS DONNEES MPU"),F("KEINE MPU DAT.")); break;
      case KP3SResonanceUIState::NO_SPACE: status = kp3s_tr(F("AXIS TOO CLOSE"),F("EIXO SEM ESPACO"),F("EJE SIN ESPACIO"),F("AXE SANS PLACE"),F("ACHSE ZU NAH")); break;
      case KP3SResonanceUIState::CAPTURE_FAIL: status = kp3s_tr(F("CAPTURE FAILED"),F("FALHA CAPTURA"),F("FALLO CAPTURA"),F("ECHEC CAPTURE"),F("MESSUNG FEHLER")); break;
      case KP3SResonanceUIState::SAVE_FAIL: status = kp3s_tr(F("APPLIED-SAVE FAIL"),F("APLIC.-FALHA SALV"),F("APLIC.-NO GUARD."),F("APPL.-SAUV ECHEC"),F("AKTIV-SPEICH.F.")); break;
      default: break;
    }
    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("RESONANCE TUNE"),F("AJUSTE RESSON."),F("AJUSTE RESON."),F("REGLAGE RESON."),F("RESONANZ TUNE")),SS_CENTER|SS_INVERT);
    STATIC_ITEM_C(freq,SS_CENTER);
    STATIC_ITEM_C(conf,SS_CENTER);
    STATIC_ITEM_F(status,SS_CENTER);
    END_SCREEN();
  }

  static void kp3s_run_resonance_axis(const AxisEnum axis) {
    kp3s_res_axis = axis;
    kp3s_res_frequency_hz = 0.0f;
    kp3s_res_confidence = 0;
    kp3s_res_sample_count = 0;

    // ACTION_ITEM doesn't push a screen automatically. Preserve the resonance
    // menu so BACK always returns one level, including preparation failures.
    ui.push_current_screen();

    bool resonance_busy = printingIsActive() || printingIsPaused() || planner.has_blocks_queued();
    #if ENABLED(KP3S_SMART_UI)
      resonance_busy |= kp3s_serial_printing(millis()) || kp3s_serial_print_paused();
    #endif
    if (resonance_busy) {
      kp3s_res_state=KP3SResonanceUIState::BUSY;
      ui.goto_screen(screen_kp3s_resonance_result); return;
    }
    if (!kp3s_mpu6050_detected() || !kp3s_mpu6050_sample().valid) {
      kp3s_res_state=KP3SResonanceUIState::NO_MPU;
      ui.goto_screen(screen_kp3s_resonance_result); return;
    }

    // The tuner owns preparation. Always establish a fresh mechanical XYZ
    // reference instead of requiring the user to home manually beforehand.
    kp3s_res_state = KP3SResonanceUIState::HOMING;
    ui.goto_screen(screen_kp3s_resonance_result);
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
    safe_delay(80);

    #if HAS_LEVELING
      const bool leveling_was_active = planner.leveling_active;
      set_bed_leveling_enabled(false);
    #endif

    gcode.process_subcommands_now(F("G28"));
    planner.synchronize();
    if (axis_should_home(X_AXIS) || axis_should_home(Y_AXIS) || axis_should_home(Z_AXIS)) {
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::HOME_FAIL;
      ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    // Move away from the bed automatically before any horizontal impulse.
    if (current_position.z < 10.0f) do_blocking_move_to_z(10.0f, 5.0f);
    planner.synchronize();
    if (current_position.z < 5.0f) {
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::SAFE_Z_FAIL;
      ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    const float amin = base_min_pos(axis) + 7.0f, amax = base_max_pos(axis) - 7.0f;
    if (amax - amin < 16.0f) {
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::NO_SPACE;
      ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }
    const float center = (amin + amax) * 0.5f;
    const float lo = center - 5.0f, hi = center + 5.0f;

    kp3s_res_state = KP3SResonanceUIState::RUNNING;
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);

    planner.synchronize();
    const float previous_shaping = stepper.get_shaping_frequency(axis);
    stepper.set_shaping_frequency(axis, 0.0f);

    // Prepare a repeatable, central starting point and let homing/positioning
    // vibration decay before opening the measurement window.
    if (axis == X_AXIS) do_blocking_move_to_x(center, 45.0f); else do_blocking_move_to_y(center, 45.0f);
    if (axis == X_AXIS) do_blocking_move_to_x(lo, 45.0f); else do_blocking_move_to_y(lo, 45.0f);
    safe_delay(200);
    kp3s_mpu6050_task(millis());

    if (!kp3s_mpu6050_detected() || !kp3s_mpu6050_sample().valid) {
      stepper.set_shaping_frequency(axis, previous_shaping);
      if (axis == X_AXIS) do_blocking_move_to_x(center, 45.0f); else do_blocking_move_to_y(center, 45.0f);
      planner.synchronize();
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::NO_MPU;
      ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    kp3s_mpu6050_resonance_capture_start();
    if (!kp3s_mpu6050_resonance_capturing()) {
      stepper.set_shaping_frequency(axis, previous_shaping);
      if (axis == X_AXIS) do_blocking_move_to_x(center, 45.0f); else do_blocking_move_to_y(center, 45.0f);
      planner.synchronize();
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::CAPTURE_FAIL;
      ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    // Queue the two broadband reversals instead of blocking on each one. The
    // stepper ISR performs motion while this loop services the IMU explicitly
    // every few milliseconds. This prevents LCD/safe_delay cadence from starving
    // a capture that is supposed to run at ~200 Hz.
    current_position[axis] = hi;
    line_to_current_position(120.0f);
    current_position[axis] = lo;
    line_to_current_position(120.0f);

    const millis_t capture_deadline = millis() + 1400UL;
    while (kp3s_mpu6050_resonance_capturing() && PENDING(millis(), capture_deadline)) {
      kp3s_mpu6050_task(millis());
      thermalManager.task();
      hal.watchdog_refresh();
      delay(1);
    }
    planner.synchronize();
    kp3s_res_sample_count = kp3s_mpu6050_resonance_samples();

    const bool analyzed = kp3s_mpu6050_resonance_capture_analyze(kp3s_res_frequency_hz, kp3s_res_confidence);
    stepper.set_shaping_frequency(axis, previous_shaping);
    if (axis == X_AXIS) do_blocking_move_to_x(center, 45.0f); else do_blocking_move_to_y(center, 45.0f);
    planner.synchronize();
    #if HAS_LEVELING
      set_bed_leveling_enabled(leveling_was_active);
    #endif

    const uint8_t required_confidence = axis == X_AXIS ? 45 : 60;
    if (analyzed && kp3s_res_confidence >= required_confidence) {
      stepper.set_shaping_frequency(axis, kp3s_res_frequency_hz);
      #if ENABLED(EEPROM_SETTINGS)
        kp3s_res_state = settings.save() ? KP3SResonanceUIState::APPLIED : KP3SResonanceUIState::SAVE_FAIL;
      #else
        kp3s_res_state = KP3SResonanceUIState::APPLIED;
      #endif
    }
    else kp3s_res_state = analyzed ? KP3SResonanceUIState::LOW_CONF : KP3SResonanceUIState::CAPTURE_FAIL;
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void kp3s_run_resonance_x() { kp3s_run_resonance_axis(X_AXIS); }
  static void kp3s_run_resonance_y() { kp3s_run_resonance_axis(Y_AXIS); }

  static void menu_kp3s_resonance_tuning() {
    START_MENU();
    BACK_ITEM(MSG_BACK);
    ACTION_ITEM_F(kp3s_tr(F("Auto Tune X"),F("Autoajuste X"),F("Autoajuste X"),F("Auto Reglage X"),F("Auto Tune X")),kp3s_run_resonance_x);
    ACTION_ITEM_F(kp3s_tr(F("Auto Tune Y (indirect)"),F("Autoajuste Y indireto"),F("Autoajuste Y indirecto"),F("Auto Y indirect"),F("Auto Y indirekt")),kp3s_run_resonance_y);
    SUBMENU_F(kp3s_tr(F("Last Result"),F("Ultimo Resultado"),F("Ultimo Resultado"),F("Dernier Resultat"),F("Letztes Ergebnis")),screen_kp3s_resonance_result);
    END_MENU();
  }

  static void menu_kp3s_mpu6050_settings() {
    START_MENU();
    BACK_ITEM(MSG_BACK);
    EDIT_ITEM_F(bool, kp3s_tr(F("Enabled"), F("Ativado"), F("Activado"), F("Active"), F("Aktiv")), &kp3s_mpu6050_runtime_enabled, kp3s_mpu6050_changed);
    EDIT_ITEM_F(bool, kp3s_tr(F("SDA/SCL Inv."), F("Inv. SDA/SCL"), F("Inv. SDA/SCL"), F("Inv. SDA/SCL"), F("SDA/SCL Inv.")), &kp3s_mpu6050_swap_lines, kp3s_mpu6050_wiring_changed);
    ACTION_ITEM_F(kp3s_tr(F("Test I2C Bus"), F("Testar I2C"), F("Probar I2C"), F("Tester I2C"), F("I2C Test")), kp3s_run_mpu_bus_test);
    ACTION_ITEM_F(kp3s_tr(F("Detect MPU"), F("Detectar MPU"), F("Detectar MPU"), F("Detecter MPU"), F("MPU Pruefen")), kp3s_run_mpu_detect_test);
    SUBMENU_F(kp3s_tr(F("Live Level"), F("Nivel ao Vivo"), F("Nivel en Vivo"), F("Niveau Live"), F("Live Niveau")), screen_kp3s_digital_level);
    SUBMENU_F(kp3s_tr(F("Motion/Vibration"), F("Mov./Vibracao"), F("Mov./Vibracion"), F("Mouv./Vibr."), F("Bew./Vibr.")), screen_kp3s_mpu_motion);
    SUBMENU_F(kp3s_tr(F("Startup Level"), F("Nivel Inicial"), F("Nivel Inicial"), F("Niv. Depart"), F("Startniveau")), screen_kp3s_startup_level);
    ACTION_ITEM_F(kp3s_tr(F("Calibrate Level Zero"), F("Calibrar Zero Nivel"), F("Calibrar Cero Nivel"), F("Calibrer Zero"), F("Niveau Null Kal.")), kp3s_open_mpu_zero_calibration);
    ACTION_ITEM_F(kp3s_tr(F("Clear Level Zero"), F("Limpar Zero Nivel"), F("Borrar Cero"), F("Effacer Zero"), F("Null Loeschen")), kp3s_run_mpu_clear_zero);
    SUBMENU_F(kp3s_tr(F("IMU Temp."), F("Temp. IMU"), F("Temp. IMU"), F("Temp. IMU"), F("IMU Temp.")), screen_kp3s_mpu_temperature);
    EDIT_ITEM_F(float31, kp3s_tr(F("Temp Offset"), F("Offset Temp."), F("Offset Temp."), F("Offset Temp."), F("Temp Offset")), &kp3s_mpu6050_temp_offset_c, -30.0f, 30.0f, kp3s_mpu6050_calibration_changed);
    END_MENU();
  }
#endif

static void screen_kp3s_about() {
  if (ui.use_click()) return ui.goto_previous_screen();
  if (!ui.should_draw()) return;
  MenuItem_static::draw(0, F("KINGROON KP3S"), SS_CENTER);
  MenuItem_static::draw(1, F("MARLIN V1"), SS_CENTER);
  MenuItem_static::draw(2, kp3s_tr(F("spidoug"), F("spidoug"), F("spidoug"), F("spidoug"), F("spidoug")), SS_CENTER | SS_INVERT);
  MenuItem_static::draw(3, F("Marlin 2.1.3"), SS_CENTER);
}

static void menu_kp3s_display_settings() {
  START_MENU();
  BACK_ITEM(MSG_BACK);
  #if ENABLED(KP3S_RUNTIME_DISPLAY)
    EDIT_ITEM_F(bool, kp3s_tr(F("Rotate 180"), F("Girar 180"), F("Girar 180"), F("Tourner 180"), F("Drehen 180")), &kp3s_display_flipped, kp3s_display_rotation_changed);
  #endif
  #if HAS_LCD_BRIGHTNESS
    EDIT_ITEM_FAST(uint8, MSG_BRIGHTNESS, &ui.brightness, LCD_BRIGHTNESS_MIN, LCD_BRIGHTNESS_MAX, ui.refresh_brightness, true);
  #endif
  #if HAS_LCD_CONTRAST && LCD_CONTRAST_MIN < LCD_CONTRAST_MAX
    EDIT_ITEM_FAST(uint8, MSG_CONTRAST, &ui.contrast, LCD_CONTRAST_MIN, LCD_CONTRAST_MAX, ui.refresh_contrast, true);
  #endif
  #if ENABLED(EDITABLE_DISPLAY_TIMEOUT)
    #if HAS_BACKLIGHT_TIMEOUT
      EDIT_ITEM(uint8, MSG_SCREEN_TIMEOUT, &ui.backlight_timeout_minutes, ui.backlight_timeout_min, ui.backlight_timeout_max, ui.refresh_backlight_timeout);
    #elif HAS_DISPLAY_SLEEP
      EDIT_ITEM(uint8, MSG_SCREEN_TIMEOUT, &ui.sleep_timeout_minutes, ui.sleep_timeout_min, ui.sleep_timeout_max, ui.refresh_screen_timeout);
    #endif
  #endif
  END_MENU();
}

#if ENABLED(BLTOUCH)
  static void menu_kp3s_probe_settings() {
    const bool busy = kp3s_runtime_machine_busy();
    START_MENU();
    BACK_ITEM(MSG_BACK);
    #if ENABLED(KP3S_RUNTIME_BLTOUCH)
      if (!busy)
        EDIT_ITEM_F(bool, kp3s_tr(F("BLTouch Probe"), F("Sonda BLTouch"), F("Sonda BLTouch"), F("Sonde BLTouch"), F("BLTouch Sonde")), &kp3s_bltouch_runtime_enabled, kp3s_runtime_bltouch_changed);
      else
        STATIC_ITEM_F(kp3s_bltouch_runtime_enabled
          ? kp3s_tr(F("BLTouch ON - LOCKED"), F("BLTouch ON - TRAV"), F("BLTouch ON - BLOQ"), F("BLTouch ON - VER"), F("BLTouch AN - SPER"))
          : kp3s_tr(F("BLTouch OFF - LOCK"), F("BLTouch OFF - TRAV"), F("BLTouch OFF - BLOQ"), F("BLTouch OFF - VER"), F("BLTouch AUS - SPER")), SS_CENTER);
      if (kp3s_bltouch_runtime_enabled && !busy) {
        SUBMENU(MSG_BLTOUCH, menu_bltouch);
        GCODES_ITEM_F(kp3s_tr(F("Auto Level"), F("Nivel Auto"), F("Nivel Auto"), F("Niv. Auto"), F("Auto-Niv.")), F("G29"));
      }
    #else
      if (!busy) SUBMENU(MSG_BLTOUCH, menu_bltouch);
    #endif
    END_MENU();
  }
#endif

static void menu_kp3s_sensor_settings() {
  START_MENU();
  BACK_ITEM(MSG_BACK);
  #if ENABLED(KP3S_MPU6050)
    SUBMENU_F(kp3s_tr(F("MPU6050 / IMU"), F("MPU6050 / IMU"), F("MPU6050 / IMU"), F("MPU6050 / IMU"), F("MPU6050 / IMU")), menu_kp3s_mpu6050_settings);
  #endif
  #if HAS_FILAMENT_SENSOR
    EDIT_ITEM_F(bool, kp3s_tr(F("Filam. Sensor"), F("Sensor Filam."), F("Sensor Filam."), F("Capt. Filam."), F("Filam.Sensor")), &runout.enabled, runout.reset);
  #endif
  END_MENU();
}

#if ENABLED(POWER_LOSS_RECOVERY)
  static void menu_kp3s_recovery_settings() {
    const bool busy = kp3s_runtime_machine_busy();
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (!busy) {
      EDIT_ITEM_F(bool, kp3s_tr(F("Recovery"), F("Recuperacao"), F("Recuperacion"), F("Reprise"), F("Wiederherst.")), &recovery.enabled, recovery.changed);
      #if HAS_PLR_BED_THRESHOLD
        EDIT_ITEM(int3, MSG_RESUME_BED_TEMP, &recovery.bed_temp_threshold, 0, BED_MAX_TARGET);
      #endif
    }
    else
      STATIC_ITEM_F(kp3s_tr(F("Recovery locked"), F("Recup. travada"), F("Recup. bloqueada"), F("Reprise verrou"), F("Wiederh. gesperrt")), SS_CENTER);
    END_MENU();
  }
#endif

#if ENABLED(EEPROM_SETTINGS)
  static void menu_kp3s_storage_settings() {
    const bool busy = kp3s_runtime_machine_busy();
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (!busy) {
      ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);
      ACTION_ITEM(MSG_LOAD_EEPROM, ui.load_settings);
      ACTION_ITEM(MSG_RESTORE_DEFAULTS, ui.reset_settings);
    }
    else
      STATIC_ITEM_F(kp3s_tr(F("Storage locked"), F("Memoria travada"), F("Memoria bloqueada"), F("Memoire verrou"), F("Speicher gesperrt")), SS_CENTER);
    END_MENU();
  }
#endif

static void menu_kp3s_motion_tuning() {
  START_MENU();
  BACK_ITEM(MSG_BACK);
  #if ENABLED(KP3S_MPU6050) && HAS_ZV_SHAPING
    SUBMENU_F(kp3s_tr(F("Resonance / Shaping"),F("Ressonancia / Shaping"),F("Resonancia / Shaping"),F("Resonance / Shaping"),F("Resonanz / Shaping")),menu_kp3s_resonance_tuning);
  #endif
  SUBMENU_F(kp3s_tr(F("Advanced Motion"),F("Movimento Avancado"),F("Movimiento Avanzado"),F("Mouvement Avance"),F("Bewegung Erweit.")),menu_advanced_settings);
  #if ENABLED(FWRETRACT)
    SUBMENU(MSG_RETRACT, menu_config_retract);
  #endif
  END_MENU();
}

static void menu_kp3s_v1_settings() {
  START_MENU();
  BACK_ITEM(MSG_CONFIGURATION);

  SUBMENU_F(kp3s_tr(F("Display"), F("Tela"), F("Pantalla"), F("Ecran"), F("Anzeige")), menu_kp3s_display_settings);
  SUBMENU_F(kp3s_tr(F("Motion / Tuning"), F("Movimento / Ajustes"), F("Movimiento / Ajustes"), F("Mouvement / Reglages"), F("Bewegung / Tuning")), menu_kp3s_motion_tuning);
  SUBMENU_F(kp3s_tr(F("Sensors / IMU"), F("Sensores / IMU"), F("Sensores / IMU"), F("Capteurs / IMU"), F("Sensoren / IMU")), menu_kp3s_sensor_settings);
  #if ENABLED(BLTOUCH)
    SUBMENU_F(kp3s_tr(F("BLTouch / Leveling"), F("BLTouch / Nivelamento"), F("BLTouch / Nivelacion"), F("BLTouch / Nivellement"), F("BLTouch / Nivellierung")), menu_kp3s_probe_settings);
  #endif

  #if ENABLED(POWER_LOSS_RECOVERY)
    SUBMENU_F(kp3s_tr(F("Recovery"), F("Recuperacao"), F("Recuperacion"), F("Reprise"), F("Wiederherst.")), menu_kp3s_recovery_settings);
  #endif

  #if ENABLED(EEPROM_SETTINGS)
    SUBMENU_F(kp3s_tr(F("Storage"), F("Memoria"), F("Memoria"), F("Memoire"), F("Speicher")), menu_kp3s_storage_settings);
  #endif

  SUBMENU_F(kp3s_tr(F("About"), F("Sobre"), F("Acerca"), F("A propos"), F("Info")), screen_kp3s_about);
  END_MENU();
}

void menu_configuration() {
''',
        "Create BLTouch runtime callback",
    )
    replace_once(
        menu_config,
        '''    #if ENABLED(BLTOUCH)
      SUBMENU(MSG_BLTOUCH, menu_bltouch);
    #endif
''',
        '''    #if ENABLED(BLTOUCH)
      // BLTouch controls are exposed explicitly under KP3S Setup > BLTouch / Leveling.
    #endif
''',
        "Group BLTouch controls under KP3S Setup",
    )

    replace_once(
        g29,
        '#include "../../../lcd/marlinui.h"\n',
        '#include "../../../lcd/marlinui.h"\n#if ENABLED(KP3S_RUNTIME_BLTOUCH)\n  #include "../../../feature/kp3s_bltouch_runtime.h"\n#endif\n',
        "Include runtime BLTouch state in G29",
    )
    replace_once(
        g29,
        'G29_TYPE GcodeSuite::G29() {\n\n  DEBUG_SECTION(log_G29, "G29", DEBUGGING(LEVELING));\n',
        '''G29_TYPE GcodeSuite::G29() {

  DEBUG_SECTION(log_G29, "G29", DEBUGGING(LEVELING));

  #if ENABLED(KP3S_RUNTIME_BLTOUCH)
    if (!kp3s_bltouch_runtime_enabled) {
      SERIAL_ERROR_MSG("BLTouch disabled in settings");
      G29_RETURN(false, false);
    }
  #endif
''',
        "Block G29 while BLTouch is disabled",
    )

    replace_once(
        probe_cpp,
        '#if ENABLED(BLTOUCH)\n  #include "../feature/bltouch.h"\n#endif\n',
        '#if ENABLED(BLTOUCH)\n  #include "../feature/bltouch.h"\n#endif\n#if ENABLED(KP3S_RUNTIME_BLTOUCH)\n  #include "../feature/kp3s_bltouch_runtime.h"\n#endif\n',
        "Include runtime BLTouch state in Probe",
    )
    replace_once(
        probe_cpp,
        'bool Probe::set_deployed(const bool deploy, const bool no_return/*=false*/) {\n',
        '''bool Probe::set_deployed(const bool deploy, const bool no_return/*=false*/) {
  #if ENABLED(KP3S_RUNTIME_BLTOUCH)
    if (deploy && !kp3s_bltouch_runtime_enabled) {
      SERIAL_ERROR_MSG("BLTouch disabled in settings");
      return true;
    }
  #endif
''',
        "Block probe deploy while BLTouch is disabled",
    )

    replace_once(
        g28,
        '#include "../../inc/MarlinConfig.h"\n',
        '#include "../../inc/MarlinConfig.h"\n#if ENABLED(KP3S_RUNTIME_BLTOUCH)\n  #include "../../feature/kp3s_bltouch_runtime.h"\n#endif\n',
        "Include runtime BLTouch state in G28",
    )
    replace_once(
        g28,
        '        TERN_(BLTOUCH, if (may_skate) bltouch.init());\n',
        '''        #if ENABLED(BLTOUCH)
          #if ENABLED(KP3S_RUNTIME_BLTOUCH)
            if (may_skate && kp3s_bltouch_runtime_enabled) bltouch.init();
          #else
            if (may_skate) bltouch.init();
          #endif
        #endif
''',
        "Do not initialize BLTouch from G28 while disabled",
    )

    replace_once(
        marlin_core,
        '''  #if ENABLED(BLTOUCH)
    SETUP_RUN(bltouch.init(/*set_voltage=*/true));
  #endif
''',
        '''  #if ENABLED(BLTOUCH)
    #if ENABLED(KP3S_RUNTIME_BLTOUCH)
      if (kp3s_bltouch_runtime_enabled) SETUP_RUN(bltouch.init(/*set_voltage=*/true));
    #else
      SETUP_RUN(bltouch.init(/*set_voltage=*/true));
    #endif
  #endif
''',
        "Do not initialize BLTouch at boot while disabled",
    )

    nokia_status.write_text(
        r'''#include "../../inc/MarlinConfigPre.h"

#if ENABLED(NOKIA5110_LCD)

#include "marlinui_DOGM.h"
#include "../marlinui.h"
#include "../lcdprint.h"
#include "../utf8.h"
#include "../../feature/kp3s_print_state.h"
#include "../../feature/kp3s_ui_text.h"
#include "../../libs/numtostr.h"
#include "../../module/temperature.h"
#if ENABLED(KP3S_MPU6050)
  #include "../../feature/kp3s_mpu6050.h"
  #include "../../module/motion.h"
  #include "../../module/planner.h"
  #include "../../module/stepper.h"
  #include "../../module/settings.h"
#endif
#if ENABLED(EEPROM_SETTINGS)
  #include "../../module/settings.h"
#endif
#include "../../module/motion.h"
#include "../../MarlinCore.h"
#if HAS_MEDIA
  #include "../../sd/cardreader.h"
#endif

static FSTR_P kp3s_idle_status_text() {
  return kp3s_tr(F("READY"), F("PRONTO"), F("LISTO"), F("PRET"), F("BEREIT"));
}

static FSTR_P kp3s_printing_text() {
  return kp3s_tr(F("PRINTING"), F("IMPRIMINDO"), F("IMPRIMIENDO"), F("IMPRESSION"), F("DRUCKT"));
}

static FSTR_P kp3s_paused_text() {
  return kp3s_tr(F("PAUSED"), F("PAUSADO"), F("PAUSA"), F("PAUSE"), F("PAUSE"));
}

static FSTR_P kp3s_hotend_prefix() {
  return kp3s_tr(F("H:"), F("B:"), F("B:"), F("B:"), F("D:"));
}

static FSTR_P kp3s_bed_prefix() {
  return kp3s_tr(F("B:"), F("M:"), F("C:"), F("P:"), F("B:"));
}

static FSTR_P kp3s_progress_prefix() {
  return kp3s_tr(F("P:"), F("P:"), F("P:"), F("P:"), F("F:"));
}

#if HAS_MEDIA
  // Independent UTF-8 marquee for the compact Nokia status row.
  static const char *kp3s_status_filename(const uint8_t max_chars) {
    const char * const name = card.longest_filename();
    static uint16_t last_hash = 0;
    static uint8_t scroll_pos = 0;
    static millis_t next_scroll = 0;

    uint16_t hash = 0x811C;
    for (const char *p = name; *p; ++p) hash = uint16_t((hash ^ uint8_t(*p)) * 257U);
    const uint8_t char_count = TERN(UTF_FILENAME_SUPPORT, utf8_strlen(name), strlen(name));

    if (hash != last_hash) {
      last_hash = hash;
      scroll_pos = 0;
      next_scroll = millis() + 900;
    }

    if (!max_chars || char_count <= max_chars) {
      scroll_pos = 0;
      return name;
    }

    const uint8_t max_offset = char_count - max_chars;
    if (scroll_pos > max_offset) scroll_pos = 0;

    const millis_t now = millis();
    if (ELAPSED(now, next_scroll)) {
      if (scroll_pos < max_offset) {
        ++scroll_pos;
        next_scroll = now + 260;
      }
      else {
        scroll_pos = 0;
        next_scroll = now + 900;
      }
      ui.refresh();
    }

    return name + TERN(UTF_FILENAME_SUPPORT, utf8_byte_pos_by_char_num(name, scroll_pos), scroll_pos);
  }
#endif

#if ENABLED(KP3S_MPU6050)
  static constexpr uint8_t KP3S_STATUS_LINE_CAP = 32;

  static bool kp3s_status_temperature_line(char * const out) {
    float temperature_c = 0;
    if (!kp3s_mpu6050_temperature_c(temperature_c)) return false;
    const int16_t tenths = int16_t(temperature_c * 10.0f + (temperature_c >= 0 ? 0.5f : -0.5f));
    const uint16_t mag = uint16_t(tenths < 0 ? -tenths : tenths);
    snprintf_P(out, KP3S_STATUS_LINE_CAP, PSTR("IMU:%c%u.%uC"), tenths < 0 ? '-' : '+', unsigned(mag / 10), unsigned(mag % 10));
    return true;
  }

  static bool kp3s_status_vibration_line(char * const out) {
    float rms=0, peak=0, instant=0;
    if (!kp3s_mpu6050_motion(rms,peak,instant)) return false;
    const uint16_t r=uint16_t(_MIN(9.99f,rms)*100.0f+0.5f), p=uint16_t(_MIN(9.99f,peak)*100.0f+0.5f);
    snprintf(out, KP3S_STATUS_LINE_CAP, "V:%u.%02u P:%u.%02u", unsigned(r/100), unsigned(r%100), unsigned(p/100), unsigned(p%100));
    return true;
  }

  static bool kp3s_status_startup_level_line(char * const out) {
    if (!kp3s_mpu6050_runtime_enabled) return false;
    float roll=0,pitch=0; bool level_ok=false;
    if (!kp3s_mpu6050_startup_level(roll,pitch,level_ok)) {
      if (!kp3s_mpu6050_detected()) {
        strcpy_P(out,FTOP(kp3s_tr(F("LEVEL: FIND MPU"),F("NIVEL: BUSCA MPU"),F("NIVEL: BUSCA MPU"),F("NIV: CHERCHE MPU"),F("NIV: MPU SUCHE"))));
        return true;
      }
      snprintf_P(out,KP3S_STATUS_LINE_CAP,FTOP(kp3s_tr(F("LEVEL:%u%%"),F("NIVEL:%u%%"),F("NIVEL:%u%%"),F("NIV:%u%%"),F("NIV:%u%%"))),unsigned(kp3s_mpu6050_startup_progress_pct()));
      return true;
    }
    if (!kp3s_mpu6050_startup_notice(roll,pitch,level_ok)) return false;
    if (level_ok) {
      strcpy_P(out,FTOP(kp3s_tr(F("LEVEL OK"),F("NIVEL OK"),F("NIVEL OK"),F("NIVEAU OK"),F("NIVEAU OK"))));
      return true;
    }
    const float angle=((millis()/1000UL)&1U)?pitch:roll;
    const char axis=((millis()/1000UL)&1U)?'Y':'X';
    const int16_t t=int16_t(angle*10.0f+(angle>=0?0.5f:-0.5f));
    const uint16_t m=uint16_t(t<0?-t:t);
    snprintf_P(out,KP3S_STATUS_LINE_CAP,PSTR("%c:%c%u.%u"),axis,t<0?'-':'+',unsigned(m/10),unsigned(m%10));
    return true;
  }
#endif

void MarlinUI::draw_status_screen() {
  // USE_SMALL_INFOFONT gives 6x9 glyphs. Five 9-pixel rows fit 84x48
  // without the overlap caused by the a taller status layout.
  set_font(FONT_STATUSMENU);

  const bool paused_now = printingIsPaused() || kp3s_serial_print_paused();
  const bool printing_now = !paused_now && (printingIsActive() || kp3s_serial_printing());

  lcd_moveto(0, 8);
  if (paused_now)
    lcd_put_u8str_max_P(FTOP(kp3s_paused_text()), LCD_PIXEL_WIDTH);
  else if (printing_now)
    lcd_put_u8str_max_P(FTOP(kp3s_printing_text()), LCD_PIXEL_WIDTH);
  else
    lcd_put_u8str_max_P(PSTR("KINGROON KP3S"), LCD_PIXEL_WIDTH);

  lcd_moveto(0, 17);
  lcd_put_u8str(kp3s_hotend_prefix());
  lcd_put_u8str(i16tostr3left(thermalManager.wholeDegHotend(0)));
  lcd_put_lchar('/');
  lcd_put_u8str(i16tostr3left(thermalManager.degTargetHotend(0)));

  lcd_moveto(0, 26);
  lcd_put_u8str(kp3s_bed_prefix());
  lcd_put_u8str(i16tostr3left(thermalManager.wholeDegBed()));
  lcd_put_lchar('/');
  lcd_put_u8str(i16tostr3left(thermalManager.degTargetBed()));

  lcd_moveto(0, 35);
  lcd_put_u8str(F("X:"));
  lcd_put_u8str(i16tostr3left(int16_t(current_position.x)));
  lcd_put_u8str(F(" Y:"));
  lcd_put_u8str(i16tostr3left(int16_t(current_position.y)));

  lcd_moveto(0, 44);
  #if HAS_MEDIA
    // Alternate file name and Z/progress every ~2 seconds during SD printing.
    if (card.isFileOpen() && ((millis() / 2000UL) & 1U)) {
      lcd_put_u8str_max(kp3s_status_filename(LCD_WIDTH), LCD_PIXEL_WIDTH);
      return;
    }
  #endif

  if (!printing_now && !paused_now) {
    #if ENABLED(KP3S_MPU6050)
      char level_line[KP3S_STATUS_LINE_CAP];
      if (kp3s_status_startup_level_line(level_line)) {
        lcd_put_u8str_max(level_line, LCD_PIXEL_WIDTH);
        return;
      }
      char temp_line[KP3S_STATUS_LINE_CAP];
      if (kp3s_status_temperature_line(temp_line)) {
        lcd_put_u8str_max(temp_line, LCD_PIXEL_WIDTH);
        return;
      }
    #endif
    lcd_put_u8str_max_P(FTOP(kp3s_idle_status_text()), LCD_PIXEL_WIDTH);
    return;
  }

  #if ENABLED(KP3S_MPU6050)
    if ((millis() / 1000UL) & 1U) {
      char vib_line[KP3S_STATUS_LINE_CAP];
      if (kp3s_status_vibration_line(vib_line)) { lcd_put_u8str_max(vib_line, LCD_PIXEL_WIDTH); return; }
    }
  #endif

  lcd_put_u8str(F("Z:"));
  lcd_put_u8str(i16tostr3left(int16_t(current_position.z)));
  #if HAS_PRINT_PROGRESS
    lcd_put_u8str(F(" "));
    lcd_put_u8str(kp3s_progress_prefix());
    lcd_put_u8str(ui8tostr3rj(get_progress_percent()));
    lcd_put_lchar('%');
  #endif
}

#endif
''',
        encoding="utf-8",
    )
    print("[OK] Create generic print-aware Nokia status screen with long-name marquee")

    (OUT / "KP3S_WIRING.txt").write_text(
        """KP3S V1 WIRING

NOKIA 5110
VCC   -> 3.3V / FFC1
GND   -> GND  / FFC2
DIN   -> PD14 / FFC3
CE/CS -> PD7  / FFC19
DC    -> PD11 / FFC20
CLK   -> PD5  / FFC21
RST   -> PC6  / FFC23
BL    -> PD13 / FFC24

SAMSUNG CONTROL BOARD - BN41-01840B / BN96-22413B
Connector: IR | GND | 3.3V | SCL | SDA | KEY1 | KEY2 | LED
3.3V -> FFC1
GND  -> FFC2
KEY1 -> PE10 / FFC10
KEY2 -> 1k series -> PE13 / FFC13; 100 nF from PE13 side to GND
IR   -> PE7  / FFC7
LED  -> PD10 / FFC18
SCL/SDA on the Samsung board -> NC

LOCAL NAVIGATION
Normal menu/list: UP/DOWN navigate, RIGHT selects, LEFT goes back.
Two-choice prompt: LEFT/RIGHT chooses the option, CENTER confirms.
Numeric/edit screen: LEFT/RIGHT changes the value, CENTER confirms.

OPTIONAL BLTOUCH
CTRL/SERVO -> PA8 / 3D Touch connector
PROBE      -> PC4 / Z-MAX (Z+) connector
+5V        -> 3D Touch 5V
GND        -> 3D Touch / Z-MAX GND
PA11 remains dedicated to the mechanical Z-min microswitch.
BLTouch starts disabled and can be enabled from KP3S Setup > BLTouch / Leveling.

FILAMENT RUNOUT
SIGNAL -> PA4 / Filament Detection 1
GND    -> sensor connector GND
Runout triggers M600 / Advanced Pause.

MPU6050 - SOFTWARE I2C
VCC -> FFC1 / 3.3V
GND -> FFC2 / GND
DEFAULT SDA -> FFC17 / PD9
DEFAULT SCL -> FFC16 / PD8
LCD: SDA/SCL Inv. exchanges these two roles at runtime and auto-saves the orientation
INT/XDA/XCL -> NC
AD0 -> module hardware strap; firmware scans the valid 7-bit I2C bus and identifies MPU6050 by WHO_AM_I
Runtime -> MPU menu includes continuously refreshed fused level, guided live zero calibration, visible startup inclination progress/result, toolhead vibration and calibrated IMU die temperature; disabled releases PD8/PD9

IMPORTANT
- Never apply 5V to the Samsung control board.
- PE15 / FFC15 is reserved only as the internal dummy BTN_ENC pin. Do not wire it.
- PA2 / PW_DET and PE6 / Filament Detection 2 remain available.
- Marlin JOYSTICK/POLL_JOG remain disabled; the Samsung JOG never moves axes directly.
""",
        encoding="utf-8",
    )



def verify_preprocessor_balance(path: Path):
    """Catch broken #if/#endif structure in generated C/C++ before PlatformIO."""
    stack = []
    for lineno, raw in enumerate(read(path).splitlines(), 1):
        line = raw.lstrip()
        if not line.startswith("#"):
            continue
        directive = line[1:].lstrip().split(None, 1)[0] if line[1:].lstrip() else ""
        if directive in ("if", "ifdef", "ifndef"):
            stack.append((directive, lineno, raw.strip()))
        elif directive == "endif":
            if not stack:
                raise RuntimeError(f"Preprocessor imbalance in {path.name}: extra #endif at line {lineno}")
            stack.pop()
    if stack:
        directive, lineno, text = stack[-1]
        raise RuntimeError(f"Preprocessor imbalance in {path.name}: unterminated #{directive} from line {lineno}: {text}")


def verify_project():
    banner("VALIDATING GENERATED PROJECT")
    files_and_markers = {
        OUT / "Marlin" / "Configuration.h": [
            "#define NOKIA5110_LCD",
            "#define USE_SMALL_INFOFONT",
            "#define KP3S_SMART_UI",
            "#define KP3S_UE5000",
            "#define KP3S_UE5000_LED_ACTIVE_LOW",
            "#define KP3S_UE5000_ROTATION 0",
            "#define KP3S_UE5000_SOFT_POWER",
            "#define KP3S_UE5000_POWER_HOLD_MS 5000UL",
            "#define KP3S_SERIAL_JOB_IDLE_TIMEOUT_MS 300000UL",
            "#define KP3S_MPU6050",
            "#define KP3S_RUNTIME_DISPLAY",
            "#define KP3S_RUNTIME_BLTOUCH",
            '#define STRING_CONFIG_H_AUTHOR "spidoug"',
            "#define EEPROM_SETTINGS",
            "#define EEPROM_AUTO_INIT",
            "#define PRINTCOUNTER",
            "#define BAUD_RATE_GCODE",
            "#define PID_EDIT_MENU",
            "#define PID_AUTOTUNE_MENU",
            "#define LCD_BED_TRAMMING",
            "#define FILAMENT_RUNOUT_SENSOR",
            "#define KP3S_MPU6050_SOFT_I2C_DELAY_US 8",
            "#define TONE_QUEUE_LENGTH 16",
            "NOKIA5110_BL_ACTIVE_LOW",
            "BOARD_MKS_ROBIN_NANO",
        ],
        OUT / "Marlin" / "Configuration_adv.h": [
            "//#define SHOW_BOOTSCREEN",
            "#define LCD_BACKLIGHT_TIMEOUT_MINS 2",
            "#define BINARY_FILE_TRANSFER",
            "#define AUTO_REPORT_TEMPERATURES",
            "#define AUTO_REPORT_POSITION",
            "#define AUTO_REPORT_SD_STATUS",
            "#define CAPABILITIES_REPORT",
            "#define EXTENDED_CAPABILITIES_REPORT",
            "#define LIN_ADVANCE",
            "#define ADVANCE_K 0.0",
            "#define INPUT_SHAPING_X",
            "#define INPUT_SHAPING_Y",
            "#define SHAPING_MENU",
            "#define FWRETRACT",
            "#define BABYSTEPPING",
            "#define BABYSTEP_ZPROBE_OFFSET",
            "#define PROBE_OFFSET_WIZARD",
            "#define POWER_LOSS_RECOVERY",
            "#define LONG_FILENAME_HOST_SUPPORT",
            "#define LONG_FILENAME_WRITE_SUPPORT",
            "#define SCROLL_LONG_FILENAMES",
            "#define STATUS_MESSAGE_SCROLLING",
            "#define CANCEL_OBJECTS",
            "#define EMERGENCY_PARSER",
            "#define ADVANCED_OK",
            "#define EDITABLE_DISPLAY_TIMEOUT",
        ],
        OUT / "Marlin" / "src" / "inc" / "Conditionals-2-LCD.h": [
            "#if ENABLED(NOKIA5110_LCD)",
            "#define LCD_PIXEL_WIDTH 84",
            "#define LCD_PIXEL_HEIGHT 48",
        ],
        OUT / "Marlin" / "src" / "inc" / "Conditionals-5-post.h": [
            "#define _LCD_CONTRAST_INIT 128",
        ],
        OUT / "Marlin" / "src" / "lcd" / "dogm" / "marlinui_DOGM.h": [
            "u8g_dev_pcd8544_84x48_sw_spi",
            "u8g_com_KP3S_PCD8544_sw_spi_fn",
            "#define U8G_CLASS U8GLIB",
        ],
        OUT / "Marlin" / "src" / "lcd" / "dogm" / "marlinui_DOGM.cpp": [
            "static uint8_t u8g_com_KP3S_PCD8544_sw_spi_fn",
            "WRITE(DOGLCD_SCK, LOW);",
            "DELAY_US(3);",
            "U8G_CLASS u8g(U8G_PARAM);",
            "u8g.undoRotation();",
            "u8g.setRot180();",
            "kp3s_display_apply_rotation();",
            "kp3s_label_pixel_limit",
            "kp3s_marquee_offset",
            "kp3s_marquee_advance",
        ],
        OUT / "Marlin" / "src" / "lcd" / "marlinui.cpp": [
            "KP3SUE5000Action ue_action",
            "kp3s_ue5000_poll(ms)",
            "kp3s_ue5000_led_task",
            "KP3SUE5000Action::PAUSE",
            "KP3SFeedback::NAV",
            "kp3s_printing_now = printingIsActive() || kp3s_serial_printing(ms)",
            "kp3s_paused_now = printingIsPaused() || kp3s_serial_print_paused()",
            "KP3S_BACKLIGHT_OFF_STATE",
            "KP3S_BACKLIGHT_ON_STATE",
            "kp3s_ue5000_init();",
            "KP3SUE5000PowerEvent::SLEPT",
            "KP3SUE5000PowerEvent::WOKE",
            "planner.has_blocks_queued()",
            "#include \"../feature/kp3s_ue5000_impl.h\"",
            "#include \"../feature/kp3s_mpu6050_impl.h\"",
            "kp3s_mpu6050_init();",
            "kp3s_mpu6050_task(ms);",
            '#include "../feature/kp3s_print_state_impl.h"',
        ],
        OUT / "Marlin" / "src" / "pins" / "stm32f1" / "pins_MKS_ROBIN_NANO_common.h": [
            "#define DOGLCD_SCK                        PD5",
            "#define BTN_ENC                           PE15",
            "#define KP3S_UE5000_KEY1_PIN              PE10",
            "#define KP3S_UE5000_KEY2_PIN              PE13",
            "#define KP3S_UE5000_IR_PIN                PE7",
            "#define KP3S_UE5000_LED_PIN               PD10",
            "#define KP3S_MPU6050_SDA_PIN              PD9",
            "#define KP3S_MPU6050_SCL_PIN              PD8",
            "#define Z_MIN_PROBE_PIN                   PC4",
            "#define LCD_BACKLIGHT_PIN                 PD13",
            "#define KP3S_BACKLIGHT_ON_STATE",
            "#define KP3S_BACKLIGHT_OFF_STATE",
            "#define KP3S_UE5000_LED_ON_STATE",
        ],
        OUT / "Marlin" / "src" / "MarlinCore.cpp": [
            "static void nokia5110_raw_selftest()",
            "nokia5110_raw_selftest();",
            "nokia5110_diag_beep",
            "KP3SFeedback::PRINT_START",
            "KP3SFeedback::DONE",
            "KP3SFeedback::ABORT",
            "KP3SFeedback::BOOT",
            "kp3s_ue5000_is_awake()",
            "queue.has_commands_queued()",
            "kp3s_ue5000_wake()",
            '#include "feature/kp3s_bltouch_runtime.h"',
            "if (kp3s_bltouch_runtime_enabled) SETUP_RUN(bltouch.init(/*set_voltage=*/true));",
        ],
        OUT / "Marlin" / "src" / "lcd" / "dogm" / "status_screen_NOKIA5110.cpp": [
            '#include "../../inc/MarlinConfigPre.h"',
            "void MarlinUI::draw_status_screen()",
            "KINGROON KP3S",
            "kp3s_status_filename(LCD_WIDTH",
            "utf8_byte_pos_by_char_num",
            "next_scroll = now + 260",
            "kp3s_printing_text",
            "IMPRIMINDO",
            "kp3s_serial_printing",
            "kp3s_mpu6050_startup_progress_pct",
            'F("NIVEL:%u%%")',
            "ui.refresh();",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_ue5000.h": [
            "enum class KP3SUE5000Action",
            "kp3s_ue5000_poll",
            "kp3s_ue5000_power_task",
            "kp3s_ue5000_is_awake",
            "enum class KP3SUE5000PowerEvent",
            "const bool allow_standby",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_ue5000_impl.h": [
            "#include \"../HAL/shared/Delay.h\"",
            "DELAY_US(500);",
            "0xE0E006F9UL",
            "0xE0E016E9UL",
            "attachInterrupt",
            "kp3s_ue5000_key2_isr",
            "KP3S_UE5000_POWER_HOLD_MS",
            "ue_power_ignore_key1_until_release",
            "ue_key1_click_ready",
            "return KP3SUE5000Action::ENTER;",
            "discrete release event, not an RC level",
            "held_ms >= 2500 ? 45",
            "stable == KP3SUE5000Action::LEFT",
            "stable == KP3SUE5000Action::RIGHT",
            "KP3S_UE5000_RC_TIMEOUT_US",
            "KP3S_UE5000_RC_CAL_SAMPLES",
            "ue_rc_baseline_us",
            "ue_neutral_cutoff_us",
            "ue_rc_armed",
            "return KP3SUE5000Action::LEFT;",
            "return KP3SUE5000Action::RIGHT;",
            "return KP3SUE5000Action::UP;",
            "return KP3SUE5000Action::DOWN;",
            "need_release",
            "KP3S_UE5000_KEY1_PIN",
            "KP3S_UE5000_KEY2_PIN",
            "KP3S_UE5000_LED_PIN",
            "100 nF",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050.h": [
            "struct KP3SMPU6050Sample",
            "kp3s_mpu6050_init",
            "kp3s_mpu6050_runtime_enabled",
            "kp3s_mpu6050_set_enabled",
            "KP3SMPU6050BusStatus",
            "kp3s_mpu6050_test_bus",
            "kp3s_mpu6050_detect_now",
            "kp3s_mpu6050_level",
            "kp3s_mpu6050_level_raw",
            "kp3s_mpu6050_startup_progress_pct",
            "kp3s_mpu6050_temperature_c",
            "kp3s_mpu6050_motion",
            "kp3s_mpu6050_resonance_capture_start",
            "kp3s_mpu6050_resonance_capture_analyze",
            "kp3s_mpu6050_resonance_samples",
            "kp3s_mpu6050_resonance_capturing",
            "kp3s_mpu6050_startup_level",
            "kp3s_mpu6050_set_level_zero",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050_impl.h": [
            "SET_INPUT_PULLUP",
            "kp3s_i2c_bus_recover",
            "KP3S_I2C_SCAN_FIRST = 0x08",
            "KP3S_I2C_SCAN_LAST = 0x77",
            "kp3s_mpu_scan_bus()",
            "kp3s_mpu_configure_and_verify()",
            "kp3s_mpu_last_who_valid",
            "kp3s_mpu_read_sample_now",
            "kp3s_mpu_write_reg(0x6B, 0x80)",
            "kp3s_mpu_delay_ms(100)",
            "kp3s_i2c_delay()",
            "#define KP3S_MPU6050_SOFT_I2C_DELAY_US 8",
            "kp3s_mpu_read_regs(0x3B",
            "kp3s_i2c_release_bus",
            "if (!kp3s_mpu6050_runtime_enabled) return",
            "kp3s_i2c_probe_ack",
            "SDA_STUCK_LOW",
            "SCL_STUCK_LOW",
            "void kp3s_mpu6050_resonance_capture_start()",
            "bool kp3s_mpu6050_resonance_capture_analyze(float &frequency_hz, uint8_t &confidence_pct)",
            "static float kp3s_res_goertzel_power",
            "kp3s_mpu_write_reg(0x1A, 0x02)",
            "kp3s_mpu_write_reg(0x1A, 0x03)",
            "if (addr != 0x68 && addr != 0x69) return false;",
            "raw_amag > 0.05f && raw_amag < 3.70f",
            "const float alpha = tau_s / (tau_s + dt);",
            "kp3s_mpu_gyro_bias_valid",
            "KP3S_MPU_TEMP_BASELINE_SAMPLES = 20",
            "kp3s_mpu_boot_last_good_ms + 250UL",
            "Bartlett window reduces leakage",
            "atan2f",
            "sqrtf",
            "KP3S_MPU_BOOT_SAMPLES_REQUIRED = 40",
            "startup_sample_ok",
            "startup_hard_motion",
            "kp3s_mpu_boot_notice_until = now + 60000UL",
            "float(kp3s_mpu_data.temperature) / 340.0f + 36.53f",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_bltouch_runtime.h": [
            "extern bool kp3s_bltouch_runtime_enabled",
            "inline void kp3s_bltouch_runtime_apply",
            "if (kp3s_bltouch_runtime_enabled)",
            "bltouch.init(/*set_voltage=*/true);",
            "set_bed_leveling_enabled(false);",
            "if (stow_when_disabling) bltouch._stow();",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_ui_context.h": [
            "kp3s_ui_selection_mode",
            "kp3s_ui_edit_mode",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_ui_text.h": [
            "static inline FSTR_P kp3s_tr",
            "case 1: return pt",
            "case 2: return es",
            "case 3: return fr",
            "case 4: return de",
        ],
        OUT / "Marlin" / "src" / "lcd" / "menu" / "menu.cpp": [
            "kp3s_ui_selection_mode = true",
            "kp3s_ui_edit_mode = true",
        ],
        OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_configuration.cpp": [
            "kp3s_runtime_bltouch_changed",
            "kp3s_display_rotation_changed",
            "kp3s_mpu6050_changed",
            "kp3s_mpu6050_wiring_changed",
            "menu_kp3s_mpu6050_settings",
            "kp3s_run_mpu_bus_test",
            "kp3s_run_mpu_detect_test",
            "screen_kp3s_digital_level",
            "screen_kp3s_mpu_zero_calibration",
            "kp3s_open_mpu_zero_calibration",
            'F("Calibrar Zero Nivel")',
            "menu_kp3s_v1_settings",
            "menu_kp3s_display_settings",
            "menu_kp3s_motion_tuning",
            "menu_kp3s_resonance_tuning",
            "kp3s_run_resonance_axis",
            "stepper.set_shaping_frequency(axis, kp3s_res_frequency_hz)",
            'gcode.process_subcommands_now(F("G28"))',
            "axis_should_home(X_AXIS) || axis_should_home(Y_AXIS) || axis_should_home(Z_AXIS)",
            "do_blocking_move_to_z(10.0f, 5.0f)",
            "line_to_current_position(120.0f)",
            "kp3s_mpu6050_task(millis())",
            "thermalManager.task()",
            "hal.watchdog_refresh()",
            "capture_deadline = millis() + 1400UL",
            "settings.save() ? KP3SResonanceUIState::APPLIED",
            "menu_kp3s_sensor_settings",
            "menu_kp3s_storage_settings",
            "screen_kp3s_about",
            "spidoug",
            'SUBMENU_F(kp3s_tr(F("Display"), F("Tela")',
            'EDIT_ITEM_F(bool, kp3s_tr(F("Rotate 180"), F("Girar 180")',
            'EDIT_ITEM_F(bool, kp3s_tr(F("Enabled"), F("Ativado")',
            'EDIT_ITEM_F(bool, kp3s_tr(F("SDA/SCL Inv."), F("Inv. SDA/SCL")',
            'SUBMENU_F(kp3s_tr(F("Motion / Tuning"), F("Movimento / Ajustes")',
            'SUBMENU_F(kp3s_tr(F("Sensors / IMU"), F("Sensores / IMU")',
            'SUBMENU_F(kp3s_tr(F("BLTouch / Leveling"), F("BLTouch / Nivelamento")',
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_display_runtime.h": [
            "extern bool kp3s_display_flipped",
            "kp3s_display_apply_rotation",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_print_state.h": [
            "kp3s_print_state_note_serial",
            "kp3s_serial_printing",
            "kp3s_serial_print_paused",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_print_state_impl.h": [
            "has_extrusion && has_machine_axis",
            "kp3s_serial_job_active",
            "kp3s_serial_job_last_activity",
            "kp3s_normalize_serial_line",
            "KP3S_SERIAL_JOB_IDLE_TIMEOUT_MS",
        ],
        OUT / "Marlin" / "src" / "gcode" / "queue.cpp": [
            "kp3s_print_state_note_serial(command, millis())",
        ],
        OUT / "Marlin" / "src" / "gcode" / "eeprom" / "M500-M504.cpp": [
            "kp3s_eeprom_mutation_busy",
            "M500 blocked while printer is active",
            "M501 blocked while printer is active",
            "M502 blocked while printer is active",
        ],
        OUT / "Marlin" / "src" / "module" / "settings.cpp": [
            '#define EEPROM_VERSION "V10"',
            "bool kp3s_display_flipped;",
            "bool kp3s_bltouch_enabled;",
            "bool kp3s_mpu6050_enabled;",
            "bool kp3s_mpu6050_swap_lines;",
            "EEPROM_WRITE(kp3s_display_flipped)",
            "EEPROM_WRITE(kp3s_bltouch_runtime_enabled)",
            "EEPROM_WRITE(kp3s_mpu6050_runtime_enabled)",
            "EEPROM_WRITE(kp3s_mpu6050_swap_lines)",
            "EEPROM_WRITE(kp3s_mpu6050_temp_offset_c)",
            "EEPROM_WRITE(kp3s_mpu6050_level_zero_roll_deg)",
            "EEPROM_WRITE(kp3s_mpu6050_level_zero_pitch_deg)",
            "EEPROM_WRITE(kp3s_mpu6050_level_zero_valid)",
            "stored_display_flipped",
            "stored_mpu6050_enabled",
            "stored_mpu6050_swap_lines",
        ],
        OUT / "Marlin" / "src" / "gcode" / "bedlevel" / "abl" / "G29.cpp": [
            "BLTouch disabled in settings",
        ],
        OUT / "Marlin" / "src" / "module" / "probe.cpp": [
            "deploy && !kp3s_bltouch_runtime_enabled",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_feedback.h": [
            "enum class KP3SFeedback",
            "KP3SFeedback::PRINT_START",
            "KP3SFeedback::DONE",
        ],
        OUT / "Marlin" / "src" / "gcode" / "sd" / "M24_M25.cpp": [
            "KP3SFeedback::PAUSE",
        ],
        OUT / "Marlin" / "src" / "gcode" / "sd" / "M28_M29.cpp": [
            "BINARY_FILE_TRANSFER",
            "Switching to Binary Protocol",
        ],
        OUT / "Marlin" / "src" / "feature" / "binary_stream.h": [
            "SDFileTransferProtocol",
            "FileTransfer::WRITE",
            "FileTransfer::CLOSE",
            "header_token = 0xB5AD",
        ],
        OUT / "ini" / "stm32f1.ini": [
            "[env:mks_robin_nano_v1v2]",
            "board_build.encrypt_mks     = Robin_nano35.bin",
        ],
    }

    for path, markers in files_and_markers.items():
        if not path.exists():
            raise RuntimeError(f"Required file missing: {path}")
        text = read(path)
        for marker in markers:
            if marker not in text:
                raise RuntimeError(f"Validation failed in {path.name}: missing {marker!r}")

    cfg_text = read(OUT / "Marlin" / "Configuration.h")
    if not re.search(r"^[ \t]*#define[ \t]+SDSUPPORT\b", cfg_text, flags=re.M):
        raise RuntimeError("SDSUPPORT is required for V1 serial spooling and local printing.")
    for language_marker in (
        "#define LCD_LANGUAGE en",
        "#define LCD_LANGUAGE_2 pt_br",
        "#define LCD_LANGUAGE_3 es",
        "#define LCD_LANGUAGE_4 fr",
        "#define LCD_LANGUAGE_5 de",
    ):
        if language_marker not in cfg_text:
            raise RuntimeError(f"Missing language configuration: {language_marker}")
    adv_language_text = read(OUT / "Marlin" / "Configuration_adv.h")
    if "#define LCD_LANGUAGE_AUTO_SAVE" not in adv_language_text:
        raise RuntimeError("LCD language selection must be persisted in EEPROM.")

    for active_define in ("MKS_ROBIN_TFT24", "TFT_COLOR_UI", "TOUCH_SCREEN"):
        if re.search(rf"^[ \t]*#define[ \t]+{active_define}\b", cfg_text, flags=re.M):
            raise RuntimeError(f"{active_define} remained enabled unexpectedly.")

    c2_text = read(OUT / "Marlin" / "src" / "inc" / "Conditionals-2-LCD.h")
    nokia_block = c2_text.split("#if ENABLED(NOKIA5110_LCD)", 1)[1].split("#elif ANY(MKS_MINI_12864, ENDER2_STOCKDISPLAY)", 1)[0]
    if re.search(r"^[ \t]*#define[ \t]+FORCE_SOFT_SPI\b", nokia_block, flags=re.M) \
       or re.search(r"^[ \t]*#define[ \t]+LCD_SPI_SPEED\b", nokia_block, flags=re.M):
        raise RuntimeError("V1 must not enable FORCE_SOFT_SPI/LCD_SPI_SPEED in the Nokia block.")

    ue_impl_text = read(OUT / "Marlin" / "src" / "feature" / "kp3s_ue5000_impl.h")
    expected_jog_map = [
        "if (rc_us < KP3S_UE5000_RC_DOWN_MAX_US)     return KP3SUE5000Action::DOWN;",
        "if (rc_us < KP3S_UE5000_RC_UP_MAX_US)       return KP3SUE5000Action::UP;",
        "if (rc_us < KP3S_UE5000_RC_RIGHT_MAX_US)    return KP3SUE5000Action::RIGHT;",
        "if (rc_us < KP3S_UE5000_RC_LEFT_MAX_US)     return KP3SUE5000Action::LEFT;",
    ]
    for line in expected_jog_map:
        if line not in ue_impl_text:
            raise RuntimeError(f"Incorrect V1 JOG mapping: missing {line}")
    cfg_jog = read(OUT / "Marlin" / "Configuration.h")
    for limit in (
        "#define KP3S_UE5000_RC_DOWN_MAX_US      60",
        "#define KP3S_UE5000_RC_UP_MAX_US       220",
        "#define KP3S_UE5000_RC_RIGHT_MAX_US    900",
        "#define KP3S_UE5000_RC_LEFT_MAX_US    5200",
    ):
        if limit not in cfg_jog:
            raise RuntimeError(f"Incorrect V1 JOG RC window: missing {limit}")
    if "KP3S_UE5000_MIRROR_LR" in cfg_jog or "KP3S_UE5000_MIRROR_LR" in ue_impl_text:
        raise RuntimeError("V1 must not apply left/right mirroring to the control pad.")

    pins_text = read(OUT / "Marlin" / "src" / "pins" / "stm32f1" / "pins_MKS_ROBIN_NANO_common.h")
    if "KP3S_MPU6050_SDA_PIN              PD9" not in pins_text or "KP3S_MPU6050_SCL_PIN              PD8" not in pins_text:
        raise RuntimeError("MPU6050 must use SDA=FFC17/PD9 and SCL=FFC16/PD8.")
    if "#define BTN_ENC                           PE15" not in pins_text:
        raise RuntimeError("V1 dummy BTN_ENC must use PE15 / FFC15.")
    if "#define Z_MIN_PROBE_PIN                   PC4" not in pins_text:
        raise RuntimeError("Optional BLTouch V1 must use PC4 as the probe input.")
    mpu_impl_text = read(OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050_impl.h")
    if "WRITE(KP3S_MPU6050_SDA_PIN, HIGH)" in mpu_impl_text or "WRITE(KP3S_MPU6050_SCL_PIN, HIGH)" in mpu_impl_text:
        raise RuntimeError("Software I2C must remain open-drain.")

    cfg_text = read(OUT / "Marlin" / "Configuration.h")
    for required in ("#define BLTOUCH", "#define KP3S_RUNTIME_BLTOUCH", "#define AUTO_BED_LEVELING_BILINEAR", "#define FILAMENT_RUNOUT_SENSOR"):
        if required not in cfg_text:
            raise RuntimeError(f"V1 is incomplete: missing {required}")
    if re.search(r"^[ \t]*#define[ \t]+USE_PROBE_FOR_Z_HOMING\b", cfg_text, flags=re.M):
        raise RuntimeError("Z homing must remain on the PA11 microswitch.")
    if re.search(r"^[ \t]*#define[ \t]+Z_MIN_PROBE_USES_Z_MIN_ENDSTOP_PIN\b", cfg_text, flags=re.M):
        raise RuntimeError("BLTouch must not share PA11 with the Z microswitch.")
    if re.search(r"^[ \t]*#define[ \t]+Z_SAFE_HOMING\b", cfg_text, flags=re.M):
        raise RuntimeError("Z_SAFE_HOMING must remain disabled in this architecture.")

    adv_text = read(OUT / "Marlin" / "Configuration_adv.h")
    if not re.search(r"^[ \t]*#define[ \t]+ADVANCED_PAUSE_FEATURE\b", adv_text, flags=re.M):
        raise RuntimeError("ADVANCED_PAUSE_FEATURE is required for M600 filament runout handling.")
    for runtime_feature in (
        "LIN_ADVANCE", "INPUT_SHAPING_X", "INPUT_SHAPING_Y", "SHAPING_MENU",
        "FWRETRACT", "BABYSTEPPING", "BABYSTEP_ZPROBE_OFFSET", "PROBE_OFFSET_WIZARD",
        "POWER_LOSS_RECOVERY", "LONG_FILENAME_HOST_SUPPORT", "LONG_FILENAME_WRITE_SUPPORT",
        "SCROLL_LONG_FILENAMES", "STATUS_MESSAGE_SCROLLING", "CANCEL_OBJECTS", "EMERGENCY_PARSER",
        "ADVANCED_OK", "EDITABLE_DISPLAY_TIMEOUT",
    ):
        if not re.search(rf"^[ \t]*#define[ \t]+{runtime_feature}\b", adv_text, flags=re.M):
            raise RuntimeError(f"V1 runtime feature is missing: {runtime_feature}")

    # Explicit V1 safety contract. Validate the effective KP3S architecture, not
    # configuration-specific USE_*_PLUG macros that are not present in the Marlin 2.1.3-b3
    # Kingroon/KP3S configuration. Future baseline changes must fail here only
    # when they actually remove a protection or change a required endstop path.
    for safety_define in (
        "THERMAL_PROTECTION_HOTENDS", "THERMAL_PROTECTION_BED",
        "PREVENT_COLD_EXTRUSION", "PREVENT_LENGTHY_EXTRUDE",
        "ENDSTOPPULLUPS",
    ):
        if not re.search(rf"^[ \t]*#define[ \t]+{safety_define}\b", cfg_text, flags=re.M):
            raise RuntimeError(f"V1 safety invariant is missing: {safety_define}")

    for axis in ("X", "Y", "Z"):
        if not re.search(rf"^[ \t]*#define[ \t]+{axis}_HOME_DIR[ \t]+-1\b", cfg_text, flags=re.M):
            raise RuntimeError(f"V1 {axis} homing must remain on the MIN endstop.")
        if not re.search(rf"^[ \t]*#define[ \t]+{axis}_MIN_ENDSTOP_HIT_STATE[ \t]+(?:LOW|HIGH)\b", cfg_text, flags=re.M):
            raise RuntimeError(f"V1 {axis}-MIN endstop hit-state definition is missing.")

    for numeric_safety in ("HEATER_0_MINTEMP", "HEATER_0_MAXTEMP", "BED_MINTEMP", "BED_MAXTEMP", "EXTRUDE_MINTEMP", "EXTRUDE_MAXLENGTH"):
        if not re.search(rf"^[ \t]*#define[ \t]+{numeric_safety}[ \t]+[-+0-9]", cfg_text, flags=re.M):
            raise RuntimeError(f"V1 thermal/extrusion safety limit is missing: {numeric_safety}")

    board_pins = pins_text
    required_pin_routes = (
        (r"^[ \t]*#define[ \t]+X_STOP_PIN[ \t]+PA15\b", "X-MIN endstop must remain on PA15."),
        (r"^[ \t]*#define[ \t]+Y_STOP_PIN[ \t]+PA12\b", "Y-MIN endstop must remain on PA12."),
        (r"^[ \t]*#define[ \t]+Z_MIN_PIN[ \t]+PA11\b", "Z-MIN microswitch must remain on PA11."),
        (r"^[ \t]*#define[ \t]+SERVO0_PIN[ \t]+PA8\b", "SERVO0 / BLTouch control must remain on PA8."),
        (r"^[ \t]*#define[ \t]+FIL_RUNOUT_PIN[ \t]+PA4\b", "The filament runout sensor must use PA4."),
    )
    for pattern, message in required_pin_routes:
        if not re.search(pattern, board_pins, flags=re.M):
            raise RuntimeError(message)

    menu_cpp_text = read(OUT / "Marlin" / "src" / "lcd" / "menu" / "menu.cpp")
    ui_cpp_text = read(OUT / "Marlin" / "src" / "lcd" / "marlinui.cpp")
    for nav_marker in ("kp3s_ui_selection_mode = true", "kp3s_ui_edit_mode = true"):
        if nav_marker not in menu_cpp_text:
            raise RuntimeError(f"Context-aware navigation is incomplete: {nav_marker}")
    if "kp3s_ui_selection_mode || kp3s_ui_edit_mode" not in ui_cpp_text:
        raise RuntimeError("LEFT/RIGHT context-aware navigation is missing from MarlinUI.")
    for click_marker in (
        "if (ui.use_click()) ui.goto_previous_screen();",
        "got_click = ui.use_click();",
    ):
        if click_marker not in menu_cpp_text:
            raise RuntimeError(f"Marlin confirmation/exit hook is missing: {click_marker}")
    if "return KP3SUE5000Action::ENTER;" not in ue_impl_text:
        raise RuntimeError("CENTER must produce an atomic ENTER event on short-release.")
    atomic_enter = ue_impl_text.find("return KP3SUE5000Action::ENTER;")
    jog_debounce = ue_impl_text.find("if (candidate == last_candidate)")
    if atomic_enter < 0 or jog_debounce < 0 or atomic_enter > jog_debounce:
        raise RuntimeError("CENTER ENTER must bypass the directional JOG debounce.")

    menu_text = read(OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_configuration.cpp")
    if '#include "../../feature/kp3s_ui_text.h"' not in menu_text:
        raise RuntimeError("KP3S custom LCD text must use the runtime localization helper.")
    if ('SDA' + '17') in menu_text or ('SCL' + '16') in menu_text:
        raise RuntimeError("Physical connector pin numbers must not be shown on the firmware LCD.")
    # Enforce full-bus discovery instead of fixed-address probing.
    for suffix in ("6" + "8", "6" + "9"):
        fixed_probe = "kp3s_mpu_probe_address(0x" + suffix + ")"
        if fixed_probe in mpu_impl_text:
            raise RuntimeError("MPU detection must scan the I2C bus instead of probing fixed addresses.")
    if 'EDIT_ITEM_F(bool, kp3s_tr(F("BLTouch Probe"), F("Sonda BLTouch")' not in menu_text:
        raise RuntimeError("BLTouch / Leveling menu must expose an explicitly named BLTouch probe toggle.")
    if 'EDIT_ITEM_F(bool, kp3s_tr(F("Rotate 180"), F("Girar 180")' not in menu_text:
        raise RuntimeError("Display menu must expose localized persistent 180-degree rotation.")
    if 'SUBMENU_F(kp3s_tr(F("MPU6050 / IMU"), F("MPU6050 / IMU")' not in menu_text:
        raise RuntimeError("Sensors / IMU menu must expose the explicitly named MPU6050 / IMU submenu.")
    for marker in ('kp3s_tr(F("Enabled"), F("Ativado")', 'kp3s_tr(F("SDA/SCL Inv."), F("Inv. SDA/SCL")', 'kp3s_tr(F("Test I2C Bus"), F("Testar I2C")', 'kp3s_tr(F("Detect MPU"), F("Detectar MPU")', 'kp3s_tr(F("IMU Temp."), F("Temp. IMU")', 'kp3s_tr(F("Live Level"), F("Nivel ao Vivo")', 'kp3s_tr(F("Motion/Vibration"), F("Mov./Vibracao")', 'kp3s_tr(F("Startup Level"), F("Nivel Inicial")', 'F("Calibrar Zero Nivel")', 'screen_kp3s_mpu_zero_calibration', 'kp3s_tr(F("Auto Tune X"),F("Autoajuste X")', 'kp3s_tr(F("Motion / Tuning"), F("Movimento / Ajustes")'):
        if marker not in menu_text:
            raise RuntimeError(f"MPU6050 localized diagnostics menu is incomplete: {marker}")
    mpu_line_cap = menu_text.find("static constexpr uint8_t KP3S_MPU_UI_LINE_CAP = 24;")
    first_mpu_line_use = menu_text.find("char xline[KP3S_MPU_UI_LINE_CAP]")
    if mpu_line_cap < 0 or first_mpu_line_use < 0 or mpu_line_cap > first_mpu_line_use:
        raise RuntimeError("MPU UI line capacity must be declared before the first menu buffer that uses it.")
    if "MarlinSettings::save();" not in menu_text:
        raise RuntimeError("SDA/SCL orientation must auto-save to EEPROM when changed from the LCD.")
    for marker in ("kp3s_mpu_configure_and_verify", "kp3s_mpu_read_sample_now", "kp3s_mpu_last_who_valid", "kp3s_mpu_write_reg(0x6B, 0x80)", "kp3s_mpu_delay_ms(100)", "static bool kp3s_i2c_read_byte(uint8_t &v", "kp3s_mpu_read_regs_mode", "stop_before_read", "if (!kp3s_i2c_read_byte(dst[i]", "kp3s_mpu_update_derived", "const float alpha = tau_s / (tau_s + dt);", "kp3s_mpu_gyro_bias_valid", "kp3s_mpu_stable_since + 500UL", "KP3S_MPU_TEMP_BASELINE_SAMPLES = 20", "kp3s_mpu_boot_last_good_ms + 250UL", "KP3S_MPU6050_POLL_PRINT_MS 10UL", "kp3s_mpu6050_set_level_zero", "kp3s_mpu6050_level_raw", "kp3s_mpu6050_startup_progress_pct", "KP3S_MPU_BOOT_SAMPLES_REQUIRED = 40", "startup_sample_ok", "kp3s_mpu6050_temp_offset_c"):
        if marker not in mpu_impl_text:
            raise RuntimeError(f"MPU detection must prove live sensor data, missing: {marker}")
    bltouch_runtime_text = read(OUT / "Marlin" / "src" / "feature" / "kp3s_bltouch_runtime.h")
    if "kp3s_bltouch_runtime_apply(/*stow_when_disabling=*/true);" not in menu_text:
        raise RuntimeError("The BLTouch display callback must apply the runtime probe state.")
    if "if (kp3s_bltouch_runtime_enabled)" not in bltouch_runtime_text \
       or "bltouch.init(/*set_voltage=*/true);" not in bltouch_runtime_text:
        raise RuntimeError("Enabling BLTouch from the display must initialize the probe through the runtime driver.")
    if "set_bed_leveling_enabled(false);" not in bltouch_runtime_text \
       or "if (stow_when_disabling) bltouch._stow();" not in bltouch_runtime_text:
        raise RuntimeError("Disabling BLTouch must disable leveling and safely stow the probe.")
    if 'kp3s_tr(F("Filam. Sensor"), F("Sensor Filam.")' not in menu_text:
        raise RuntimeError("Explicitly named filament sensor toggle is missing from the Sensors menu.")
    g28_text = read(OUT / "Marlin" / "src" / "gcode" / "calibrate" / "G28.cpp")
    if "may_skate && kp3s_bltouch_runtime_enabled" not in g28_text:
        raise RuntimeError("G28 must ignore BLTouch while it is disabled.")
    core_text = read(OUT / "Marlin" / "src" / "MarlinCore.cpp")
    if "if (kp3s_bltouch_runtime_enabled) SETUP_RUN(bltouch.init(/*set_voltage=*/true));" not in core_text:
        raise RuntimeError("Boot must not initialize BLTouch while it is disabled.")

    status_text = read(OUT / "Marlin" / "src" / "lcd" / "dogm" / "status_screen_NOKIA5110.cpp")
    if '"KINGROON KP3S"' not in status_text:
        raise RuntimeError("Status screen must identify the printer.")
    if "static const char *kp3s_status_filename" not in status_text or "lcd_put_u8str_max(kp3s_status_filename(" not in status_text:
        raise RuntimeError("Status screen must safely scroll the current SD filename when available.")
    if "kp3s_printing_text" not in status_text or "kp3s_serial_printing" not in status_text:
        raise RuntimeError("Status screen must report generic print activity from SD or serial G-code.")
    if "kp3s_status_temperature_line" not in status_text or "kp3s_mpu6050_temperature_c" not in status_text:
        raise RuntimeError("Status screen must expose the MPU6050 calibrated MPU die-temperature while idle.")
    if "kp3s_status_vibration_line" not in status_text or "kp3s_mpu6050_motion" not in status_text:
        raise RuntimeError("Status screen must expose live toolhead vibration during printing.")
    if "kp3s_status_startup_level_line" not in status_text or "kp3s_mpu6050_startup_notice" not in status_text:
        raise RuntimeError("Status screen must expose the automatic startup level assessment.")
    retired_bottom_row = "lcd_moveto(0, " + "47);"
    if retired_bottom_row in status_text or "lcd_moveto(0, 44);" not in status_text:
        raise RuntimeError("Nokia status must use the compact five-row 6x9 layout.")
    if "kp3s_tr(" not in status_text:
        raise RuntimeError("Nokia custom status text must follow the selected language.")
    # F()/FSTR_P strings live in Flash and must use the _P overload. The
    # two-argument lcd_put_u8str_max function only accepts SRAM const char*.
    for flash_call in (
        "lcd_put_u8str_max_P(FTOP(kp3s_paused_text()), LCD_PIXEL_WIDTH);",
        "lcd_put_u8str_max_P(FTOP(kp3s_printing_text()), LCD_PIXEL_WIDTH);",
        'lcd_put_u8str_max_P(PSTR("KINGROON KP3S"), LCD_PIXEL_WIDTH);',
        "lcd_put_u8str_max_P(FTOP(kp3s_idle_status_text()), LCD_PIXEL_WIDTH);",
    ):
        if flash_call not in status_text:
            raise RuntimeError(f"Nokia status uses an invalid Flash-string draw API: missing {flash_call}")
    for bad_flash_call in (
        "lcd_put_u8str_max(kp3s_paused_text(),",
        "lcd_put_u8str_max(kp3s_printing_text(),",
        "lcd_put_u8str_max(kp3s_idle_status_text(),",
        'lcd_put_u8str_max(F("KINGROON KP3S"),',
    ):
        if bad_flash_call in status_text:
            raise RuntimeError(f"Nokia status reintroduced the invalid FSTR_P overload: {bad_flash_call}")
    if 'lcd_put_u8str("UE5000")' in status_text:
        raise RuntimeError("Status screen must not display UE5000.")
    if 'lcd_put_u8str("KP3S 5110")' in status_text or 'lcd_put_u8str("UE5K V1.' in status_text:
        raise RuntimeError("Status screen still contains a display model or firmware version string.")

    dogm_cpp_path = OUT / "Marlin" / "src" / "lcd" / "dogm" / "marlinui_DOGM.cpp"
    nokia_status_path = OUT / "Marlin" / "src" / "lcd" / "dogm" / "status_screen_NOKIA5110.cpp"
    verify_preprocessor_balance(dogm_cpp_path)
    verify_preprocessor_balance(nokia_status_path)
    dogm_cpp_text = read(dogm_cpp_path)
    if ";#endif" in dogm_cpp_text or ";#if" in dogm_cpp_text:
        raise RuntimeError("DOGM patch joined a preprocessor directive to a C++ statement.")
    # Arduino STM32 defines PGM_P as `const char *`; adding an outer const
    # produces `const const char *` and is rejected by GCC 9.2.1.
    if "const PGM_P" in dogm_cpp_text:
        raise RuntimeError("DOGM marquee uses invalid `const PGM_P`; use PGM_P directly.")
    if "!itemStringC && !itemStringF && itemIndex == 0" in dogm_cpp_text:
        raise RuntimeError("DOGM marquee still depends on stale MenuItemBase substitution state.")
    for marker in (
        "kp3s_marquee_advance", "kp3s_marquee_offset",
        "expand_u8str(kp3s_label", "MAX_MESSAGE_SIZE * LANG_CHARSIZE + 2",
        "START_PAUSE_MS = 900UL", "STEP_MS = 420UL",
        "const millis_t cycle_ms", "% cycle_ms",
        "lcd_put_u8str_max(kp3s_marquee_advance", "kp3s_edit_label", "kp3s_visible_chars"
    ):
        if marker not in dogm_cpp_text:
            raise RuntimeError(f"Nokia selected-label marquee is incomplete: {marker}")
    if "u8g_com_HAL_STM32F1_sw_spi_fn" in dogm_cpp_text or "u8g_com_HAL_STM32_sw_spi_fn" in dogm_cpp_text:
        raise RuntimeError("A generic HAL display driver is still referenced unexpectedly.")

    core_text = read(OUT / "Marlin" / "src" / "MarlinCore.cpp")
    if "queue.clear();  // discard commands received while the interface is in logical standby" in core_text:
        raise RuntimeError("Standby must never silently discard acknowledged G-code.")
    for marker in ("queue.has_commands_queued()", "kp3s_ue5000_wake()"):
        if marker not in core_text:
            raise RuntimeError(f"Standby auto-wake is incomplete: {marker}")

    settings_text = read(OUT / "Marlin" / "src" / "module" / "settings.cpp")
    for marker in ("kp3s_bltouch_enabled", "EEPROM_WRITE(kp3s_bltouch_runtime_enabled)", "if (IsRunning()) kp3s_bltouch_runtime_apply"):
        if marker not in settings_text:
            raise RuntimeError(f"Persistent BLTouch state is incomplete: {marker}")

    eeprom_gcode_text = read(OUT / "Marlin" / "src" / "gcode" / "eeprom" / "M500-M504.cpp")
    for marker in ("kp3s_eeprom_mutation_busy", "M500 blocked while printer is active", "M501 blocked while printer is active", "M502 blocked while printer is active"):
        if marker not in eeprom_gcode_text:
            raise RuntimeError(f"EEPROM mutation guard is incomplete: {marker}")

    print_state_text = read(OUT / "Marlin" / "src" / "feature" / "kp3s_print_state_impl.h")
    for marker in ("kp3s_normalize_serial_line", "KP3S_SERIAL_JOB_IDLE_TIMEOUT_MS", "case 25:", "case 24:"):
        if marker not in print_state_text:
            raise RuntimeError(f"Serial print-state robustness is incomplete: {marker}")
    if "+ 15000UL" in print_state_text or "kp3s_serial_job_last_motion" in print_state_text:
        raise RuntimeError("Serial print idle timeout must remain at the V1 value.")

    status_text = read(nokia_status_path)
    if "KP3S_STATUS_LINE_CAP = 32" not in status_text:
        raise RuntimeError("Nokia dynamic status lines must use the safe translated-line buffer.")

    for custom_path in (
        OUT / "Marlin" / "src" / "feature" / "kp3s_ue5000.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_ue5000_impl.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_feedback.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_print_state.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_print_state_impl.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_bltouch_runtime.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_ui_context.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_ui_text.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_display_runtime.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050.h",
        OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050_impl.h",
    ):
        verify_preprocessor_balance(custom_path)

    print("[OK] V1 validated: safety contract + lossless standby + persistent hardware state + robust serial/UI + IMU tuning")


def pio_candidates():
    candidates = []
    local_env = BASE / ".build_env"
    if os.name == "nt":
        candidates += [local_env / "Scripts" / "platformio.exe", local_env / "Scripts" / "pio.exe"]
    else:
        candidates += [local_env / "bin" / "platformio", local_env / "bin" / "pio"]
    for name in ("platformio", "pio", "platformio.exe", "pio.exe"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))

    if os.name == "nt":
        candidates += [
            Path.home() / ".platformio" / "penv" / "Scripts" / "platformio.exe",
            Path.home() / ".platformio" / "penv" / "Scripts" / "pio.exe",
        ]
    else:
        candidates += [
            Path.home() / ".platformio" / "penv" / "bin" / "platformio",
            Path.home() / ".platformio" / "penv" / "bin" / "pio",
        ]
    return candidates


def find_platformio(override: str | None = None):
    candidates = []
    if override:
        direct = Path(override).expanduser()
        if direct.exists():
            candidates.append(direct)
        else:
            found = shutil.which(override)
            if found:
                candidates.append(Path(found))
    candidates.extend(pio_candidates())

    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        key = str(resolved).lower() if os.name == "nt" else str(resolved)
        if key in seen or not resolved.exists():
            continue
        seen.add(key)
        if run([resolved, "--version"], check=False) == 0:
            return resolved
    return None


def prepare_build_toolchain():
    """Create a project-local build environment when no working toolchain is available."""
    existing = find_platformio()
    if existing:
        return existing

    banner("PREPARING BUILD TOOLCHAIN")
    env_dir = BASE / ".build_env"
    py = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        if env_dir.exists():
            shutil.rmtree(env_dir)
        print("[...] Creating isolated build environment")
        run([sys.executable, "-m", "venv", env_dir])

    print("[...] Installing / updating firmware build dependencies")
    run([py, "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"])
    run([py, "-m", "pip", "install", "--disable-pip-version-check", "platformio>=6.1,<7"])

    pio = find_platformio()
    if not pio:
        raise RuntimeError("The build toolchain was installed but could not be validated.")
    print("[OK] Build toolchain ready:", pio)
    return pio


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_flash_output(source_binary: Path):
    if FW_OUT.exists():
        shutil.rmtree(FW_OUT)
    FLASH_DIR.mkdir(parents=True)
    ORIGINAL_DIR.mkdir(parents=True)

    original = ORIGINAL_DIR / BUILD_BINARY
    flash = FLASH_DIR / FLASH_BINARY
    shutil.copy2(source_binary, original)
    shutil.copy2(source_binary, flash)

    digest = sha256_file(flash)
    (FW_OUT / "SHA256.txt").write_text(
        f"{digest}  FLASH_KP3S/{FLASH_BINARY}\n",
        encoding="ascii",
    )
    (FW_OUT / "FLASH_README.txt").write_text(
        """KP3S - FLASH-READY FILE

Use only this file on the SD card:
  FLASH_KP3S\\Robin_nano.bin

The build_original\\Robin_nano35.bin file is the binary name produced by the
Marlin environment. For the KP3S it is copied / renamed automatically to
Robin_nano.bin, which is the filename expected by the printer bootloader.

Use the normal KP3S microSD bootloader procedure: power the printer off, insert
a FAT32 microSD containing Robin_nano.bin in the card root, then power the printer
on again. Direct debug-interface upload is not required for the normal update.
""",
        encoding="utf-8",
    )

    print("[OK] Original build binary:", original)
    print("[OK] FLASH READY:", flash)
    print("[OK] SHA-256:", digest)
    return flash


def build(pio_override: str | None = None, auto_toolchain: bool = False):
    banner("BUILDING FIRMWARE")
    pio = find_platformio(pio_override)
    if not pio and auto_toolchain:
        pio = prepare_build_toolchain()
    if not pio:
        raise RuntimeError(
            "The firmware build toolchain was not found or failed validation.\n"
            "Run BUILD_FIRMWARE.bat or use --auto-toolchain."
        )

    print("[OK] Build tool:", pio)

    banner("INSTALLING BUILD DEPENDENCIES")
    # Resolve the platform, compiler framework, and environment libraries.
    run([pio, "pkg", "install", "-d", OUT, "-e", ENV], cwd=OUT)

    banner("BUILDING FIRMWARE")
    run([pio, "run", "-e", ENV], cwd=OUT)

    build_dir = OUT / ".pio" / "build" / ENV
    source = build_dir / BUILD_BINARY
    if not source.exists() or source.stat().st_size < 16 * 1024:
        found = sorted(p.name for p in build_dir.glob("*.bin")) if build_dir.exists() else []
        raise RuntimeError(
            f"Build finished, but {BUILD_BINARY} was not found in {build_dir}.\n"
            f"Binary files found: {found}"
        )

    flash = prepare_flash_output(source)
    print()
    print("[SUCCESS] Firmware ready to copy to microSD:")
    print("          ", flash)


def clean():
    banner("CLEANING")
    if OUT.exists():
        shutil.rmtree(OUT)
        print("[OK] Generated project removed")
    if FW_OUT.exists():
        shutil.rmtree(FW_OUT)
        print("[OK] firmware_output removed")
    for extra in (CACHE, BASE / ".build_env"):
        if extra.exists():
            shutil.rmtree(extra)
            print("[OK] removed", extra.name)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build", action="store_true", help="Build after generating the project")
    parser.add_argument("--generate-only", action="store_true", help="Generate and validate without compiling")
    parser.add_argument("--auto-toolchain", action="store_true", help="Prepare an isolated build toolchain when needed")
    parser.add_argument("--clean", action="store_true", help="Remove generated files and exit")
    parser.add_argument("--build-tool", dest="pio", help="Explicit path to the firmware build executable")
    args = parser.parse_args()

    if args.clean:
        clean()
        return

    # Remove any existing firmware artifact before creating the V1 build.
    if args.build and FW_OUT.exists():
        shutil.rmtree(FW_OUT)
        print("[OK] Existing firmware output removed before this build")

    banner("KINGROON KP3S MARLIN FIRMWARE V1 - CLEAN BUILD")

    ensure_download(MARLIN_URL, MARLIN_ZIP, 1_000_000, f"Marlin {TAG}", validate_marlin_zip)
    ensure_download(CONFIG_H_URL, CONFIG_H, 10_000, "KP3S Configuration.h", validate_config_h)
    ensure_download(
        CONFIG_ADV_H_URL,
        CONFIG_ADV_H,
        10_000,
        "KP3S Configuration_adv.h",
        validate_config_adv,
    )

    extract_marlin()
    patch_configuration()
    verify_project()

    print()
    print("[OK] Project ready:")
    print("    ", OUT)

    if args.build:
        build(args.pio, args.auto_toolchain)
    else:
        print()
        print("To build:")
        print("  BUILD_FIRMWARE.bat")


if __name__ == "__main__":
    BASE.mkdir(parents=True, exist_ok=True)

    # --clean must leave the repository clean. Handle it before creating
    # BUILD.log or cache/, then let clean() remove any old build artifacts.
    if "--clean" in sys.argv[1:]:
        clean()
        if LOG.exists():
            LOG.unlink()
        sys.exit(0)

    # Help is read-only too; don't create build artifacts just to show usage.
    if any(arg in ("-h", "--help") for arg in sys.argv[1:]):
        main()
        sys.exit(0)

    CACHE.mkdir(exist_ok=True)

    with open(LOG, "w", encoding="utf-8", buffering=1) as log:
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout = Tee(original_out, log)
        sys.stderr = Tee(original_err, log)
        try:
            main()
        except KeyboardInterrupt:
            print("\nCancelled by user.")
            sys.exit(130)
        except Exception:
            banner("ERROR")
            traceback.print_exc()
            print()
            print("Full log:")
            print(" ", LOG)
            sys.exit(1)
        finally:
            sys.stdout = original_out
            sys.stderr = original_err
