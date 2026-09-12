#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KINGROON KP3S MARLIN FIRMWARE

Build system for the V1 firmware based on Marlin 2.1.3-b3.

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
import ast
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

BUILD_SYSTEM_NAME = "KINGROON KP3S MARLIN FIRMWARE"

TAG = "2.1.3-b3"
# Immutable upstream refs verified from the official Marlin repositories.
MARLIN_COMMIT = "58a4358809c315ec55c827687cb52edf0cd92fa5"
CONFIG_COMMIT = "3f66c8829abf9bb298b4d86a80ed9bf57237619c"
PLATFORMIO_CORE_VERSION = "6.1.19"
ENV = "mks_robin_nano_v1v2"
BUILD_BINARY = "Robin_nano35.bin"
FLASH_BINARY = "Robin_nano.bin"

# V1 UI languages. English is the primary/default language.
V1_LCD_LANGUAGES = ("en", "pt_br", "es", "fr", "de")
V1_DEFAULT_LCD_LANGUAGE = "en"

# V1 high-temperature hotend profile. A 340C selectable target requires a
# temperature sensor that is valid above 340C. Marlin thermistor table 61 is
# the 100k B3950 Formbot/Vivedino 350C sensor on the normal 4.7k pull-up.
# Hardware must be all-metal and the heater cartridge, thermistor, wiring and
# connector must all be rated for this temperature.
V1_HOTEND_SENSOR = 61
V1_HOTEND_TARGET_MAX_C = 340
V1_HOTEND_MAXTEMP_C = 350
V1_HOTEND_OVERSHOOT_C = V1_HOTEND_MAXTEMP_C - V1_HOTEND_TARGET_MAX_C
V1_HOTEND_IDLE_TIMEOUT_SEC = 10 * 60
V1_LCD_LANGUAGE_DEFINES = "\n".join(
    f"#define LCD_LANGUAGE{'_' + str(index) if index > 1 else ''} {code}"
    for index, code in enumerate(V1_LCD_LANGUAGES, start=1)
)


# V1 supplements the upstream Marlin translations only for UI entries that are
# visible in this firmware and are missing, partially translated, or left in
# English in the pinned 2.1.3-b3 language files. This prevents Marlin's normal
# Language_en fallback from leaking English into another selected language.
# Keep the strings concise for the Nokia 84x48 display; native menu marquee is
# still available when a translated label is wider than one row.
V1_NATIVE_LANGUAGE_SUPPLEMENTS = {
    "pt_br": {
        "LANGUAGE": "Português (BR)",
        "MSG_BRIGHTNESS": "Brilho LCD",
        "MSG_BRIGHTNESS_OFF": "Desligar LCD",
        "MSG_SCREEN_TIMEOUT": "Espera LCD (m)",
        "MSG_INPUT_SHAPING": "Filtro vibração",
        "MSG_SHAPING_ENABLE_N": "Ativ. filtro @",
        "MSG_SHAPING_DISABLE_N": "Desat. filtro @",
        "MSG_SHAPING_FREQ_N": "Freq. @",
        "MSG_SHAPING_ZETA_N": "Amortec. @",
        "MSG_HOTEND_IDLE_TIMEOUT": "Espera hotend",
        "MSG_HOTEND_IDLE_DISABLE": "Desat. espera",
        "MSG_HOTEND_IDLE_NOZZLE_TARGET": "Temp. bico esp.",
        "MSG_HOTEND_IDLE_BED_TARGET": "Temp. mesa esp.",
        "MSG_PROBE_WIZARD": "Assist. Sonda Z",
        "MSG_PROBE_WIZARD_PROBING": "Medindo ref.",
        "MSG_PROBE_WIZARD_MOVING": "Movendo p/ pos.",
        "MSG_INFO_BUILD": "Data compil.",
        "MSG_BED_TRAMMING_MANUAL": "Nivel. manual",
        "MSG_BED_TRAMMING_RAISE": "Subir até sonda",
        "MSG_BED_TRAMMING_IN_RANGE": "Cantos OK",
        "MSG_BED_TRAMMING_GOOD_POINTS": "Pontos bons: ",
        "MSG_BED_TRAMMING_LAST_Z": "Último Z: ",
        "MSG_BUTTON_DONE": "Concluído",
        "MSG_BUTTON_SKIP": "Pular",
        "MSG_TIMEOUT": "Tempo limite",
        "MSG_TEMPERATURE": "Temperatura",
        "MSG_LCD_ON": "Ligado",
        "MSG_LCD_OFF": "Desligado",
        "MSG_PID_AUTOTUNE": "Autoajuste PID",
        "MSG_PID_AUTOTUNE_E": "Autoajuste PID *",
        "MSG_PID_CYCLE": "Ciclos PID",
        "MSG_PID_AUTOTUNE_DONE": "Autoajuste PID OK",
        "MSG_PID_AUTOTUNE_FAILED": "Falha autoajuste!",
        "MSG_BAD_HEATER_ID": "Aquecedor inválido",
        "MSG_TEMP_TOO_HIGH": "Temp. muito alta",
        "MSG_TEMP_TOO_LOW": "Temp. muito baixa",
        "MSG_PID_BAD_HEATER_ID": "Autoajuste: aquec. inválido",
        "MSG_PID_TEMP_TOO_HIGH": "Autoajuste: temp. alta",
        "MSG_PID_TIMEOUT": "Autoajuste: tempo esgotado",
        "MSG_INFO_MENU": "Sobre",
        "MSG_INFO_PRINTER_MENU": "Impressora",
        "MSG_INFO_BOARD_MENU": "Placa",
        "MSG_INFO_THERMISTOR_MENU": "Termistores",
        "MSG_INFO_STATS_MENU": "Estatísticas",
        "MSG_INFO_PRINT_COUNT": "Total impressões",
        "MSG_INFO_COMPLETED_PRINTS": "Concluídas",
        "MSG_INFO_PRINT_TIME": "Tempo impressão",
        "MSG_INFO_PRINT_LONGEST": "Maior impressão",
        "MSG_INFO_PRINT_FILAMENT": "Filamento total",
        "MSG_INFO_MIN_TEMP": "Temp. mínima",
        "MSG_INFO_MAX_TEMP": "Temp. máxima",
        "MSG_INFO_RUNAWAY_ON": "Proteção ativa",
        "MSG_INFO_RUNAWAY_OFF": "Proteção inativa",
        "MSG_INFO_BAUDRATE": "Baud",
        "MSG_INFO_PROTOCOL": "Protocolo",
        "MSG_INFO_PSU": "Fonte",
        "MSG_INFO_EXTRUDERS": "Extrusores",
        "MSG_MEDIA_SORT": "Ordenar SD",
        "MSG_MEDIA_INSERTED_SD": "SD inserido",
        "MSG_MEDIA_INSERTED_USB": "USB inserido",
        "MSG_MEDIA_REMOVED_SD": "SD removido",
        "MSG_MEDIA_REMOVED_USB": "USB removido",
        "MSG_MEDIA_INIT_FAIL": "Falha ao iniciar",
        "MSG_MEDIA_INIT_FAIL_SD": "Falha ao iniciar SD",
        "MSG_MEDIA_INIT_FAIL_USB": "Falha ao iniciar USB",
        "MSG_MEDIA_READ_ERROR": "Erro de leitura",
        "MSG_MEDIA_UPDATE": "Atualizar mídia",
        "MSG_USB_FD_WAITING_FOR_MEDIA": "Aguardando USB",
        "MSG_USB_FD_MEDIA_REMOVED": "USB removido",
        "MSG_ATTACH_MEDIA": "Montar mídia",
        "MSG_ATTACH_SD": "Montar SD",
        "MSG_ATTACH_USB": "Montar USB",
        "MSG_RELEASE_MEDIA": "Ejetar mídia",
        "MSG_RELEASE_SD": "Ejetar SD",
        "MSG_RELEASE_USB": "Ejetar USB",
        "MSG_CHANGE_MEDIA": "Atualizar mídia",
        "MSG_CHANGE_SD": "Selecionar SD",
        "MSG_CHANGE_USB": "Selecionar USB",
        "MSG_RUN_AUTOFILES": "Autoarquivos",
        "MSG_RUN_AUTOFILES_SD": "Autoarquivos SD",
        "MSG_RUN_AUTOFILES_USB": "Autoarq. USB",
        "MSG_MEDIA_MENU": "Escolher mídia",
        "MSG_MEDIA_MENU_SD": "Escolher do SD",
        "MSG_MEDIA_MENU_USB": "Arquivos USB",
        "MSG_NO_MEDIA": "Sem mídia",
        "MSG_TRAMMING_WIZARD": "Assist. cantos",
        "MSG_SELECT_ORIGIN": "Escolher canto",
        "MSG_LAST_VALUE_SP": "Último valor ",
        "MSG_HOMING": "Referenciando",
        "MSG_HOME_ALL": "Origem XYZ",
        "MSG_HOME_FIRST": "Origem %s antes",
        "MSG_RUNOUT_SENSOR": "Sensor filamento",
        "MSG_OUTAGE_RECOVERY": "Recuperar impressão",
        "MSG_ADVANCE_K": "Avanço K",
        "MSG_AUTORETRACT": "Retração automática",
        "MSG_FILAMENT_LOAD": "Carregar mm",
        "MSG_FILAMENT_UNLOAD": "Descarregar mm",
    },
    "es": {
        "LANGUAGE": "Español",
        "MSG_BRIGHTNESS": "Brillo LCD",
        "MSG_BRIGHTNESS_OFF": "Apagar LCD",
        "MSG_SCREEN_TIMEOUT": "Espera LCD (m)",
        "MSG_INPUT_SHAPING": "Filtro vibrac.",
        "MSG_SHAPING_ENABLE_N": "Act. filtro @",
        "MSG_SHAPING_DISABLE_N": "Desact. fil. @",
        "MSG_SHAPING_FREQ_N": "Frec. @",
        "MSG_SHAPING_ZETA_N": "Amortig. @",
        "MSG_HOTEND_IDLE_TIMEOUT": "Espera hotend",
        "MSG_HOTEND_IDLE_DISABLE": "Desact. espera",
        "MSG_HOTEND_IDLE_NOZZLE_TARGET": "Temp. boq. esp.",
        "MSG_HOTEND_IDLE_BED_TARGET": "Temp. cama esp.",
        "MSG_PROBE_WIZARD": "Asist. Sonda Z",
        "MSG_PROBE_WIZARD_PROBING": "Midiendo ref.",
        "MSG_PROBE_WIZARD_MOVING": "Mover a pos.",
        "MSG_INFO_BUILD": "Fecha compil.",
        "MSG_BED_TRAMMING_MANUAL": "Nivel. manual",
        "MSG_BED_TRAMMING_RAISE": "Subir a sonda",
        "MSG_BED_TRAMMING_IN_RANGE": "Esquinas OK",
        "MSG_BED_TRAMMING_GOOD_POINTS": "Puntos buenos:",
        "MSG_BED_TRAMMING_LAST_Z": "Último Z: ",
        "MSG_BUTTON_DONE": "Hecho",
        "MSG_BUTTON_SKIP": "Omitir",
        "MSG_TIMEOUT": "Tiempo límite",
        "MSG_TEMPERATURE": "Temperatura",
        "MSG_LCD_ON": "Encendido",
        "MSG_LCD_OFF": "Apagado",
        "MSG_PID_AUTOTUNE": "Autoajuste PID",
        "MSG_PID_AUTOTUNE_E": "Autoajuste PID *",
        "MSG_PID_CYCLE": "Ciclos PID",
        "MSG_PID_AUTOTUNE_DONE": "Autoajuste PID OK",
        "MSG_PID_AUTOTUNE_FAILED": "¡Fallo autoajuste!",
        "MSG_BAD_HEATER_ID": "Calentador inválido",
        "MSG_TEMP_TOO_HIGH": "Temp. muy alta",
        "MSG_TEMP_TOO_LOW": "Temp. muy baja",
        "MSG_PID_BAD_HEATER_ID": "Autoajuste: calent. inválido",
        "MSG_PID_TEMP_TOO_HIGH": "Autoajuste: temp. alta",
        "MSG_PID_TIMEOUT": "Autoajuste: tiempo agotado",
        "MSG_INFO_MENU": "Acerca de",
        "MSG_INFO_PRINTER_MENU": "Impresora",
        "MSG_INFO_BOARD_MENU": "Placa",
        "MSG_INFO_THERMISTOR_MENU": "Termistores",
        "MSG_INFO_STATS_MENU": "Estadísticas",
        "MSG_INFO_PRINT_COUNT": "Total impresiones",
        "MSG_INFO_COMPLETED_PRINTS": "Completadas",
        "MSG_INFO_PRINT_TIME": "Tiempo impresión",
        "MSG_INFO_PRINT_LONGEST": "Impresión más larga",
        "MSG_INFO_PRINT_FILAMENT": "Filamento total",
        "MSG_INFO_MIN_TEMP": "Temp. mínima",
        "MSG_INFO_MAX_TEMP": "Temp. máxima",
        "MSG_INFO_RUNAWAY_ON": "Protección activa",
        "MSG_INFO_RUNAWAY_OFF": "Protección inactiva",
        "MSG_INFO_BAUDRATE": "Baudios",
        "MSG_INFO_PROTOCOL": "Protocolo",
        "MSG_INFO_PSU": "Fuente",
        "MSG_INFO_EXTRUDERS": "Extrusores",
        "MSG_MEDIA_SORT": "Ordenar SD",
        "MSG_MEDIA_INSERTED_SD": "SD insertada",
        "MSG_MEDIA_INSERTED_USB": "USB insertado",
        "MSG_MEDIA_REMOVED_SD": "SD retirada",
        "MSG_MEDIA_REMOVED_USB": "USB retirado",
        "MSG_MEDIA_INIT_FAIL": "Fallo al iniciar",
        "MSG_MEDIA_INIT_FAIL_SD": "Fallo inicio SD",
        "MSG_MEDIA_INIT_FAIL_USB": "Fallo inicio USB",
        "MSG_MEDIA_READ_ERROR": "Error de lectura",
        "MSG_MEDIA_UPDATE": "Actualizar medio",
        "MSG_USB_FD_WAITING_FOR_MEDIA": "Esperando USB",
        "MSG_USB_FD_MEDIA_REMOVED": "USB retirado",
        "MSG_ATTACH_MEDIA": "Montar medio",
        "MSG_ATTACH_SD": "Montar SD",
        "MSG_ATTACH_USB": "Montar USB",
        "MSG_RELEASE_MEDIA": "Expulsar medio",
        "MSG_RELEASE_SD": "Expulsar SD",
        "MSG_RELEASE_USB": "Expulsar USB",
        "MSG_CHANGE_MEDIA": "Actualizar medio",
        "MSG_CHANGE_SD": "Elegir SD",
        "MSG_CHANGE_USB": "Elegir USB",
        "MSG_RUN_AUTOFILES": "Autoarchivos",
        "MSG_RUN_AUTOFILES_SD": "Autoarchivos SD",
        "MSG_RUN_AUTOFILES_USB": "Autoarch. USB",
        "MSG_MEDIA_MENU": "Elegir medio",
        "MSG_MEDIA_MENU_SD": "Elegir desde SD",
        "MSG_MEDIA_MENU_USB": "Archivos USB",
        "MSG_NO_MEDIA": "Sin medio",
        "MSG_TRAMMING_WIZARD": "Asist. esquinas",
        "MSG_SELECT_ORIGIN": "Elegir esquina",
        "MSG_LAST_VALUE_SP": "Último valor ",
        "MSG_HOMING": "Referenciando",
        "MSG_HOME_ALL": "Origen XYZ",
        "MSG_HOME_FIRST": "Origen %s antes",
        "MSG_RUNOUT_SENSOR": "Sensor filamento",
        "MSG_OUTAGE_RECOVERY": "Recuperar impresión",
        "MSG_ADVANCE_K": "Avance K",
        "MSG_AUTORETRACT": "Retracción automática",
        "MSG_FILAMENT_LOAD": "Cargar mm",
        "MSG_FILAMENT_UNLOAD": "Descargar mm",
    },
    "fr": {
        "LANGUAGE": "Français",
        "MSG_BRIGHTNESS": "Luminosité LCD",
        "MSG_BRIGHTNESS_OFF": "Éteindre LCD",
        "MSG_SCREEN_TIMEOUT": "Veille LCD (m)",
        "MSG_INPUT_SHAPING": "Filtre vibrat.",
        "MSG_SHAPING_ENABLE_N": "Activer filt. @",
        "MSG_SHAPING_DISABLE_N": "Désact. filt. @",
        "MSG_SHAPING_FREQ_N": "Fréq. @",
        "MSG_SHAPING_ZETA_N": "Amorti. @",
        "MSG_HOTEND_IDLE_TIMEOUT": "Veille hotend",
        "MSG_HOTEND_IDLE_DISABLE": "Désact. veille",
        "MSG_HOTEND_IDLE_NOZZLE_TARGET": "Buse en veille",
        "MSG_HOTEND_IDLE_BED_TARGET": "Lit en veille",
        "MSG_PROBE_WIZARD": "Assist. Sonde Z",
        "MSG_PROBE_WIZARD_PROBING": "Mesure réf.",
        "MSG_PROBE_WIZARD_MOVING": "Vers position",
        "MSG_INFO_BUILD": "Date compil.",
        "MSG_BUTTON_DONE": "Terminé",
        "MSG_BUTTON_SKIP": "Passer",
        "MSG_TIMEOUT": "Délai",
        "MSG_TEMPERATURE": "Température",
        "MSG_LCD_ON": "Activé",
        "MSG_LCD_OFF": "Désactivé",
        "MSG_PID_AUTOTUNE": "Auto-réglage PID",
        "MSG_PID_AUTOTUNE_E": "Auto-régl. PID *",
        "MSG_PID_CYCLE": "Cycles PID",
        "MSG_PID_AUTOTUNE_DONE": "Réglage PID OK",
        "MSG_PID_AUTOTUNE_FAILED": "Échec réglage PID",
        "MSG_BAD_HEATER_ID": "Chauffage invalide",
        "MSG_TEMP_TOO_HIGH": "Temp. trop haute",
        "MSG_TEMP_TOO_LOW": "Temp. trop basse",
        "MSG_PID_BAD_HEATER_ID": "PID: chauffage invalide",
        "MSG_PID_TEMP_TOO_HIGH": "PID: temp. trop haute",
        "MSG_PID_TIMEOUT": "PID: délai dépassé",
        "MSG_BED_TRAMMING_MANUAL": "Niv. manuel",
        "MSG_BED_TRAMMING_RAISE": "Monter au palpeur",
        "MSG_BED_TRAMMING_IN_RANGE": "Coins nivelés",
        "MSG_BED_TRAMMING_GOOD_POINTS": "Bons points: ",
        "MSG_BED_TRAMMING_LAST_Z": "Dernier Z: ",
        "MSG_INFO_MENU": "À propos",
        "MSG_INFO_PRINTER_MENU": "Imprimante",
        "MSG_INFO_BOARD_MENU": "Carte",
        "MSG_INFO_THERMISTOR_MENU": "Thermistances",
        "MSG_INFO_STATS_MENU": "Statistiques",
        "MSG_INFO_PRINT_COUNT": "Total impressions",
        "MSG_INFO_COMPLETED_PRINTS": "Terminées",
        "MSG_INFO_PRINT_TIME": "Temps impression",
        "MSG_INFO_PRINT_LONGEST": "Plus longue impr.",
        "MSG_INFO_PRINT_FILAMENT": "Filament total",
        "MSG_INFO_MIN_TEMP": "Temp. minimale",
        "MSG_INFO_MAX_TEMP": "Temp. maximale",
        "MSG_INFO_RUNAWAY_ON": "Protection active",
        "MSG_INFO_RUNAWAY_OFF": "Protection inactive",
        "MSG_INFO_BAUDRATE": "Bauds",
        "MSG_INFO_PROTOCOL": "Protocole",
        "MSG_INFO_PSU": "Alimentation",
        "MSG_INFO_EXTRUDERS": "Extrudeurs",
        "MSG_MEDIA_SORT": "Trier SD",
        "MSG_MEDIA_INSERTED_SD": "SD insérée",
        "MSG_MEDIA_INSERTED_USB": "USB inséré",
        "MSG_MEDIA_REMOVED_SD": "SD retirée",
        "MSG_MEDIA_REMOVED_USB": "USB retiré",
        "MSG_MEDIA_INIT_FAIL": "Échec démarrage",
        "MSG_MEDIA_INIT_FAIL_SD": "Échec démarr. SD",
        "MSG_MEDIA_INIT_FAIL_USB": "Échec démarr. USB",
        "MSG_MEDIA_READ_ERROR": "Erreur lecture",
        "MSG_MEDIA_UPDATE": "Actualiser média",
        "MSG_USB_FD_WAITING_FOR_MEDIA": "Attendre USB",
        "MSG_USB_FD_MEDIA_REMOVED": "USB retiré",
        "MSG_ATTACH_MEDIA": "Monter média",
        "MSG_ATTACH_SD": "Monter SD",
        "MSG_ATTACH_USB": "Monter USB",
        "MSG_RELEASE_MEDIA": "Éjecter média",
        "MSG_RELEASE_SD": "Éjecter SD",
        "MSG_RELEASE_USB": "Éjecter USB",
        "MSG_CHANGE_MEDIA": "Actualiser média",
        "MSG_CHANGE_SD": "Choisir SD",
        "MSG_CHANGE_USB": "Choisir USB",
        "MSG_RUN_AUTOFILES": "Fichiers auto",
        "MSG_RUN_AUTOFILES_SD": "Auto-fich. SD",
        "MSG_RUN_AUTOFILES_USB": "Auto-fich. USB",
        "MSG_MEDIA_MENU": "Choisir média",
        "MSG_MEDIA_MENU_SD": "Choisir sur SD",
        "MSG_MEDIA_MENU_USB": "Fichiers USB",
        "MSG_NO_MEDIA": "Aucun média",
        "MSG_TRAMMING_WIZARD": "Assist. molettes",
        "MSG_SELECT_ORIGIN": "Choisir coin",
        "MSG_LAST_VALUE_SP": "Dernière val. ",
        "MSG_HOMING": "Référencement",
        "MSG_HOME_ALL": "Origine XYZ",
        "MSG_HOME_FIRST": "Origine %s avant",
        "MSG_RUNOUT_SENSOR": "Capteur filament",
        "MSG_OUTAGE_RECOVERY": "Reprendre impression",
        "MSG_ADVANCE_K": "Avance K",
        "MSG_AUTORETRACT": "Rétraction auto",
        "MSG_FILAMENT_LOAD": "Charger mm",
        "MSG_FILAMENT_UNLOAD": "Retirer mm",
    },
    "de": {
        "LANGUAGE": "Deutsch",
        "MSG_BRIGHTNESS": "LCD-Helligkeit",
        "MSG_BRIGHTNESS_OFF": "LCD ausschalten",
        "MSG_SCREEN_TIMEOUT": "LCD-Zeitlimit",
        "MSG_INPUT_SHAPING": "Schwing.filter",
        "MSG_SHAPING_ENABLE_N": "Filter @ an",
        "MSG_SHAPING_DISABLE_N": "Filter @ aus",
        "MSG_SHAPING_FREQ_N": "Frequenz @",
        "MSG_SHAPING_ZETA_N": "Dämpfung @",
        "MSG_HOTEND_IDLE_TIMEOUT": "Hotend-Ruhe",
        "MSG_HOTEND_IDLE_DISABLE": "Ruhezeit aus",
        "MSG_HOTEND_IDLE_NOZZLE_TARGET": "Düse Ruhetemp.",
        "MSG_HOTEND_IDLE_BED_TARGET": "Bett Ruhetemp.",
        "MSG_PROBE_WIZARD": "Sonden-Ass.",
        "MSG_PROBE_WIZARD_PROBING": "Referenz messen",
        "MSG_PROBE_WIZARD_MOVING": "Zur Position",
        "MSG_INFO_BUILD": "Erstelldatum",
        "MSG_BUTTON_DONE": "Fertig",
        "MSG_BUTTON_SKIP": "Überspringen",
        "MSG_TIMEOUT": "Zeitlimit",
        "MSG_TEMPERATURE": "Temperatur",
        "MSG_LCD_ON": "Ein",
        "MSG_LCD_OFF": "Aus",
        "MSG_PID_AUTOTUNE": "PID-Autoabgleich",
        "MSG_PID_AUTOTUNE_E": "PID-Abgleich *",
        "MSG_PID_CYCLE": "PID-Zyklen",
        "MSG_PID_AUTOTUNE_DONE": "PID-Abgleich OK",
        "MSG_PID_AUTOTUNE_FAILED": "PID-Abgleich fehlg.",
        "MSG_BAD_HEATER_ID": "Heizer ungültig",
        "MSG_TEMP_TOO_HIGH": "Temp. zu hoch",
        "MSG_TEMP_TOO_LOW": "Temp. zu niedrig",
        "MSG_PID_BAD_HEATER_ID": "PID: Heizer ungültig",
        "MSG_PID_TEMP_TOO_HIGH": "PID: Temp. zu hoch",
        "MSG_PID_TIMEOUT": "PID: Zeitlimit",
        "MSG_BED_TRAMMING_MANUAL": "Manuell ausr.",
        "MSG_BED_TRAMMING_RAISE": "Bis Sonde heben",
        "MSG_BED_TRAMMING_IN_RANGE": "Ecken OK",
        "MSG_BED_TRAMMING_GOOD_POINTS": "Gute Punkte: ",
        "MSG_BED_TRAMMING_LAST_Z": "Letztes Z: ",
        "MSG_INFO_MENU": "Über Drucker",
        "MSG_INFO_PRINTER_MENU": "Drucker",
        "MSG_INFO_BOARD_MENU": "Platine",
        "MSG_INFO_THERMISTOR_MENU": "Thermistoren",
        "MSG_INFO_STATS_MENU": "Statistik",
        "MSG_INFO_PRINT_COUNT": "Drucke gesamt",
        "MSG_INFO_COMPLETED_PRINTS": "Abgeschlossen",
        "MSG_INFO_PRINT_TIME": "Druckzeit",
        "MSG_INFO_PRINT_LONGEST": "Längster Druck",
        "MSG_INFO_PRINT_FILAMENT": "Filament gesamt",
        "MSG_INFO_MIN_TEMP": "Min. Temperatur",
        "MSG_INFO_MAX_TEMP": "Max. Temperatur",
        "MSG_INFO_RUNAWAY_ON": "Schutz aktiv",
        "MSG_INFO_RUNAWAY_OFF": "Schutz inaktiv",
        "MSG_INFO_BAUDRATE": "Baudrate",
        "MSG_INFO_PROTOCOL": "Protokoll",
        "MSG_INFO_PSU": "Netzteil",
        "MSG_INFO_EXTRUDERS": "Extruder",
        "MSG_MEDIA_SORT": "SD sortieren",
        "MSG_MEDIA_INSERTED_SD": "SD eingelegt",
        "MSG_MEDIA_INSERTED_USB": "USB eingelegt",
        "MSG_MEDIA_REMOVED_SD": "SD entfernt",
        "MSG_MEDIA_REMOVED_USB": "USB entfernt",
        "MSG_MEDIA_INIT_FAIL": "Startfehler",
        "MSG_MEDIA_INIT_FAIL_SD": "SD-Startfehler",
        "MSG_MEDIA_INIT_FAIL_USB": "USB-Startfehler",
        "MSG_MEDIA_READ_ERROR": "Lesefehler",
        "MSG_MEDIA_UPDATE": "Medium aktual.",
        "MSG_USB_FD_WAITING_FOR_MEDIA": "USB abwarten",
        "MSG_USB_FD_MEDIA_REMOVED": "USB entfernt",
        "MSG_ATTACH_MEDIA": "Medium einbinden",
        "MSG_ATTACH_SD": "SD einbinden",
        "MSG_ATTACH_USB": "USB einbinden",
        "MSG_RELEASE_MEDIA": "Medium auswerfen",
        "MSG_RELEASE_SD": "SD auswerfen",
        "MSG_RELEASE_USB": "USB auswerfen",
        "MSG_CHANGE_MEDIA": "Medium wechseln",
        "MSG_CHANGE_SD": "SD wählen",
        "MSG_CHANGE_USB": "USB wählen",
        "MSG_RUN_AUTOFILES": "Autodateien",
        "MSG_RUN_AUTOFILES_SD": "SD-Autodateien",
        "MSG_RUN_AUTOFILES_USB": "USB-Autodateien",
        "MSG_MEDIA_MENU": "Medium wählen",
        "MSG_MEDIA_MENU_SD": "Von SD wählen",
        "MSG_MEDIA_MENU_USB": "USB-Dateien",
        "MSG_NO_MEDIA": "Kein Medium",
        "MSG_TRAMMING_WIZARD": "Ausricht-Ass.",
        "MSG_SELECT_ORIGIN": "Ecke wählen",
        "MSG_LAST_VALUE_SP": "Letzter Wert ",
        "MSG_HOMING": "Referenzfahrt",
        "MSG_HOME_ALL": "Alle referenz.",
        "MSG_HOME_FIRST": "%s zuerst ref.",
        "MSG_RUNOUT_SENSOR": "Filamentsensor",
        "MSG_OUTAGE_RECOVERY": "Druck fortsetzen",
        "MSG_ADVANCE_K": "Vorschubfaktor K",
        "MSG_AUTORETRACT": "Auto-Rückzug",
        "MSG_FILAMENT_LOAD": "Laden mm",
        "MSG_FILAMENT_UNLOAD": "Entladen mm",
    },
}

BASE = Path(__file__).resolve().parent
CACHE = BASE / "cache"
OUT = BASE / "generated" / "Marlin-KP3S-Firmware-V1"
FW_OUT = BASE / "firmware_output"
FLASH_DIR = FW_OUT / "FLASH_KP3S"
LOG = BASE / "BUILD.log"

MARLIN_ZIP = CACHE / f"Marlin-{TAG}.zip"
CONFIG_H = CACHE / "Configuration.h"
CONFIG_ADV_H = CACHE / "Configuration_adv.h"

MARLIN_URL = f"https://codeload.github.com/MarlinFirmware/Marlin/zip/{MARLIN_COMMIT}"
CONFIG_H_URL = (
    f"https://raw.githubusercontent.com/MarlinFirmware/Configurations/{CONFIG_COMMIT}/"
    "config/examples/Kingroon/KP3S/Configuration.h"
)
CONFIG_ADV_H_URL = (
    f"https://raw.githubusercontent.com/MarlinFirmware/Configurations/{CONFIG_COMMIT}/"
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



def patch_v1_native_languages():
    """Complete V1-visible translations without allowing Language_en fallback."""
    language_dir = OUT / "Marlin" / "src" / "lcd" / "language"

    # A typo in a supplement key must fail the build instead of silently adding
    # an unused symbol. Every V1 override has to exist in the pinned English
    # language catalog used by Marlin as the canonical message set.
    english = read(language_dir / "language_en.h")
    all_keys = set().union(*(set(values) for values in V1_NATIVE_LANGUAGE_SUPPLEMENTS.values()))
    unknown = sorted(key for key in all_keys if not re.search(rf"^[ \t]*LSTR[ \t]+{re.escape(key)}[ \t]*=", english, flags=re.M))
    if unknown:
        raise RuntimeError(f"Unknown V1 Marlin language keys: {', '.join(unknown)}")

    for code, translations in V1_NATIVE_LANGUAGE_SUPPLEMENTS.items():
        path = language_dir / f"language_{code}.h"
        text = read(path)
        namespace = f"namespace LanguageNarrow_{code} {{"
        wide_namespace = f"namespace LanguageWide_{code} {{"
        start = text.find(namespace)
        wide = text.find(wide_namespace, start + len(namespace))
        if start < 0 or wide < 0:
            raise RuntimeError(f"Unexpected Marlin language namespace structure: {path}")

        # The narrow namespace closes immediately before LanguageWide_<code>.
        close = text.rfind("}", start, wide)
        if close < 0:
            raise RuntimeError(f"Could not locate LanguageNarrow_{code} closing brace: {path}")

        narrow = text[start:close]
        additions = []
        for key, value in translations.items():
            if '"' in value or "\\" in value:
                raise RuntimeError(f"Unsafe V1 translation literal for {code}/{key}: {value!r}")
            replacement = f'  LSTR {key:<34} = _UxGT("{value}");'
            rx = re.compile(rf"^[ \t]*LSTR[ \t]+{re.escape(key)}[ \t]*=[^\r\n]*$", flags=re.M)
            matches = list(rx.finditer(narrow))
            if len(matches) > 1:
                raise RuntimeError(f"Duplicate {key} in LanguageNarrow_{code}: {path}")
            if matches:
                narrow = rx.sub(replacement, narrow, count=1)
            else:
                additions.append(replacement)

        if additions:
            narrow = narrow.rstrip() + "\n\n  // KINGROON KP3S V1 language completion\n" + "\n".join(additions) + "\n"
        text = text[:start] + narrow + text[close:]
        write(path, text)

        # Re-read the patched narrow namespace and prove every V1 key is unique.
        check = read(path)
        check_start = check.find(namespace)
        check_wide = check.find(wide_namespace, check_start + len(namespace))
        check_close = check.rfind("}", check_start, check_wide)
        check_narrow = check[check_start:check_close]
        for key in translations:
            count = len(re.findall(rf"^[ \t]*LSTR[ \t]+{re.escape(key)}[ \t]*=", check_narrow, flags=re.M))
            if count != 1:
                raise RuntimeError(f"V1 translation patch produced {count} entries for {code}/{key}: {path}")
        print(f"[OK] Complete {code} V1-visible Marlin translations ({len(translations)} entries)")

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
    menu_advanced = OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_advanced.cpp"
    menu_probe_level = OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_probe_level.cpp"
    menu_main = OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_main.cpp"
    menu_info = OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_info.cpp"
    menu_language = OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_language.cpp"
    g29 = OUT / "Marlin" / "src" / "gcode" / "bedlevel" / "abl" / "G29.cpp"
    g28 = OUT / "Marlin" / "src" / "gcode" / "calibrate" / "G28.cpp"
    probe_cpp = OUT / "Marlin" / "src" / "module" / "probe.cpp"
    joystick_h = OUT / "Marlin" / "src" / "feature" / "joystick.h"
    settings_cpp = OUT / "Marlin" / "src" / "module" / "settings.cpp"
    queue_cpp = OUT / "Marlin" / "src" / "gcode" / "queue.cpp"
    eeprom_gcode = OUT / "Marlin" / "src" / "gcode" / "eeprom" / "M500-M504.cpp"

    patch_v1_native_languages()

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

    # Optional BLTouch support for this KP3S V1 hardware configuration.
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
    set_define(cfg, "CUSTOM_MACHINE_NAME", '#define CUSTOM_MACHINE_NAME "KINGROON KP3S V1"', "Set unambiguous V1 machine identity")

    # High-temperature V1 hotend profile. HEATER_0_MAXTEMP is the hard fault
    # ceiling; HOTEND_OVERSHOOT is subtracted from it by Marlin when computing
    # the highest selectable target. 350 - 10 = 340C.
    set_define(
        cfg,
        "TEMP_SENSOR_0",
        f"#define TEMP_SENSOR_0 {V1_HOTEND_SENSOR} // V1: 100k B3950 350C high-temperature thermistor",
        "Use the V1 350C-rated high-temperature hotend thermistor",
    )
    set_define(
        cfg,
        "HEATER_0_MAXTEMP",
        f"#define HEATER_0_MAXTEMP {V1_HOTEND_MAXTEMP_C} // V1 hard safety ceiling",
        "Set V1 hotend hard maximum temperature",
    )
    set_define(
        cfg,
        "HOTEND_OVERSHOOT",
        f"#define HOTEND_OVERSHOOT {V1_HOTEND_OVERSHOOT_C} // V1 max target = {V1_HOTEND_TARGET_MAX_C}C",
        "Allow a 340C hotend target with a 10C safety margin",
    )
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
    set_bool_define(adv, "MEDIA_MENU_AT_TOP", True, "Put SD / file selection first in the main menu")
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

    # Native Marlin idle-heater protection. This is especially useful with the
    # high-temperature profile: after ten minutes without extrusion activity,
    # a hot nozzle is commanded to cool to 0C. The native Configuration menu
    # exposes the timeout settings at runtime.
    set_bool_define(adv, "HOTEND_IDLE_TIMEOUT", True, "Enable high-temperature hotend idle protection")
    set_define(
        adv,
        "HOTEND_IDLE_TIMEOUT_SEC",
        f"  #define HOTEND_IDLE_TIMEOUT_SEC {V1_HOTEND_IDLE_TIMEOUT_SEC} // V1: 10 minutes",
        "Set V1 hotend idle timeout",
    )
    set_define(adv, "HOTEND_IDLE_MIN_TRIGGER", "  #define HOTEND_IDLE_MIN_TRIGGER 180", "Set V1 hotend idle protection trigger")
    set_define(adv, "HOTEND_IDLE_NOZZLE_TARGET", "  #define HOTEND_IDLE_NOZZLE_TARGET 0", "Cool the nozzle after the V1 idle timeout")
    set_define(adv, "HOTEND_IDLE_BED_TARGET", "  #define HOTEND_IDLE_BED_TARGET 0", "Cool the bed after the V1 idle timeout")

    # Five-language Marlin menu. English is always language index 0 / default.
    regex_once(
        cfg,
        r"^[ \t]*#define[ \t]+LCD_LANGUAGE[ \t]+[^\r\n]+$",
        V1_LCD_LANGUAGE_DEFINES,
        "Configure five LCD languages with English as the V1 default",
    )
    regex_once(
        adv,
        r"^[ \t]*//[ \t]*#define[ \t]+LCD_LANGUAGE_AUTO_SAVE\b[^\r\n]*$",
        "#define LCD_LANGUAGE_AUTO_SAVE",
        "Persist the selected LCD language",
    )
    replace_once(
        ui_cpp,
        "uint8_t MarlinUI::language; // Initialized by settings.load",
        "uint8_t MarlinUI::language = 0; // V1 primary/default: English; EEPROM may override after user selection",
        "Make English the explicit V1 default LCD language",
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
#define KP3S_RUNTIME_BLTOUCH          // OFF by default; enabled from Configuration > BLTouch On

// PA4 is reserved for filament runout. MPU6050 uses the FFC again.
// Default: SDA=PD9/FFC17, SCL=PD8/FFC16. Runtime menu can swap SDA/SCL.
// VCC=FFC1/3.3V, GND=FFC2.
#define KP3S_MPU6050
#define KP3S_MPU6050_SOFT_I2C_DELAY_US 8
#define KP3S_MPU6050_POLL_IDLE_MS 20UL
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
// The display samples DIN on the rising CLK edge. Each bit therefore does:
// CLK LOW -> stabilize MOSI -> wait 3 us -> CLK HIGH -> wait 3 us.
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

    replace_once(
        ui_dogm_cpp,
        r'''  void MenuItem_confirm::draw_select_screen(FSTR_P const yes, FSTR_P const no, const bool yesno, FSTR_P const fpre, const char * const string/*=nullptr*/, FSTR_P const fsuf/*=nullptr*/) {
    ui.draw_select_screen_prompt(fpre, string, fsuf);
    if (no)  draw_boxed_string(1, LCD_HEIGHT - 1, no, !yesno);
    if (yes) draw_boxed_string(LCD_WIDTH - (utf8_strlen(yes) * (USE_WIDE_GLYPH ? 2 : 1) + 1), LCD_HEIGHT - 1, yes, yesno);
  }''',
        r'''  #if ENABLED(NOKIA5110_LCD)
    static void kp3s_draw_select_choice(FSTR_P const text, const bool right, const bool selected) {
      if (!text) return;
      const u8g_uint_t by = LCD_HEIGHT * MENU_FONT_HEIGHT;
      const u8g_uint_t half = LCD_PIXEL_WIDTH / 2;
      const u8g_uint_t x = right ? half + 1 : 0;
      const pixel_len_t width = right ? LCD_PIXEL_WIDTH - x : half - 1;
      const pixel_len_t inner = width > 4 ? width - 4 : width;
      const uint8_t fit_chars = _MAX(uint8_t(1), uint8_t(inner / MENU_FONT_WIDTH));
      const uint8_t text_chars = utf8_strlen(text);
      uint8_t offset_chars = 0;
      if (selected && text_chars > fit_chars) {
        offset_chars = kp3s_marquee_offset(text, right ? 0xFD : 0xFC, fit_chars, text_chars);
        ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
      }
      PGM_P const shown = FTOP(text) + utf8_byte_pos_by_char_num_P(FTOP(text), offset_chars);
      const pixel_len_t text_px = uxg_GetUtf8StrPixelWidthP(u8g.getU8g(), shown);
      const pixel_len_t shown_px = _MIN(text_px, inner);
      if (selected) {
        u8g.setColorIndex(1);
        u8g.drawBox(x, by - MENU_FONT_ASCENT, width, MENU_FONT_HEIGHT);
        u8g.setColorIndex(0);
      }
      // Long labels stay clipped to their own half; the selected label scrolls
      // inside that half so translations such as Cancelar / Imprimir remain readable.
      const u8g_uint_t text_x = x + 2 + (text_px <= inner ? (inner - shown_px) / 2 : 0);
      lcd_moveto(text_x, by);
      lcd_put_u8str_max_P(shown, inner);
      if (selected) u8g.setColorIndex(1);
    }
  #endif

  void MenuItem_confirm::draw_select_screen(FSTR_P const yes, FSTR_P const no, const bool yesno, FSTR_P const fpre, const char * const string/*=nullptr*/, FSTR_P const fsuf/*=nullptr*/) {
    ui.draw_select_screen_prompt(fpre, string, fsuf);
    #if ENABLED(NOKIA5110_LCD)
      // The stock DOGM layout right-aligns YES and left-aligns NO. On the
      // 84-pixel KP3S display long translations can overlap. Give each choice
      // its own clipped half-screen field so they can never compete for pixels.
      const u8g_uint_t by = LCD_HEIGHT * MENU_FONT_HEIGHT;
      u8g.setColorIndex(0);
      u8g.drawBox(0, by - MENU_FONT_ASCENT, LCD_PIXEL_WIDTH, MENU_FONT_HEIGHT);
      u8g.setColorIndex(1);
      kp3s_draw_select_choice(no, false, !yesno);
      kp3s_draw_select_choice(yes, true, yesno);
    #else
      if (no)  draw_boxed_string(1, LCD_HEIGHT - 1, no, !yesno);
      if (yes) draw_boxed_string(LCD_WIDTH - (utf8_strlen(yes) * (USE_WIDE_GLYPH ? 2 : 1) + 1), LCD_HEIGHT - 1, yes, yesno);
    #endif
  }''',
        "Keep two-choice confirmation labels in separate Nokia half-screen fields",
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
              if (kp3s_ui_selection_mode || kp3s_ui_edit_mode) break;
            #endif
            encoderDiff = -int8_t(ENCODER_STEPS_PER_MENU_ITEM * epps);
            kp3s_feedback_sound(KP3SFeedback::NAV);
            TERN_(HAS_MARLINUI_MENU, refresh());
            break;

          case KP3SUE5000Action::DOWN:
            #if ENABLED(KP3S_CONTEXT_NAVIGATION)
              if (kp3s_ui_selection_mode || kp3s_ui_edit_mode) break;
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
                kp3s_feedback_sound(KP3SFeedback::BACK);
              }
            #endif
            break;

          case KP3SUE5000Action::BACK:
            #if HAS_MARLINUI_MENU
              if (!on_status_screen()) {
                goto_previous_screen();
                refresh();
                kp3s_feedback_sound(KP3SFeedback::BACK);
              }
            #endif
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
        "Initialize backlight and UE5000 panel",
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
        "Add V1 feedback to SD pause/resume",
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
        "Add pause beep for every pause mode",
    )

    # V1 low-level display diagnostic independent of U8glib / MarlinUI.
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
 * KP3S Marlin Firmware V1 - dual MPU6050 / IMU runtime interface.
 *
 * Up to two MPU6050 devices may share the dedicated software-I2C pair by
 * using the two legal AD0 addresses (0x68 / 0x69). Each address can be
 * assigned to the bed or toolhead. MPU I/O is strictly idle-only: an active
 * or paused print blocks every background sensor transaction; normal queued motion does too.
 */
#pragma once

#include "../inc/MarlinConfig.h"

#if ENABLED(KP3S_MPU6050)
enum class KP3SMPU6050BusStatus : uint8_t {
  DISABLED,
  BUSY,
  OK,
  SDA_STUCK_LOW,
  SCL_STUCK_LOW,
  NO_ACK
};

enum class KP3SMPU6050Role : uint8_t {
  UNUSED = 0,
  BED = 1,
  TOOLHEAD = 2
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
extern uint8_t kp3s_mpu6050_role_68;
extern uint8_t kp3s_mpu6050_role_69;

// Toolhead and bed calibrations are independent V1 state.
extern float kp3s_mpu6050_toolhead_temp_offset_c;
extern float kp3s_mpu6050_toolhead_level_zero_roll_deg;
extern float kp3s_mpu6050_toolhead_level_zero_pitch_deg;
extern bool kp3s_mpu6050_toolhead_level_zero_valid;

// Bed-mounted sensor has an independent calibration.
extern float kp3s_mpu6050_bed_temp_offset_c;
extern float kp3s_mpu6050_bed_level_zero_roll_deg;
extern float kp3s_mpu6050_bed_level_zero_pitch_deg;
extern bool kp3s_mpu6050_bed_level_zero_valid;

void kp3s_mpu6050_init();
void kp3s_mpu6050_set_enabled(const bool enabled);
void kp3s_mpu6050_set_swap_lines(const bool swap_lines);
bool kp3s_mpu6050_lines_swapped();
void kp3s_mpu6050_task(const millis_t now);
void kp3s_mpu6050_sanitize_configuration();

KP3SMPU6050BusStatus kp3s_mpu6050_test_bus();
bool kp3s_mpu6050_detect_now();
bool kp3s_mpu6050_detected_at(const uint8_t address);
bool kp3s_mpu6050_detected_role(const KP3SMPU6050Role role);
uint8_t kp3s_mpu6050_detected_count();
uint8_t kp3s_mpu6050_address_for_role(const KP3SMPU6050Role role);
uint8_t kp3s_mpu6050_last_bus_address();
uint8_t kp3s_mpu6050_who_am_i_at(const uint8_t address);
bool kp3s_mpu6050_who_valid_at(const uint8_t address);

KP3SMPU6050Role kp3s_mpu6050_role_for_address(const uint8_t address);
void kp3s_mpu6050_set_role(const uint8_t address, const KP3SMPU6050Role role);

// Role-specific orientation / motion / temperature APIs.
bool kp3s_mpu6050_level_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg);
bool kp3s_mpu6050_level_raw_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg);
bool kp3s_mpu6050_motion_stable_for_role(const KP3SMPU6050Role role);
bool kp3s_mpu6050_level_zero_candidate_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg);
bool kp3s_mpu6050_set_level_zero_for_role(const KP3SMPU6050Role role);
void kp3s_mpu6050_clear_level_zero_for_role(const KP3SMPU6050Role role);
bool kp3s_mpu6050_startup_level_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg, bool &level_ok);
bool kp3s_mpu6050_startup_notice_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg, bool &level_ok);
uint8_t kp3s_mpu6050_startup_progress_pct_for_role(const KP3SMPU6050Role role);
bool kp3s_mpu6050_temperature_raw_c_for_role(const KP3SMPU6050Role role, float &temperature_c);
bool kp3s_mpu6050_temperature_c_for_role(const KP3SMPU6050Role role, float &temperature_c);
bool kp3s_mpu6050_temperature_delta_c_for_role(const KP3SMPU6050Role role, float &delta_c);
bool kp3s_mpu6050_motion_for_role(const KP3SMPU6050Role role, float &rms_g, float &peak_g, float &instant_g);
uint16_t kp3s_mpu6050_sample_rate_hz_for_role(const KP3SMPU6050Role role, const millis_t now=millis());
const KP3SMPU6050Sample& kp3s_mpu6050_sample_for_role(const KP3SMPU6050Role role);

// Bounded 200 Hz capture. X requires TOOLHEAD; Y requires BED.
void kp3s_mpu6050_resonance_capture_start(const KP3SMPU6050Role role=KP3SMPU6050Role::TOOLHEAD);
bool kp3s_mpu6050_resonance_capture_analyze(float &frequency_hz, uint8_t &confidence_pct);
uint16_t kp3s_mpu6050_resonance_samples();
bool kp3s_mpu6050_resonance_capturing();
KP3SMPU6050Role kp3s_mpu6050_resonance_role();

#endif
''',
        encoding="utf-8",
    )
    mpu6050_impl_h.write_text(
        r'''/**
 * KP3S Marlin Firmware V1 - dual MPU6050 / IMU software I2C.
 *
 * V1 operating rules:
 *  - only 0x68 and 0x69 are ever probed as MPU6050 devices;
 *  - up to two devices are tracked independently;
 *  - each device is explicitly assigned to BED / TOOLHEAD / UNUSED;
 *  - active or paused printing performs no MPU I/O, without exceptions;
 *  - ordinary queued motion also blocks background MPU I/O;
 *  - retries / bus recovery / reconfiguration are idle-only;
 *  - resonance capture is explicit and bounded, never a background print task.
 */
#pragma once
#include "../inc/MarlinConfig.h"
#include "../HAL/shared/Delay.h"
#include "../MarlinCore.h"
#include "../module/planner.h"
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

bool kp3s_mpu6050_runtime_enabled = true;
bool kp3s_mpu6050_swap_lines = false;
uint8_t kp3s_mpu6050_role_68 = uint8_t(KP3SMPU6050Role::UNUSED);
uint8_t kp3s_mpu6050_role_69 = uint8_t(KP3SMPU6050Role::UNUSED);

float kp3s_mpu6050_toolhead_temp_offset_c = 0.0f;
float kp3s_mpu6050_toolhead_level_zero_roll_deg = 0.0f;
float kp3s_mpu6050_toolhead_level_zero_pitch_deg = 0.0f;
bool kp3s_mpu6050_toolhead_level_zero_valid = false;
float kp3s_mpu6050_bed_temp_offset_c = 0.0f;
float kp3s_mpu6050_bed_level_zero_roll_deg = 0.0f;
float kp3s_mpu6050_bed_level_zero_pitch_deg = 0.0f;
bool kp3s_mpu6050_bed_level_zero_valid = false;

struct KP3SMPU6050DeviceState {
  uint8_t address, who;
  bool who_valid, present, stop_before_read;
  uint8_t faults;
  millis_t next_retry;
  KP3SMPU6050Sample data;

  bool fusion_valid, stable, gyro_bias_valid, motion_lp_valid;
  float roll_deg, pitch_deg;
  float gyro_bias_x, gyro_bias_y, gyro_bias_z;
  uint8_t gyro_bias_samples;
  float gyro_bias_sum_x, gyro_bias_sum_y, gyro_bias_sum_z;
  millis_t fusion_ms, stable_since;
  float stable_roll_deg, stable_pitch_deg;
  float lp_ax, lp_ay, lp_az;
  float vib_rms2, vib_peak_g, vib_now_g;

  uint8_t boot_samples;
  float boot_roll_sum, boot_pitch_sum;
  bool boot_level_ready, boot_level_ok;
  float boot_roll_deg, boot_pitch_deg;
  millis_t boot_notice_until, boot_last_good_ms;

  uint8_t temp_baseline_samples;
  float temp_baseline_sum, boot_temp_raw_c;
  bool boot_temp_valid;
};

static KP3SMPU6050DeviceState kp3s_mpu_devices[2] = {};
static uint8_t kp3s_mpu_last_bus_addr = 0;
static millis_t kp3s_mpu_next_poll = 0;
static uint8_t kp3s_mpu_poll_index = 0;

static constexpr uint8_t KP3S_MPU_BOOT_SAMPLES_REQUIRED = 40;
static constexpr uint8_t KP3S_MPU_TEMP_BASELINE_SAMPLES = 20;
static constexpr millis_t KP3S_MPU_SAMPLE_STALE_MS = 1500UL;

// Resonance capture: 192 samples x 3 axes = 1152 bytes (~0.96 s at 200 Hz).
static constexpr uint16_t KP3S_RESONANCE_CAPTURE_MAX = 192;
static int16_t kp3s_res_ax[KP3S_RESONANCE_CAPTURE_MAX], kp3s_res_ay[KP3S_RESONANCE_CAPTURE_MAX], kp3s_res_az[KP3S_RESONANCE_CAPTURE_MAX];
static uint16_t kp3s_res_count = 0;
static bool kp3s_res_capture = false;
static uint8_t kp3s_res_source_addr = 0;
static bool kp3s_res_restore_pending = false;
static uint8_t kp3s_res_restore_addr = 0;
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

static bool kp3s_mpu_job_active(const millis_t now) {
  bool active = printingIsActive() || printingIsPaused();
  #if ENABLED(KP3S_SMART_UI)
    active |= kp3s_serial_printing(now) || kp3s_serial_print_paused();
  #else
    UNUSED(now);
  #endif
  return active;
}

// Background IMU work must never share the normal motion path. The only
// intentional exception is the explicit resonance-capture branch below.
static bool kp3s_mpu_background_blocked(const millis_t now) {
  return kp3s_mpu_job_active(now) || planner.has_blocks_queued();
}

static KP3SMPU6050DeviceState* kp3s_mpu_device_at(const uint8_t address) {
  if (address == 0x68) return &kp3s_mpu_devices[0];
  if (address == 0x69) return &kp3s_mpu_devices[1];
  return nullptr;
}

static const KP3SMPU6050DeviceState* kp3s_mpu_device_at_const(const uint8_t address) {
  return kp3s_mpu_device_at(address);
}

static KP3SMPU6050Role kp3s_role_value(const uint8_t raw) {
  return raw == uint8_t(KP3SMPU6050Role::BED) ? KP3SMPU6050Role::BED
       : raw == uint8_t(KP3SMPU6050Role::TOOLHEAD) ? KP3SMPU6050Role::TOOLHEAD
       : KP3SMPU6050Role::UNUSED;
}

KP3SMPU6050Role kp3s_mpu6050_role_for_address(const uint8_t address) {
  return address == 0x68 ? kp3s_role_value(kp3s_mpu6050_role_68)
       : address == 0x69 ? kp3s_role_value(kp3s_mpu6050_role_69)
       : KP3SMPU6050Role::UNUSED;
}

uint8_t kp3s_mpu6050_address_for_role(const KP3SMPU6050Role role) {
  if (role == KP3SMPU6050Role::UNUSED) return 0;
  if (kp3s_mpu6050_role_for_address(0x68) == role) return 0x68;
  if (kp3s_mpu6050_role_for_address(0x69) == role) return 0x69;
  return 0;
}

static KP3SMPU6050DeviceState* kp3s_mpu_device_for_role(const KP3SMPU6050Role role) {
  return kp3s_mpu_device_at(kp3s_mpu6050_address_for_role(role));
}

static const KP3SMPU6050DeviceState* kp3s_mpu_device_for_role_const(const KP3SMPU6050Role role) {
  return kp3s_mpu_device_for_role(role);
}

static bool kp3s_mpu_data_fresh(const KP3SMPU6050DeviceState &dev) {
  return dev.present && dev.data.valid && PENDING(millis(), dev.data.updated_ms + KP3S_MPU_SAMPLE_STALE_MS);
}

static void kp3s_clear_role_calibration(const KP3SMPU6050Role role, const bool clear_temp=true) {
  if (role == KP3SMPU6050Role::TOOLHEAD) {
    kp3s_mpu6050_toolhead_level_zero_roll_deg = kp3s_mpu6050_toolhead_level_zero_pitch_deg = 0.0f;
    kp3s_mpu6050_toolhead_level_zero_valid = false;
    if (clear_temp) kp3s_mpu6050_toolhead_temp_offset_c = 0.0f;
  }
  else if (role == KP3SMPU6050Role::BED) {
    kp3s_mpu6050_bed_level_zero_roll_deg = kp3s_mpu6050_bed_level_zero_pitch_deg = 0.0f;
    kp3s_mpu6050_bed_level_zero_valid = false;
    if (clear_temp) kp3s_mpu6050_bed_temp_offset_c = 0.0f;
  }
}

static float kp3s_role_zero_roll(const KP3SMPU6050Role role) {
  return role == KP3SMPU6050Role::BED ? kp3s_mpu6050_bed_level_zero_roll_deg : kp3s_mpu6050_toolhead_level_zero_roll_deg;
}
static float kp3s_role_zero_pitch(const KP3SMPU6050Role role) {
  return role == KP3SMPU6050Role::BED ? kp3s_mpu6050_bed_level_zero_pitch_deg : kp3s_mpu6050_toolhead_level_zero_pitch_deg;
}
static bool kp3s_role_zero_valid(const KP3SMPU6050Role role) {
  return role == KP3SMPU6050Role::BED ? kp3s_mpu6050_bed_level_zero_valid : kp3s_mpu6050_toolhead_level_zero_valid;
}
static float kp3s_role_temp_offset(const KP3SMPU6050Role role) {
  return role == KP3SMPU6050Role::BED ? kp3s_mpu6050_bed_temp_offset_c : kp3s_mpu6050_toolhead_temp_offset_c;
}

static void kp3s_mpu_reset_device_derived(KP3SMPU6050DeviceState &dev, const bool reset_temperature_baseline=true) {
  dev.data.valid = false;
  dev.fusion_valid = dev.stable = dev.gyro_bias_valid = dev.motion_lp_valid = false;
  dev.roll_deg = dev.pitch_deg = 0.0f;
  dev.gyro_bias_x = dev.gyro_bias_y = dev.gyro_bias_z = 0.0f;
  dev.gyro_bias_samples = 0;
  dev.gyro_bias_sum_x = dev.gyro_bias_sum_y = dev.gyro_bias_sum_z = 0.0f;
  dev.fusion_ms = dev.stable_since = 0;
  dev.stable_roll_deg = dev.stable_pitch_deg = 0.0f;
  dev.lp_ax = dev.lp_ay = dev.lp_az = 0.0f;
  dev.vib_rms2 = dev.vib_peak_g = dev.vib_now_g = 0.0f;
  dev.boot_samples = 0;
  dev.boot_roll_sum = dev.boot_pitch_sum = 0.0f;
  dev.boot_level_ready = dev.boot_level_ok = false;
  dev.boot_roll_deg = dev.boot_pitch_deg = 0.0f;
  dev.boot_notice_until = dev.boot_last_good_ms = 0;
  if (reset_temperature_baseline) {
    dev.temp_baseline_samples = 0;
    dev.temp_baseline_sum = dev.boot_temp_raw_c = 0.0f;
    dev.boot_temp_valid = false;
  }
}

static void kp3s_mpu_reset_all_derived(const bool reset_temperature_baseline=true) {
  for (uint8_t i=0; i<2; ++i) kp3s_mpu_reset_device_derived(kp3s_mpu_devices[i], reset_temperature_baseline);
  kp3s_res_capture = false;
  kp3s_res_source_addr = 0;
  kp3s_res_restore_pending = false;
  kp3s_res_restore_addr = 0;
  kp3s_res_count = 0;
  kp3s_res_first_ms = kp3s_res_last_ms = 0;
}

void kp3s_mpu6050_sanitize_configuration() {
  kp3s_mpu6050_role_68 = uint8_t(kp3s_role_value(kp3s_mpu6050_role_68));
  kp3s_mpu6050_role_69 = uint8_t(kp3s_role_value(kp3s_mpu6050_role_69));
  if (kp3s_mpu6050_role_68 != uint8_t(KP3SMPU6050Role::UNUSED)
      && kp3s_mpu6050_role_68 == kp3s_mpu6050_role_69)
    kp3s_mpu6050_role_69 = uint8_t(KP3SMPU6050Role::UNUSED);

  if (!WITHIN(kp3s_mpu6050_toolhead_temp_offset_c,-30.0f,30.0f)) kp3s_mpu6050_toolhead_temp_offset_c=0.0f;
  if (!WITHIN(kp3s_mpu6050_bed_temp_offset_c,-30.0f,30.0f)) kp3s_mpu6050_bed_temp_offset_c=0.0f;
  if (!WITHIN(kp3s_mpu6050_toolhead_level_zero_roll_deg,-180.0f,180.0f)
      || !WITHIN(kp3s_mpu6050_toolhead_level_zero_pitch_deg,-90.0f,90.0f)) {
    kp3s_mpu6050_toolhead_level_zero_roll_deg=kp3s_mpu6050_toolhead_level_zero_pitch_deg=0.0f;
    kp3s_mpu6050_toolhead_level_zero_valid=false;
  }
  if (!WITHIN(kp3s_mpu6050_bed_level_zero_roll_deg,-180.0f,180.0f)
      || !WITHIN(kp3s_mpu6050_bed_level_zero_pitch_deg,-90.0f,90.0f)) {
    kp3s_mpu6050_bed_level_zero_roll_deg=kp3s_mpu6050_bed_level_zero_pitch_deg=0.0f;
    kp3s_mpu6050_bed_level_zero_valid=false;
  }
}

void kp3s_mpu6050_set_role(const uint8_t address, const KP3SMPU6050Role role) {
  if ((address != 0x68 && address != 0x69) || kp3s_mpu_background_blocked(millis())) return;
  const KP3SMPU6050Role clean = role == KP3SMPU6050Role::BED || role == KP3SMPU6050Role::TOOLHEAD ? role : KP3SMPU6050Role::UNUSED;
  uint8_t &slot = address == 0x68 ? kp3s_mpu6050_role_68 : kp3s_mpu6050_role_69;
  uint8_t &other = address == 0x68 ? kp3s_mpu6050_role_69 : kp3s_mpu6050_role_68;
  const KP3SMPU6050Role old_role = kp3s_role_value(slot);
  const KP3SMPU6050Role other_old = kp3s_role_value(other);
  if (old_role == clean && (clean == KP3SMPU6050Role::UNUSED || other_old != clean)) return;

  if (clean != KP3SMPU6050Role::UNUSED && other_old == clean) {
    other = uint8_t(KP3SMPU6050Role::UNUSED);
    kp3s_clear_role_calibration(other_old);
    KP3SMPU6050DeviceState * const other_dev = kp3s_mpu_device_at(address == 0x68 ? 0x69 : 0x68);
    if (other_dev) kp3s_mpu_reset_device_derived(*other_dev, false);
  }
  slot = uint8_t(clean);
  if (old_role != KP3SMPU6050Role::UNUSED) kp3s_clear_role_calibration(old_role);
  if (clean != KP3SMPU6050Role::UNUSED) kp3s_clear_role_calibration(clean);
  KP3SMPU6050DeviceState * const dev = kp3s_mpu_device_at(address);
  if (dev) kp3s_mpu_reset_device_derived(*dev, false);
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

static bool kp3s_mpu_write_reg(KP3SMPU6050DeviceState &dev, const uint8_t reg, const uint8_t val, const bool robust=true) {
  const uint8_t attempts = robust ? 2 : 1;
  for (uint8_t attempt=0; attempt<attempts; ++attempt) {
    if (!kp3s_i2c_start()) {
      if (robust) kp3s_i2c_bus_recover();
      continue;
    }
    if (!kp3s_i2c_write_byte(uint8_t(dev.address << 1)) || !kp3s_i2c_write_byte(reg) || !kp3s_i2c_write_byte(val)) {
      kp3s_i2c_stop();
      if (robust) kp3s_i2c_bus_recover();
      continue;
    }
    kp3s_i2c_stop();
    return true;
  }
  return false;
}

static bool kp3s_mpu_read_regs_mode(const uint8_t address, const uint8_t reg, uint8_t *dst, const uint8_t count, const bool stop_before_read) {
  if (!kp3s_i2c_start()) return false;
  if (!kp3s_i2c_write_byte(uint8_t(address << 1)) || !kp3s_i2c_write_byte(reg)) {
    kp3s_i2c_stop(); return false;
  }
  if (stop_before_read) { kp3s_i2c_stop(); DELAY_US(12); }
  if (!kp3s_i2c_start()) { kp3s_i2c_stop(); return false; }
  if (!kp3s_i2c_write_byte(uint8_t((address << 1) | 1U))) { kp3s_i2c_stop(); return false; }
  for (uint8_t i=0; i<count; ++i)
    if (!kp3s_i2c_read_byte(dst[i], i + 1 < count)) { kp3s_i2c_stop(); return false; }
  kp3s_i2c_stop();
  return true;
}

static bool kp3s_mpu_read_regs(KP3SMPU6050DeviceState &dev, const uint8_t reg, uint8_t *dst, const uint8_t count, const bool robust=true) {
  if (!count) return false;
  if (kp3s_mpu_read_regs_mode(dev.address, reg, dst, count, dev.stop_before_read)) return true;
  if (!robust) return false;
  kp3s_i2c_bus_recover();
  const bool alternate = !dev.stop_before_read;
  if (kp3s_mpu_read_regs_mode(dev.address, reg, dst, count, alternate)) {
    dev.stop_before_read = alternate;
    return true;
  }
  kp3s_i2c_bus_recover();
  return kp3s_mpu_read_regs_mode(dev.address, reg, dst, count, dev.stop_before_read);
}

static void kp3s_mpu_delay_ms(uint16_t ms) { while (ms--) DELAY_US(1000); }

static float kp3s_mpu_raw_temperature_c(const KP3SMPU6050DeviceState &dev) {
  return float(dev.data.temperature) / 340.0f + 36.53f;
}

static void kp3s_mpu_update_derived(KP3SMPU6050DeviceState &dev, const millis_t now) {
  constexpr float ACC_LSB_PER_G = 16384.0f, GYRO_LSB_PER_DPS = 131.0f, RAD_TO_DEG_F = 57.2957795f;
  const float ax=float(dev.data.ax)/ACC_LSB_PER_G, ay=float(dev.data.ay)/ACC_LSB_PER_G, az=float(dev.data.az)/ACC_LSB_PER_G,
              gx=float(dev.data.gx)/GYRO_LSB_PER_DPS, gy=float(dev.data.gy)/GYRO_LSB_PER_DPS, gz=float(dev.data.gz)/GYRO_LSB_PER_DPS;
  const float amag=sqrtf(ax*ax+ay*ay+az*az);
  const float cgx=gx-(dev.gyro_bias_valid?dev.gyro_bias_x:0.0f),
              cgy=gy-(dev.gyro_bias_valid?dev.gyro_bias_y:0.0f),
              cgz=gz-(dev.gyro_bias_valid?dev.gyro_bias_z:0.0f);
  const float accel_roll=atan2f(ay,az)*RAD_TO_DEG_F;
  const float accel_pitch=atan2f(-ax,sqrtf(ay*ay+az*az))*RAD_TO_DEG_F;

  float dt=dev.fusion_ms ? float(now-dev.fusion_ms)*0.001f : 0.02f;
  if (dt<0.001f) dt=0.001f;
  if (dt>0.250f) dt=0.250f;
  dev.fusion_ms=now;

  if (!dev.fusion_valid) {
    dev.roll_deg=accel_roll; dev.pitch_deg=accel_pitch; dev.fusion_valid=true;
  }
  else {
    dev.roll_deg += cgx*dt; dev.pitch_deg += cgy*dt;
    const bool accel_trust=fabsf(amag-1.0f)<0.12f;
    if (accel_trust) {
      const bool gyro_quiet=fabsf(cgx)<3.0f && fabsf(cgy)<3.0f && fabsf(cgz)<3.0f;
      const float tau_s=gyro_quiet?0.48f:3.5f;
      const float alpha=tau_s/(tau_s+dt);
      dev.roll_deg=alpha*dev.roll_deg+(1.0f-alpha)*accel_roll;
      dev.pitch_deg=alpha*dev.pitch_deg+(1.0f-alpha)*accel_pitch;
    }
  }

  if (!dev.motion_lp_valid) {
    dev.lp_ax=ax; dev.lp_ay=ay; dev.lp_az=az; dev.motion_lp_valid=true;
  }
  const float lp_k=_MIN(0.12f,_MAX(0.01f,dt*4.0f));
  dev.lp_ax+=(ax-dev.lp_ax)*lp_k; dev.lp_ay+=(ay-dev.lp_ay)*lp_k; dev.lp_az+=(az-dev.lp_az)*lp_k;
  const float dx=ax-dev.lp_ax, dy=ay-dev.lp_ay, dz=az-dev.lp_az;
  dev.vib_now_g=sqrtf(dx*dx+dy*dy+dz*dz);
  const float rms_k=_MIN(0.10f,_MAX(0.005f,dt*2.5f));
  dev.vib_rms2+=(dev.vib_now_g*dev.vib_now_g-dev.vib_rms2)*rms_k;
  dev.vib_peak_g*=_MAX(0.0f,1.0f-dt*0.50f);
  if (dev.vib_now_g>dev.vib_peak_g) dev.vib_peak_g=dev.vib_now_g;

  const bool quiet_for_bias=fabsf(amag-1.0f)<0.06f && dev.vib_now_g<0.035f
                         && fabsf(gx)<4.0f && fabsf(gy)<4.0f && fabsf(gz)<4.0f;
  if (!dev.gyro_bias_valid) {
    if (quiet_for_bias) {
      dev.gyro_bias_sum_x+=gx; dev.gyro_bias_sum_y+=gy; dev.gyro_bias_sum_z+=gz;
      if (++dev.gyro_bias_samples>=12) {
        const float inv=1.0f/float(dev.gyro_bias_samples);
        dev.gyro_bias_x=dev.gyro_bias_sum_x*inv; dev.gyro_bias_y=dev.gyro_bias_sum_y*inv; dev.gyro_bias_z=dev.gyro_bias_sum_z*inv;
        dev.gyro_bias_valid=true;
      }
    }
    else if (fabsf(amag-1.0f)>0.12f || dev.vib_now_g>0.08f) {
      dev.gyro_bias_samples=0;
      dev.gyro_bias_sum_x=dev.gyro_bias_sum_y=dev.gyro_bias_sum_z=0.0f;
    }
  }
  else if (quiet_for_bias) {
    const float bias_k=_MIN(0.01f,_MAX(0.001f,dt*0.10f));
    dev.gyro_bias_x+=(gx-dev.gyro_bias_x)*bias_k;
    dev.gyro_bias_y+=(gy-dev.gyro_bias_y)*bias_k;
    dev.gyro_bias_z+=(gz-dev.gyro_bias_z)*bias_k;
  }

  const float sgx=gx-(dev.gyro_bias_valid?dev.gyro_bias_x:0.0f),
              sgy=gy-(dev.gyro_bias_valid?dev.gyro_bias_y:0.0f),
              sgz=gz-(dev.gyro_bias_valid?dev.gyro_bias_z:0.0f);
  const bool stable_now=fabsf(amag-1.0f)<0.08f && fabsf(sgx)<2.0f && fabsf(sgy)<2.0f && fabsf(sgz)<2.0f && dev.vib_now_g<0.06f;
  if (stable_now) {
    if (!dev.stable_since) {
      dev.stable_since=now; dev.stable_roll_deg=dev.roll_deg; dev.stable_pitch_deg=dev.pitch_deg;
    }
    else {
      const float zero_k=_MIN(0.20f,_MAX(0.02f,dt*3.0f));
      dev.stable_roll_deg+=(dev.roll_deg-dev.stable_roll_deg)*zero_k;
      dev.stable_pitch_deg+=(dev.pitch_deg-dev.stable_pitch_deg)*zero_k;
    }
  }
  else dev.stable_since=0;
  dev.stable=dev.stable_since && ELAPSED(now,dev.stable_since+500UL);

  if (!dev.boot_temp_valid) {
    const float raw_temp=kp3s_mpu_raw_temperature_c(dev);
    if (WITHIN(raw_temp,-50.0f,110.0f)) {
      dev.temp_baseline_sum+=raw_temp;
      if (++dev.temp_baseline_samples>=KP3S_MPU_TEMP_BASELINE_SAMPLES) {
        dev.boot_temp_raw_c=dev.temp_baseline_sum/float(dev.temp_baseline_samples);
        dev.boot_temp_valid=true;
      }
    }
  }

  const KP3SMPU6050Role role=kp3s_mpu6050_role_for_address(dev.address);
  if (role != KP3SMPU6050Role::UNUSED && !dev.boot_level_ready && !kp3s_mpu_job_active(now) && !kp3s_res_capture) {
    const bool sample_ok=fabsf(amag-1.0f)<0.12f && fabsf(sgx)<4.0f && fabsf(sgy)<4.0f && fabsf(sgz)<4.0f && dev.vib_now_g<0.10f;
    const bool hard_motion=fabsf(amag-1.0f)>0.25f || fabsf(sgx)>10.0f || fabsf(sgy)>10.0f || fabsf(sgz)>10.0f || dev.vib_now_g>0.20f;
    if (sample_ok) {
      if (dev.boot_samples && ELAPSED(now,dev.boot_last_good_ms+250UL)) {
        dev.boot_samples=0; dev.boot_roll_sum=dev.boot_pitch_sum=0.0f;
      }
      dev.boot_last_good_ms=now;
      const float roll=dev.roll_deg-(kp3s_role_zero_valid(role)?kp3s_role_zero_roll(role):0.0f);
      const float pitch=dev.pitch_deg-(kp3s_role_zero_valid(role)?kp3s_role_zero_pitch(role):0.0f);
      dev.boot_roll_sum+=roll; dev.boot_pitch_sum+=pitch;
      if (++dev.boot_samples>=KP3S_MPU_BOOT_SAMPLES_REQUIRED) {
        const float inv=1.0f/float(dev.boot_samples);
        dev.boot_roll_deg=dev.boot_roll_sum*inv; dev.boot_pitch_deg=dev.boot_pitch_sum*inv;
        dev.boot_level_ok=fabsf(dev.boot_roll_deg)<=0.5f && fabsf(dev.boot_pitch_deg)<=0.5f;
        dev.boot_level_ready=true; dev.boot_notice_until=now+60000UL;
      }
    }
    else if (hard_motion && dev.boot_samples) {
      dev.boot_samples=0; dev.boot_roll_sum=dev.boot_pitch_sum=0.0f; dev.boot_last_good_ms=0;
    }
  }
}

static bool kp3s_mpu_parse_sample(KP3SMPU6050DeviceState &dev, const uint8_t * const b, const millis_t now) {
  dev.data.ax=int16_t((uint16_t(b[0])<<8)|b[1]);
  dev.data.ay=int16_t((uint16_t(b[2])<<8)|b[3]);
  dev.data.az=int16_t((uint16_t(b[4])<<8)|b[5]);
  dev.data.temperature=int16_t((uint16_t(b[6])<<8)|b[7]);
  dev.data.gx=int16_t((uint16_t(b[8])<<8)|b[9]);
  dev.data.gy=int16_t((uint16_t(b[10])<<8)|b[11]);
  dev.data.gz=int16_t((uint16_t(b[12])<<8)|b[13]);
  const bool accel_signal=ABS(dev.data.ax)>32 || ABS(dev.data.ay)>32 || ABS(dev.data.az)>32;
  const bool all_minus_one=dev.data.ax==-1 && dev.data.ay==-1 && dev.data.az==-1 && dev.data.temperature==-1 && dev.data.gx==-1 && dev.data.gy==-1 && dev.data.gz==-1;
  const bool all_zero=dev.data.ax==0 && dev.data.ay==0 && dev.data.az==0 && dev.data.temperature==0 && dev.data.gx==0 && dev.data.gy==0 && dev.data.gz==0;
  const float ax=float(dev.data.ax)/16384.0f, ay=float(dev.data.ay)/16384.0f, az=float(dev.data.az)/16384.0f;
  const float amag=sqrtf(ax*ax+ay*ay+az*az);
  dev.data.updated_ms=now;
  dev.data.valid=accel_signal && !all_minus_one && !all_zero && amag>0.05f && amag<3.70f;
  if (!dev.data.valid) return false;

  if (kp3s_res_capture && dev.address==kp3s_res_source_addr && kp3s_res_count<KP3S_RESONANCE_CAPTURE_MAX) {
    if (!kp3s_res_count) kp3s_res_first_ms=now;
    kp3s_res_ax[kp3s_res_count]=dev.data.ax;
    kp3s_res_ay[kp3s_res_count]=dev.data.ay;
    kp3s_res_az[kp3s_res_count]=dev.data.az;
    kp3s_res_last_ms=now;
    ++kp3s_res_count;
    if (kp3s_res_count>=KP3S_RESONANCE_CAPTURE_MAX) kp3s_res_capture=false;
  }
  kp3s_mpu_update_derived(dev,now);
  return true;
}

static bool kp3s_mpu_read_sample_now(KP3SMPU6050DeviceState &dev, const millis_t now, const bool robust=true) {
  uint8_t b[14];
  if (!kp3s_mpu_read_regs(dev,0x3B,b,uint8_t(sizeof(b)),robust)) { dev.data.valid=false; return false; }
  return kp3s_mpu_parse_sample(dev,b,now);
}

static bool kp3s_mpu_configure_and_verify(KP3SMPU6050DeviceState &dev) {
  kp3s_mpu_reset_device_derived(dev,true);
  if (!kp3s_mpu_write_reg(dev,0x6B,0x80,true)) return false;
  kp3s_mpu_delay_ms(100);
  if (!kp3s_mpu_write_reg(dev,0x6B,0x01,true)) return false;
  kp3s_mpu_delay_ms(20);
  if (!kp3s_mpu_write_reg(dev,0x6C,0x00,true)
      || !kp3s_mpu_write_reg(dev,0x19,0x04,true)
      || !kp3s_mpu_write_reg(dev,0x1A,0x03,true)
      || !kp3s_mpu_write_reg(dev,0x1B,0x00,true)
      || !kp3s_mpu_write_reg(dev,0x1C,0x00,true)) return false;
  kp3s_mpu_delay_ms(10);
  uint8_t cfg[4]={0xFF,0xFF,0xFF,0xFF}, pwr[2]={0xFF,0xFF};
  if (!kp3s_mpu_read_regs(dev,0x19,cfg,4,true) || !kp3s_mpu_read_regs(dev,0x6B,pwr,2,true)) return false;
  if (cfg[0]!=0x04 || (cfg[1]&0x07)!=0x03 || (cfg[2]&0x18) || (cfg[3]&0x18)) return false;
  if ((pwr[0]&0x7F)!=0x01 || pwr[1]!=0x00) return false;
  return kp3s_mpu_read_sample_now(dev,millis(),true);
}

static bool kp3s_mpu_probe_device(KP3SMPU6050DeviceState &dev) {
  dev.who=0; dev.who_valid=false; dev.present=false; dev.faults=0;
  if (!kp3s_i2c_probe_ack(dev.address)) return false;
  kp3s_mpu_last_bus_addr=dev.address;
  uint8_t who=0;
  dev.who_valid=kp3s_mpu_read_regs(dev,0x75,&who,1,true);
  if (dev.who_valid) dev.who=who;
  const bool normal_identity=dev.who_valid && ((who&0x7E)==0x68);
  if (!normal_identity) {
    uint8_t pwr=0xFF, gyro_cfg=0xFF, accel_cfg=0xFF;
    if (!kp3s_mpu_read_regs(dev,0x6B,&pwr,1,true)
        || !kp3s_mpu_read_regs(dev,0x1B,&gyro_cfg,1,true)
        || !kp3s_mpu_read_regs(dev,0x1C,&accel_cfg,1,true)) return false;
    if (pwr==0xFF || (gyro_cfg&0x07) || (accel_cfg&0x07)) return false;
  }
  if (!kp3s_mpu_configure_and_verify(dev)) return false;
  dev.present=true; dev.faults=0; dev.next_retry=millis()+2000UL;
  return true;
}

static bool kp3s_mpu_detect_all_idle() {
  if (!kp3s_mpu6050_runtime_enabled || kp3s_mpu_background_blocked(millis())) return false;
  kp3s_mpu_last_bus_addr=0;
  kp3s_i2c_bus_recover();
  bool any=false;
  for (uint8_t i=0; i<2; ++i) any |= kp3s_mpu_probe_device(kp3s_mpu_devices[i]);
  return any;
}

static uint8_t kp3s_mpu_assigned_present_count() {
  uint8_t n=0;
  for (uint8_t i=0; i<2; ++i)
    if (kp3s_mpu_devices[i].present && kp3s_mpu6050_role_for_address(kp3s_mpu_devices[i].address)!=KP3SMPU6050Role::UNUSED) ++n;
  return n;
}

static KP3SMPU6050DeviceState* kp3s_mpu_next_pollable_device() {
  for (uint8_t tries=0; tries<2; ++tries) {
    KP3SMPU6050DeviceState &dev=kp3s_mpu_devices[kp3s_mpu_poll_index++ & 1U];
    if (dev.present && kp3s_mpu6050_role_for_address(dev.address)!=KP3SMPU6050Role::UNUSED) return &dev;
  }
  return nullptr;
}

void kp3s_mpu6050_init() {
  kp3s_mpu_devices[0].address=0x68;
  kp3s_mpu_devices[1].address=0x69;
  kp3s_mpu_devices[0].stop_before_read=kp3s_mpu_devices[1].stop_before_read=false;
  kp3s_mpu6050_sanitize_configuration();
  kp3s_mpu_reset_all_derived(true);
  kp3s_mpu_poll_index=0;
  if (!kp3s_mpu6050_runtime_enabled) {
    for (uint8_t i=0; i<2; ++i) { kp3s_mpu_devices[i].present=false; kp3s_mpu_devices[i].who_valid=false; }
    kp3s_i2c_release_bus();
    return;
  }
  kp3s_i2c_sda_release(); kp3s_i2c_scl_release(); DELAY_US(100);
  kp3s_mpu_detect_all_idle();
  const millis_t now=millis();
  kp3s_mpu_next_poll=now+KP3S_MPU6050_POLL_IDLE_MS;
  for (uint8_t i=0; i<2; ++i) kp3s_mpu_devices[i].next_retry=now+2000UL;
  #if ENABLED(KP3S_MPU6050_DEBUG)
    SERIAL_ECHOPGM("MPU6050 init: count="); SERIAL_PRINT(kp3s_mpu6050_detected_count());
    SERIAL_ECHOPGM(" 68="); if (kp3s_mpu_devices[0].present) SERIAL_ECHOPGM("OK"); else SERIAL_ECHOPGM("--");
    SERIAL_ECHOPGM(" 69="); if (kp3s_mpu_devices[1].present) SERIAL_ECHOLNPGM("OK"); else SERIAL_ECHOLNPGM("--");
  #endif
}

void kp3s_mpu6050_set_enabled(const bool enabled) {
  if (kp3s_mpu_background_blocked(millis())) return;
  kp3s_mpu6050_runtime_enabled=enabled;
  for (uint8_t i=0; i<2; ++i) {
    kp3s_mpu_devices[i].present=kp3s_mpu_devices[i].who_valid=false;
    kp3s_mpu_devices[i].faults=0;
  }
  kp3s_mpu_reset_all_derived(true);
  if (enabled) kp3s_mpu6050_init(); else kp3s_i2c_release_bus();
}

void kp3s_mpu6050_set_swap_lines(const bool swap_lines) {
  if (kp3s_mpu_background_blocked(millis())) return;
  kp3s_i2c_release_bus();
  kp3s_mpu6050_swap_lines=swap_lines;
  for (uint8_t i=0; i<2; ++i) { kp3s_mpu_devices[i].present=kp3s_mpu_devices[i].who_valid=false; kp3s_mpu_devices[i].faults=0; }
  kp3s_mpu_reset_all_derived(true);
  if (kp3s_mpu6050_runtime_enabled) kp3s_mpu6050_init(); else kp3s_i2c_release_bus();
}

bool kp3s_mpu6050_lines_swapped() { return kp3s_mpu6050_swap_lines; }

KP3SMPU6050BusStatus kp3s_mpu6050_test_bus() {
  kp3s_mpu_last_bus_addr=0;
  if (!kp3s_mpu6050_runtime_enabled) return KP3SMPU6050BusStatus::DISABLED;
  if (kp3s_mpu_background_blocked(millis())) return KP3SMPU6050BusStatus::BUSY;
  kp3s_i2c_bus_recover(); kp3s_i2c_sda_release(); kp3s_i2c_scl_release(); DELAY_US(20);
  if (!READ(kp3s_i2c_scl_pin())) return KP3SMPU6050BusStatus::SCL_STUCK_LOW;
  if (!READ(kp3s_i2c_sda_pin())) return KP3SMPU6050BusStatus::SDA_STUCK_LOW;
  if (kp3s_i2c_probe_ack(0x68)) { kp3s_mpu_last_bus_addr=0x68; return KP3SMPU6050BusStatus::OK; }
  if (kp3s_i2c_probe_ack(0x69)) { kp3s_mpu_last_bus_addr=0x69; return KP3SMPU6050BusStatus::OK; }
  return KP3SMPU6050BusStatus::NO_ACK;
}

bool kp3s_mpu6050_detect_now() {
  if (!kp3s_mpu6050_runtime_enabled || kp3s_mpu_background_blocked(millis())) return false;
  kp3s_mpu_reset_all_derived(false);
  const bool ok=kp3s_mpu_detect_all_idle();
  kp3s_mpu_next_poll=millis();
  return ok;
}

static void kp3s_mpu_restore_resonance_config_idle() {
  if (!kp3s_res_restore_pending || kp3s_mpu_background_blocked(millis())) return;
  KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_at(kp3s_res_restore_addr);
  if (!dev || !dev->present) {
    kp3s_res_restore_pending=false;
    kp3s_res_restore_addr=0;
    return;
  }
  if (kp3s_mpu_write_reg(*dev,0x1A,0x03,true)) {
    kp3s_mpu_delay_ms(5);
    kp3s_res_restore_pending=false;
    kp3s_res_restore_addr=0;
  }
}

void kp3s_mpu6050_task(const millis_t now) {
  if (!kp3s_mpu6050_runtime_enabled) return;

  if (kp3s_res_capture) {
    // Resonance capture is calibration-only. If a print/job starts from another
    // interface while this screen is open, abort before touching the I2C bus.
    if (kp3s_mpu_job_active(now)) { kp3s_res_capture=false; return; }
    if (!ELAPSED(now,kp3s_mpu_next_poll)) return;
    kp3s_mpu_next_poll=now+5UL;
    KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_at(kp3s_res_source_addr);
    if (!dev || !dev->present) { kp3s_res_capture=false; return; }
    if (kp3s_mpu_read_sample_now(*dev,now,false)) dev->faults=0;
    else if (++dev->faults>=8) kp3s_res_capture=false;
    return;
  }

  // Normal motion owns the main loop. V1 never runs background MPU software-I2C
  // while printing, paused, homing, jogging, or any other planner motion is queued.
  if (kp3s_mpu_background_blocked(now)) return;

  // A capture aborted by a newly-active print may leave the MPU in the
  // capture DLPF setting. Restore it only after the printer is idle again.
  kp3s_mpu_restore_resonance_config_idle();

  if (!ELAPSED(now,kp3s_mpu_next_poll)) return;
  kp3s_mpu_next_poll=now+KP3S_MPU6050_POLL_IDLE_MS;

  KP3SMPU6050DeviceState *dev=kp3s_mpu_next_pollable_device();
  if (dev) {
    const bool ok=kp3s_mpu_read_sample_now(*dev,now,true);
    if (ok) dev->faults=0;
    else if (++dev->faults>=3) {
      dev->present=false;
      kp3s_mpu_reset_device_derived(*dev,false);
      dev->next_retry=now+1500UL;
    }
  }

  // Missing assigned devices are retried only while idle.
  for (uint8_t i=0; i<2; ++i) {
    KP3SMPU6050DeviceState &candidate=kp3s_mpu_devices[i];
    if (!candidate.present
        && kp3s_mpu6050_role_for_address(candidate.address)!=KP3SMPU6050Role::UNUSED
        && ELAPSED(now,candidate.next_retry)) {
      candidate.next_retry=now+2000UL;
      kp3s_i2c_bus_recover();
      kp3s_mpu_probe_device(candidate);
      break;
    }
  }
}

bool kp3s_mpu6050_detected_at(const uint8_t address) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_at_const(address);
  return dev && dev->present;
}
bool kp3s_mpu6050_detected_role(const KP3SMPU6050Role role) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  return dev && dev->present;
}
uint8_t kp3s_mpu6050_detected_count() {
  return uint8_t(kp3s_mpu_devices[0].present)+uint8_t(kp3s_mpu_devices[1].present);
}
uint8_t kp3s_mpu6050_last_bus_address() { return kp3s_mpu_last_bus_addr; }
uint8_t kp3s_mpu6050_who_am_i_at(const uint8_t address) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_at_const(address); return dev?dev->who:0;
}
bool kp3s_mpu6050_who_valid_at(const uint8_t address) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_at_const(address); return dev&&dev->who_valid;
}

bool kp3s_mpu6050_level_raw_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  if (!dev || !kp3s_mpu_data_fresh(*dev) || !dev->fusion_valid) return false;
  roll_x_deg=dev->roll_deg; pitch_y_deg=dev->pitch_deg; return true;
}
bool kp3s_mpu6050_level_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg) {
  if (!kp3s_mpu6050_level_raw_for_role(role,roll_x_deg,pitch_y_deg)) return false;
  if (kp3s_role_zero_valid(role)) { roll_x_deg-=kp3s_role_zero_roll(role); pitch_y_deg-=kp3s_role_zero_pitch(role); }
  return true;
}
bool kp3s_mpu6050_motion_stable_for_role(const KP3SMPU6050Role role) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  return dev && kp3s_mpu_data_fresh(*dev) && dev->stable;
}
bool kp3s_mpu6050_level_zero_candidate_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg) {
  if (kp3s_mpu_background_blocked(millis())) return false;
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  if (!dev || !kp3s_mpu_data_fresh(*dev) || !dev->stable) return false;
  roll_x_deg=dev->stable_roll_deg; pitch_y_deg=dev->stable_pitch_deg; return true;
}
bool kp3s_mpu6050_set_level_zero_for_role(const KP3SMPU6050Role role) {
  float roll=0,pitch=0;
  if (!kp3s_mpu6050_level_zero_candidate_for_role(role,roll,pitch)) return false;
  if (role==KP3SMPU6050Role::BED) {
    kp3s_mpu6050_bed_level_zero_roll_deg=roll; kp3s_mpu6050_bed_level_zero_pitch_deg=pitch; kp3s_mpu6050_bed_level_zero_valid=true;
  }
  else if (role==KP3SMPU6050Role::TOOLHEAD) {
    kp3s_mpu6050_toolhead_level_zero_roll_deg=roll; kp3s_mpu6050_toolhead_level_zero_pitch_deg=pitch; kp3s_mpu6050_toolhead_level_zero_valid=true;
  }
  else return false;
  KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role(role);
  if (dev) { dev->boot_samples=0; dev->boot_roll_sum=dev->boot_pitch_sum=0.0f; dev->boot_level_ready=dev->boot_level_ok=false; dev->boot_notice_until=dev->boot_last_good_ms=0; }
  return true;
}
void kp3s_mpu6050_clear_level_zero_for_role(const KP3SMPU6050Role role) {
  kp3s_clear_role_calibration(role,false);
  KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role(role);
  if (dev) { dev->boot_samples=0; dev->boot_roll_sum=dev->boot_pitch_sum=0.0f; dev->boot_level_ready=dev->boot_level_ok=false; dev->boot_notice_until=dev->boot_last_good_ms=0; }
}
bool kp3s_mpu6050_startup_level_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg, bool &level_ok) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  if (!dev || !dev->boot_level_ready) return false;
  roll_x_deg=dev->boot_roll_deg; pitch_y_deg=dev->boot_pitch_deg; level_ok=dev->boot_level_ok; return true;
}
bool kp3s_mpu6050_startup_notice_for_role(const KP3SMPU6050Role role, float &roll_x_deg, float &pitch_y_deg, bool &level_ok) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  if (!dev || !kp3s_mpu6050_startup_level_for_role(role,roll_x_deg,pitch_y_deg,level_ok)) return false;
  return PENDING(millis(),dev->boot_notice_until);
}
uint8_t kp3s_mpu6050_startup_progress_pct_for_role(const KP3SMPU6050Role role) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  if (!dev) return 0;
  if (dev->boot_level_ready) return 100;
  return uint8_t(_MIN(99U,(uint16_t(dev->boot_samples)*100U)/KP3S_MPU_BOOT_SAMPLES_REQUIRED));
}
bool kp3s_mpu6050_temperature_raw_c_for_role(const KP3SMPU6050Role role, float &temperature_c) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  if (!dev || !kp3s_mpu_data_fresh(*dev)) return false;
  temperature_c=kp3s_mpu_raw_temperature_c(*dev); return true;
}
bool kp3s_mpu6050_temperature_c_for_role(const KP3SMPU6050Role role, float &temperature_c) {
  if (!kp3s_mpu6050_temperature_raw_c_for_role(role,temperature_c)) return false;
  temperature_c+=kp3s_role_temp_offset(role); return true;
}
bool kp3s_mpu6050_temperature_delta_c_for_role(const KP3SMPU6050Role role, float &delta_c) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  float raw=0;
  if (!dev || !dev->boot_temp_valid || !kp3s_mpu6050_temperature_raw_c_for_role(role,raw)) return false;
  delta_c=raw-dev->boot_temp_raw_c; return true;
}
bool kp3s_mpu6050_motion_for_role(const KP3SMPU6050Role role, float &rms_g, float &peak_g, float &instant_g) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  if (!dev || !kp3s_mpu_data_fresh(*dev) || !dev->motion_lp_valid) return false;
  rms_g=sqrtf(_MAX(0.0f,dev->vib_rms2)); peak_g=dev->vib_peak_g; instant_g=dev->vib_now_g; return true;
}
uint16_t kp3s_mpu6050_sample_rate_hz_for_role(const KP3SMPU6050Role role, const millis_t now) {
  if (kp3s_res_capture && kp3s_mpu6050_address_for_role(role)==kp3s_res_source_addr) return 200;
  if (kp3s_mpu_background_blocked(now) || !kp3s_mpu6050_detected_role(role)) return 0;
  const uint8_t n=_MAX(uint8_t(1),uint8_t(kp3s_mpu_assigned_present_count()));
  const millis_t period=KP3S_MPU6050_POLL_IDLE_MS*n;
  return period?uint16_t(1000UL/period):0;
}

static KP3SMPU6050Sample kp3s_mpu_invalid_sample={0,0,0,0,0,0,0,0,false};
const KP3SMPU6050Sample& kp3s_mpu6050_sample_for_role(const KP3SMPU6050Role role) {
  const KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_for_role_const(role);
  return dev?dev->data:kp3s_mpu_invalid_sample;
}

void kp3s_mpu6050_resonance_capture_start(const KP3SMPU6050Role role) {
  kp3s_res_count=0; kp3s_res_first_ms=kp3s_res_last_ms=0; kp3s_res_source_addr=0;
  if (kp3s_mpu_background_blocked(millis())) { kp3s_res_capture=false; return; }
  kp3s_res_source_addr=kp3s_mpu6050_address_for_role(role);
  KP3SMPU6050DeviceState * const dev=kp3s_mpu_device_at(kp3s_res_source_addr);
  kp3s_res_capture=dev && dev->present && kp3s_mpu_data_fresh(*dev);
  if (kp3s_res_capture) {
    if (!kp3s_mpu_write_reg(*dev,0x1A,0x02,true)) kp3s_res_capture=false;
    else {
      kp3s_res_restore_pending=true;
      kp3s_res_restore_addr=dev->address;
      kp3s_mpu_delay_ms(5);
    }
  }
  kp3s_mpu_next_poll=millis();
}
bool kp3s_mpu6050_resonance_capturing() { return kp3s_res_capture; }
uint16_t kp3s_mpu6050_resonance_samples() { return kp3s_res_count; }
KP3SMPU6050Role kp3s_mpu6050_resonance_role() { return kp3s_mpu6050_role_for_address(kp3s_res_source_addr); }

static float kp3s_res_goertzel_power(const int16_t * const data, const uint16_t n, const float mean, const float frequency_hz, const float sample_rate_hz) {
  const float omega=6.28318530718f*frequency_hz/sample_rate_hz;
  const float coeff=2.0f*cosf(omega);
  float q0=0.0f,q1=0.0f,q2=0.0f;
  const float mid=float(n-1)*0.5f;
  for (uint16_t i=0; i<n; ++i) {
    const float window=mid>0.0f?_MAX(0.0f,1.0f-fabsf((float(i)-mid)/mid)):1.0f;
    q0=(float(data[i])-mean)*window+coeff*q1-q2;
    q2=q1; q1=q0;
  }
  const float power=q1*q1+q2*q2-coeff*q1*q2;
  return power>0.0f?power:0.0f;
}

bool kp3s_mpu6050_resonance_capture_analyze(float &frequency_hz, uint8_t &confidence_pct) {
  kp3s_res_capture=false;
  frequency_hz=0.0f; confidence_pct=0;
  if (kp3s_mpu_background_blocked(millis())) return false;
  kp3s_mpu_restore_resonance_config_idle();
  const uint16_t n=kp3s_res_count;
  if (n<120 || kp3s_res_last_ms<=kp3s_res_first_ms) return false;
  const float sample_rate=float(n-1)*1000.0f/float(kp3s_res_last_ms-kp3s_res_first_ms);
  if (sample_rate<140.0f || sample_rate>240.0f) return false;

  float mean_x=0,mean_y=0,mean_z=0;
  for (uint16_t i=0;i<n;++i) { mean_x+=kp3s_res_ax[i]; mean_y+=kp3s_res_ay[i]; mean_z+=kp3s_res_az[i]; }
  const float inv_n=1.0f/float(n); mean_x*=inv_n; mean_y*=inv_n; mean_z*=inv_n;
  float best_power=0.0f,best_freq=0.0f;
  for (uint8_t f=20;f<=80;++f) {
    const float power=kp3s_res_goertzel_power(kp3s_res_ax,n,mean_x,float(f),sample_rate)
                     +kp3s_res_goertzel_power(kp3s_res_ay,n,mean_y,float(f),sample_rate)
                     +kp3s_res_goertzel_power(kp3s_res_az,n,mean_z,float(f),sample_rate);
    if (power>best_power) { best_power=power; best_freq=float(f); }
  }
  if (best_power<=0.0f) return false;
  float refined_power=best_power,refined_freq=best_freq;
  for (int8_t q=-3;q<=3;++q) {
    const float f=best_freq+float(q)*0.25f;
    if (f<20.0f || f>80.0f) continue;
    const float power=kp3s_res_goertzel_power(kp3s_res_ax,n,mean_x,f,sample_rate)
                     +kp3s_res_goertzel_power(kp3s_res_ay,n,mean_y,f,sample_rate)
                     +kp3s_res_goertzel_power(kp3s_res_az,n,mean_z,f,sample_rate);
    if (power>refined_power) { refined_power=power; refined_freq=f; }
  }
  float noise_sum=0.0f; uint8_t noise_bins=0;
  for (uint8_t f=20;f<=80;++f) {
    if (fabsf(float(f)-refined_freq)<=2.0f) continue;
    noise_sum+=kp3s_res_goertzel_power(kp3s_res_ax,n,mean_x,float(f),sample_rate)
              +kp3s_res_goertzel_power(kp3s_res_ay,n,mean_y,float(f),sample_rate)
              +kp3s_res_goertzel_power(kp3s_res_az,n,mean_z,float(f),sample_rate);
    ++noise_bins;
  }
  const float noise=_MAX(1.0f,noise_sum/float(_MAX(1,int(noise_bins))));
  const float snr=refined_power/noise;
  confidence_pct=uint8_t(_MIN(100.0f,_MAX(0.0f,(snr-1.0f)*10.0f)));
  frequency_hz=refined_freq;
  return confidence_pct>=25 && WITHIN(frequency_hz,20.0f,80.0f);
}

#endif
''',
        encoding="utf-8",
    )

    print("[OK] Create isolated dual-MPU6050 runtime with bed/toolhead roles and idle-only acquisition")

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
        '#define EEPROM_VERSION "V01"',
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
    uint8_t kp3s_mpu6050_role_68;
    uint8_t kp3s_mpu6050_role_69;
    float kp3s_mpu6050_toolhead_temp_offset_c;
    float kp3s_mpu6050_toolhead_level_zero_roll_deg;
    float kp3s_mpu6050_toolhead_level_zero_pitch_deg;
    bool kp3s_mpu6050_toolhead_level_zero_valid;
    float kp3s_mpu6050_bed_temp_offset_c;
    float kp3s_mpu6050_bed_level_zero_roll_deg;
    float kp3s_mpu6050_bed_level_zero_pitch_deg;
    bool kp3s_mpu6050_bed_level_zero_valid;
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
      _FIELD_TEST(kp3s_mpu6050_role_68);
      EEPROM_WRITE(kp3s_mpu6050_role_68);
      _FIELD_TEST(kp3s_mpu6050_role_69);
      EEPROM_WRITE(kp3s_mpu6050_role_69);
      _FIELD_TEST(kp3s_mpu6050_toolhead_temp_offset_c);
      EEPROM_WRITE(kp3s_mpu6050_toolhead_temp_offset_c);
      _FIELD_TEST(kp3s_mpu6050_toolhead_level_zero_roll_deg);
      EEPROM_WRITE(kp3s_mpu6050_toolhead_level_zero_roll_deg);
      _FIELD_TEST(kp3s_mpu6050_toolhead_level_zero_pitch_deg);
      EEPROM_WRITE(kp3s_mpu6050_toolhead_level_zero_pitch_deg);
      _FIELD_TEST(kp3s_mpu6050_toolhead_level_zero_valid);
      EEPROM_WRITE(kp3s_mpu6050_toolhead_level_zero_valid);
      _FIELD_TEST(kp3s_mpu6050_bed_temp_offset_c);
      EEPROM_WRITE(kp3s_mpu6050_bed_temp_offset_c);
      _FIELD_TEST(kp3s_mpu6050_bed_level_zero_roll_deg);
      EEPROM_WRITE(kp3s_mpu6050_bed_level_zero_roll_deg);
      _FIELD_TEST(kp3s_mpu6050_bed_level_zero_pitch_deg);
      EEPROM_WRITE(kp3s_mpu6050_bed_level_zero_pitch_deg);
      _FIELD_TEST(kp3s_mpu6050_bed_level_zero_valid);
      EEPROM_WRITE(kp3s_mpu6050_bed_level_zero_valid);
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
        bool stored_mpu6050_enabled, stored_mpu6050_swap_lines;
        bool stored_level_zero_valid, stored_bed_level_zero_valid;
        uint8_t stored_role_68, stored_role_69;
        float stored_temp_offset_c, stored_zero_roll, stored_zero_pitch;
        float stored_bed_temp_offset_c, stored_bed_zero_roll, stored_bed_zero_pitch;
        _FIELD_TEST(kp3s_mpu6050_enabled);
        EEPROM_READ(stored_mpu6050_enabled);
        _FIELD_TEST(kp3s_mpu6050_swap_lines);
        EEPROM_READ(stored_mpu6050_swap_lines);
        _FIELD_TEST(kp3s_mpu6050_role_68);
        EEPROM_READ(stored_role_68);
        _FIELD_TEST(kp3s_mpu6050_role_69);
        EEPROM_READ(stored_role_69);
        _FIELD_TEST(kp3s_mpu6050_toolhead_temp_offset_c);
        EEPROM_READ(stored_temp_offset_c);
        _FIELD_TEST(kp3s_mpu6050_toolhead_level_zero_roll_deg);
        EEPROM_READ(stored_zero_roll);
        _FIELD_TEST(kp3s_mpu6050_toolhead_level_zero_pitch_deg);
        EEPROM_READ(stored_zero_pitch);
        _FIELD_TEST(kp3s_mpu6050_toolhead_level_zero_valid);
        EEPROM_READ(stored_level_zero_valid);
        _FIELD_TEST(kp3s_mpu6050_bed_temp_offset_c);
        EEPROM_READ(stored_bed_temp_offset_c);
        _FIELD_TEST(kp3s_mpu6050_bed_level_zero_roll_deg);
        EEPROM_READ(stored_bed_zero_roll);
        _FIELD_TEST(kp3s_mpu6050_bed_level_zero_pitch_deg);
        EEPROM_READ(stored_bed_zero_pitch);
        _FIELD_TEST(kp3s_mpu6050_bed_level_zero_valid);
        EEPROM_READ(stored_bed_level_zero_valid);
        if (!validating) {
          kp3s_mpu6050_runtime_enabled = stored_mpu6050_enabled;
          kp3s_mpu6050_swap_lines = stored_mpu6050_swap_lines;
          kp3s_mpu6050_role_68 = stored_role_68;
          kp3s_mpu6050_role_69 = stored_role_69;
          kp3s_mpu6050_toolhead_temp_offset_c = stored_temp_offset_c;
          kp3s_mpu6050_toolhead_level_zero_roll_deg = stored_zero_roll;
          kp3s_mpu6050_toolhead_level_zero_pitch_deg = stored_zero_pitch;
          kp3s_mpu6050_toolhead_level_zero_valid = stored_level_zero_valid;
          kp3s_mpu6050_bed_temp_offset_c = stored_bed_temp_offset_c;
          kp3s_mpu6050_bed_level_zero_roll_deg = stored_bed_zero_roll;
          kp3s_mpu6050_bed_level_zero_pitch_deg = stored_bed_zero_pitch;
          kp3s_mpu6050_bed_level_zero_valid = stored_bed_level_zero_valid;
          kp3s_mpu6050_sanitize_configuration();
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
        '''  //\n  // KP3S Marlin Firmware V1 runtime hardware/UI defaults\n  //\n  #if ENABLED(KP3S_RUNTIME_DISPLAY)\n    kp3s_display_flipped = false;\n  #endif\n  #if ENABLED(KP3S_RUNTIME_BLTOUCH)\n    kp3s_bltouch_runtime_enabled = false;\n  #endif\n  #if ENABLED(KP3S_MPU6050)\n    kp3s_mpu6050_runtime_enabled = true;\n    kp3s_mpu6050_swap_lines = false;\n    kp3s_mpu6050_role_68 = uint8_t(KP3SMPU6050Role::UNUSED);\n    kp3s_mpu6050_role_69 = uint8_t(KP3SMPU6050Role::UNUSED);\n    kp3s_mpu6050_toolhead_temp_offset_c = 0.0f;\n    kp3s_mpu6050_toolhead_level_zero_roll_deg = 0.0f;\n    kp3s_mpu6050_toolhead_level_zero_pitch_deg = 0.0f;\n    kp3s_mpu6050_toolhead_level_zero_valid = false;\n    kp3s_mpu6050_bed_temp_offset_c = 0.0f;\n    kp3s_mpu6050_bed_level_zero_roll_deg = 0.0f;\n    kp3s_mpu6050_bed_level_zero_pitch_deg = 0.0f;\n    kp3s_mpu6050_bed_level_zero_valid = false;\n  #endif\n\n  //\n  // LCD Contrast\n  //\n  TERN_(HAS_LCD_CONTRAST, ui.contrast = LCD_CONTRAST_DEFAULT);\n''',
        "Reset KP3S runtime options to safe defaults",
    )
    print("[OK] Persist display rotation, BLTouch state, dual-MPU roles and independent calibrations in EEPROM")

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
    # V1 menu organization: extend Marlin's native categories instead of
    # creating a parallel KP3S menu tree. Runout, Retract, Recovery, EEPROM
    # and Advanced Settings keep their native locations; screen controls are
    # consolidated into one dedicated Display submenu.
    replace_once(
        menu_config,
        '  #if HAS_LCD_BRIGHTNESS\n    EDIT_ITEM_FAST(uint8, MSG_BRIGHTNESS, &ui.brightness, LCD_BRIGHTNESS_MIN, LCD_BRIGHTNESS_MAX, ui.refresh_brightness, true);\n  #endif\n  #if HAS_LCD_CONTRAST && LCD_CONTRAST_MIN < LCD_CONTRAST_MAX\n    EDIT_ITEM_FAST(uint8, MSG_CONTRAST, &ui.contrast, LCD_CONTRAST_MIN, LCD_CONTRAST_MAX, ui.refresh_contrast, true);\n  #endif\n',
        '  SUBMENU_F(kp3s_tr(F("Display"),F("Tela"),F("Pantalla"),F("Affichage"),F("Anzeige")), menu_kp3s_display_settings);\n',
        'Replace native display controls with one clean Display submenu',
    )

    replace_once(
        menu_config,
        '  #if HAS_FILAMENT_SENSOR\n    EDIT_ITEM(bool, MSG_RUNOUT_SENSOR, &runout.enabled, runout.reset);\n  #endif\n',
        '  #if HAS_FILAMENT_SENSOR\n    EDIT_ITEM(bool, MSG_RUNOUT_SENSOR, &runout.enabled, runout.reset);\n  #endif\n\n  #if ENABLED(KP3S_MPU6050)\n    SUBMENU_F(kp3s_tr(F("MPU6050 / IMU"),F("MPU6050 / IMU"),F("MPU6050 / IMU"),F("MPU6050 / IMU"),F("MPU6050 / IMU")), menu_kp3s_mpu6050_settings);\n  #endif\n',
        'Place V1 IMU beside native sensor controls',
    )

    replace_once(
        menu_config,
        '  #if ENABLED(EEPROM_SETTINGS)\n    ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);\n    if (!busy) ACTION_ITEM(MSG_LOAD_EEPROM, ui.load_settings);\n  #endif\n\n  if (!busy) ACTION_ITEM(MSG_RESTORE_DEFAULTS, ui.reset_settings);\n',
        '  #if ENABLED(EEPROM_SETTINGS)\n    if (!busy) {\n      ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);\n      ACTION_ITEM(MSG_LOAD_EEPROM, ui.load_settings);\n    }\n  #endif\n\n  if (!busy)\n    CONFIRM_ITEM(MSG_RESTORE_DEFAULTS,\n      MSG_BUTTON_RESET, MSG_BUTTON_CANCEL,\n      []{ ui.reset_settings(); ui.goto_previous_screen(); }, nullptr,\n      GET_TEXT_F(MSG_RESTORE_DEFAULTS), (const char *)nullptr, F("?")\n    );\n',
        'Keep EEPROM actions native, lock them while busy, confirm reset, and return cleanly',
    )

    replace_once(
        menu_config,
        'void menu_configuration() {\n  const bool busy = printer_busy();\n',
        'void menu_configuration() {\n  const bool busy = printer_busy()\n    #if ENABLED(KP3S_SMART_UI)\n      || kp3s_serial_printing() || kp3s_serial_print_paused()\n    #endif\n  ;\n',
        'Make native Configuration busy-state aware of serial print jobs',
    )

    replace_once(
        menu_config,
        'void menu_configuration() {\n',
        """static bool kp3s_runtime_machine_busy() {
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

void menu_kp3s_display_settings() {
  START_MENU();
  BACK_ITEM(MSG_CONFIGURATION);

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
  #if ENABLED(KP3S_RUNTIME_DISPLAY)
    if (!kp3s_runtime_machine_busy())
      EDIT_ITEM_F(bool, kp3s_tr(F("Rotate LCD 180"),F("Girar LCD 180"),F("Girar LCD 180"),F("LCD à 180°"),F("LCD 180 drehen")), &kp3s_display_flipped, kp3s_display_rotation_changed);
  #endif
  #if HAS_MULTI_LANGUAGE
    SUBMENU_F(kp3s_tr(F("Language"),F("Idioma"),F("Idioma"),F("Langue"),F("Sprache")), menu_language);
  #endif

  END_MENU();
}

#if ENABLED(KP3S_MPU6050)
  static void kp3s_mpu6050_changed() {
    kp3s_mpu6050_set_enabled(kp3s_mpu6050_runtime_enabled);
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
  }

  static void kp3s_mpu6050_wiring_changed() {
    kp3s_mpu6050_set_swap_lines(kp3s_mpu6050_swap_lines);
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
  }

  static void kp3s_mpu6050_calibration_changed() {
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
  }

  static constexpr uint8_t KP3S_MPU_UI_LINE_CAP = 24;
  static KP3SMPU6050Role kp3s_mpu_ui_role = KP3SMPU6050Role::TOOLHEAD;
  static uint8_t kp3s_mpu_role_edit_addr = 0x68;
  static bool kp3s_mpu_zero_saved = false, kp3s_mpu_zero_attempted = false;

  static FSTR_P kp3s_mpu_role_title(const KP3SMPU6050Role role) {
    return role == KP3SMPU6050Role::BED
      ? kp3s_tr(F("BED IMU"),F("IMU DA MESA"),F("IMU DE CAMA"),F("IMU PLATEAU"),F("BETT-IMU"))
      : kp3s_tr(F("TOOLHEAD IMU"),F("IMU CABEÇOTE"),F("IMU CABEZAL"),F("IMU TÊTE OUTIL"),F("DRUCKKOPF-IMU"));
  }

  static const char *kp3s_mpu_role_tag(const KP3SMPU6050Role role) {
    #if HAS_MULTI_LANGUAGE
      switch (ui.language) {
        case 1:
          switch (role) { case KP3SMPU6050Role::BED: return "MESA"; case KP3SMPU6050Role::TOOLHEAD: return "CAB"; default: return "DESL"; }
        case 2:
          switch (role) { case KP3SMPU6050Role::BED: return "CAMA"; case KP3SMPU6050Role::TOOLHEAD: return "CAB"; default: return "APAG"; }
        case 3:
          switch (role) { case KP3SMPU6050Role::BED: return "PLAT"; case KP3SMPU6050Role::TOOLHEAD: return "TETE"; default: return "ARRET"; }
        case 4:
          switch (role) { case KP3SMPU6050Role::BED: return "BETT"; case KP3SMPU6050Role::TOOLHEAD: return "KOPF"; default: return "AUS"; }
      }
    #endif
    switch (role) {
      case KP3SMPU6050Role::BED: return "BED";
      case KP3SMPU6050Role::TOOLHEAD: return "HEAD";
      default: return "OFF";
    }
  }

  static float *kp3s_mpu_role_temp_offset_ptr() {
    return kp3s_mpu_ui_role == KP3SMPU6050Role::BED ? &kp3s_mpu6050_bed_temp_offset_c : &kp3s_mpu6050_toolhead_temp_offset_c;
  }

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

  static void screen_kp3s_mpu_zero_calibration() {
    if (kp3s_runtime_machine_busy()) return ui.goto_previous_screen();
    float raw_roll=0, raw_pitch=0;
    char xline[KP3S_MPU_UI_LINE_CAP], yline[KP3S_MPU_UI_LINE_CAP];
    const bool raw_ok = kp3s_mpu6050_level_raw_for_role(kp3s_mpu_ui_role, raw_roll, raw_pitch);
    const bool stable = kp3s_mpu6050_motion_stable_for_role(kp3s_mpu_ui_role);
    if (stable) kp3s_mpu6050_level_zero_candidate_for_role(kp3s_mpu_ui_role, raw_roll, raw_pitch);

    if (ui.use_click()) {
      if (kp3s_mpu_zero_saved) {
        kp3s_mpu_zero_saved = kp3s_mpu_zero_attempted = false;
        return ui.goto_previous_screen();
      }
      kp3s_mpu_zero_attempted = true;
      if (raw_ok && stable && kp3s_mpu6050_set_level_zero_for_role(kp3s_mpu_ui_role)) {
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
    STATIC_ITEM_F(kp3s_mpu_role_title(kp3s_mpu_ui_role), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(xline, SS_CENTER);
    STATIC_ITEM_C(yline, SS_CENTER);
    if (kp3s_mpu_zero_saved)
      STATIC_ITEM_F(kp3s_tr(F("SAVED - OK"),F("SALVO - OK"),F("GUARDADO - OK"),F("SAUVÉ - OK"),F("GESPEICHERT OK")), SS_CENTER);
    else if (!raw_ok)
      STATIC_ITEM_F(kp3s_tr(F("NO MPU DATA"),F("SEM DADOS MPU"),F("SIN DATOS MPU"),F("PAS DE DONNÉES"),F("KEINE MPU-DAT.")), SS_CENTER);
    else if (!stable)
      STATIC_ITEM_F(kp3s_tr(F("KEEP STILL"),F("NÃO MOVA"),F("NO SE MUEVA"),F("NE BOUGEZ PAS"),F("NICHT BEWEGEN")), SS_CENTER);
    else
      STATIC_ITEM_F(kp3s_tr(F("OK = SAVE ZERO"),F("OK=SALVAR ZERO"),F("OK=FIJAR CERO"),F("OK=SAUVER ZÉRO"),F("OK=0 SPEICH.")), SS_CENTER);
    END_SCREEN();
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void kp3s_open_mpu_zero_calibration() {
    if (kp3s_runtime_machine_busy()) return;
    kp3s_mpu_zero_saved = kp3s_mpu_zero_attempted = false;
    ui.push_current_screen();
    ui.goto_screen(screen_kp3s_mpu_zero_calibration);
  }

  static void kp3s_run_mpu_clear_zero() {
    if (kp3s_runtime_machine_busy()) return;
    kp3s_mpu6050_clear_level_zero_for_role(kp3s_mpu_ui_role);
    kp3s_mpu6050_calibration_changed();
    ui.completion_feedback();
    ui.goto_previous_screen();
  }

  static KP3SMPU6050BusStatus kp3s_mpu_bus_test_result = KP3SMPU6050BusStatus::DISABLED;
  static bool kp3s_mpu_detect_test_result = false;

  static void screen_kp3s_mpu_bus_test() {
    if (ui.use_click()) return ui.goto_previous_screen();
    char addr[KP3S_MPU_UI_LINE_CAP];
    const uint8_t a = kp3s_mpu6050_last_bus_address();
    if (a) snprintf_P(addr, sizeof(addr), PSTR("I2C: 0x%02X"), unsigned(a));
    else strcpy_P(addr, PSTR("I2C: --"));

    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("I2C CHECK"),F("TESTE I2C"),F("PRUEBA I2C"),F("TEST I2C"),F("I2C-TEST")), SS_CENTER | SS_INVERT);
    switch (kp3s_mpu_bus_test_result) {
      case KP3SMPU6050BusStatus::OK: STATIC_ITEM_F(F("I2C OK"), SS_CENTER); break;
      case KP3SMPU6050BusStatus::BUSY: STATIC_ITEM_F(kp3s_tr(F("PRINTER BUSY"),F("IMPR. OCUPADA"),F("IMPRES. OCUP."),F("IMPRIM. OCCUP."),F("DRUCKER BELEGT")), SS_CENTER); break;
      case KP3SMPU6050BusStatus::DISABLED: STATIC_ITEM_F(kp3s_tr(F("MPU DISABLED"),F("MPU DESATIVADO"),F("MPU DESACTIV."),F("MPU DÉSACTIVÉ"),F("MPU DEAKTIV.")), SS_CENTER); break;
      case KP3SMPU6050BusStatus::SDA_STUCK_LOW: STATIC_ITEM_F(kp3s_tr(F("SDA STUCK"),F("SDA TRAVADA"),F("SDA ATASC."),F("SDA BLOQUÉE"),F("SDA BLOCKIERT")), SS_CENTER); break;
      case KP3SMPU6050BusStatus::SCL_STUCK_LOW: STATIC_ITEM_F(kp3s_tr(F("SCL STUCK"),F("SCL TRAVADO"),F("SCL ATASC."),F("SCL BLOQUÉE"),F("SCL BLOCKIERT")), SS_CENTER); break;
      default: STATIC_ITEM_F(kp3s_tr(F("NO I2C ACK"),F("SEM ACK I2C"),F("SIN ACK I2C"),F("SANS ACK I2C"),F("KEIN I2C-ACK")), SS_CENTER); break;
    }
    STATIC_ITEM_C(addr, SS_CENTER);
    STATIC_ITEM_F(kp3s_tr(F("OK = BACK"),F("OK = VOLTAR"),F("OK = VOLVER"),F("OK = RETOUR"),F("OK = ZURÜCK")), SS_CENTER);
    END_SCREEN();
  }

  static void kp3s_run_mpu_bus_test() {
    kp3s_mpu_bus_test_result = kp3s_mpu6050_test_bus();
    ui.push_current_screen();
    ui.goto_screen(screen_kp3s_mpu_bus_test);
  }

  static void screen_kp3s_mpu_detect_test() {
    if (ui.use_click()) return ui.goto_previous_screen();
    char line68[KP3S_MPU_UI_LINE_CAP], line69[KP3S_MPU_UI_LINE_CAP], countline[KP3S_MPU_UI_LINE_CAP];
    snprintf_P(line68, sizeof(line68), PSTR("68:%s %s"), kp3s_mpu6050_detected_at(0x68) ? "OK" : "--", kp3s_mpu_role_tag(kp3s_mpu6050_role_for_address(0x68)));
    snprintf_P(line69, sizeof(line69), PSTR("69:%s %s"), kp3s_mpu6050_detected_at(0x69) ? "OK" : "--", kp3s_mpu_role_tag(kp3s_mpu6050_role_for_address(0x69)));
    if (kp3s_mpu_detect_test_result)
      snprintf_P(countline, sizeof(countline), FTOP(kp3s_tr(F("MPU:%u OK"),F("MPU:%u OK"),F("MPU:%u OK"),F("MPU:%u OK"),F("MPU:%u OK"))), unsigned(kp3s_mpu6050_detected_count()));
    else
      snprintf_P(countline, sizeof(countline), FTOP(kp3s_tr(F("MPU:%u CHECK"),F("MPU:%u REVER"),F("MPU:%u REVIS."),F("MPU:%u VÉRIF."),F("MPU:%u PRÜF."))), unsigned(kp3s_mpu6050_detected_count()));
    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("DETECT MPU"),F("DETECTAR MPU"),F("DETECTAR MPU"),F("DÉTECTER MPU"),F("MPU PRÜFEN")), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(line68, SS_CENTER);
    STATIC_ITEM_C(line69, SS_CENTER);
    STATIC_ITEM_C(countline, SS_CENTER);
    END_SCREEN();
  }

  static void kp3s_run_mpu_detect_test() {
    kp3s_mpu_detect_test_result = kp3s_mpu6050_detect_now();
    ui.push_current_screen();
    ui.goto_screen(screen_kp3s_mpu_detect_test);
  }

  static void screen_kp3s_digital_level() {
    if (kp3s_runtime_machine_busy()) return ui.goto_previous_screen();
    if (ui.use_click()) return ui.goto_previous_screen();
    float roll=0, pitch=0, rms=0, peak=0, instant=0;
    char xline[KP3S_MPU_UI_LINE_CAP], yline[KP3S_MPU_UI_LINE_CAP], state_line[KP3S_MPU_UI_LINE_CAP];
    const bool ok = kp3s_mpu6050_level_for_role(kp3s_mpu_ui_role, roll, pitch);
    const bool motion_ok = kp3s_mpu6050_motion_for_role(kp3s_mpu_ui_role, rms, peak, instant);
    if (ok) { kp3s_format_angle(xline, 'X', roll); kp3s_format_angle(yline, 'Y', pitch); }
    else { strcpy_P(xline, PSTR("X: --.-")); strcpy_P(yline, PSTR("Y: --.-")); }

    const bool leveled = ok && WITHIN(roll, -0.5f, 0.5f) && WITHIN(pitch, -0.5f, 0.5f);
    if (!kp3s_mpu6050_runtime_enabled) strcpy_P(state_line, FTOP(kp3s_tr(F("MPU OFF"),F("MPU DESATIVADO"),F("MPU DESACTIV."),F("MPU DÉSACTIVÉ"),F("MPU DEAKTIV."))));
    else if (!ok) strcpy_P(state_line, FTOP(kp3s_tr(F("NO MPU DATA"),F("SEM DADOS MPU"),F("SIN DATOS MPU"),F("PAS DE DONNÉES"),F("KEINE MPU-DAT."))));
    else if (!kp3s_mpu6050_motion_stable_for_role(kp3s_mpu_ui_role)) strcpy_P(state_line, FTOP(kp3s_tr(F("LIVE / MOVING"),F("EM MOVIMENTO"),F("EN MOVIMIENTO"),F("EN MOUVEMENT"),F("IN BEWEGUNG"))));
    else strcpy_P(state_line, FTOP(leveled
      ? kp3s_tr(F("LEVEL OK"),F("NÍVEL OK"),F("NIVEL OK"),F("NIVEAU OK"),F("NEIGUNG OK"))
      : kp3s_tr(F("ADJUST BASE"),F("AJUSTE BASE"),F("AJUSTE BASE"),F("RÉGLER BASE"),F("BASIS EINST."))));
    if (motion_ok && strlen(state_line) < 10) {
      char v[8]; const uint16_t centi=uint16_t(_MIN(9.99f,rms)*100.0f+0.5f);
      snprintf_P(v,sizeof(v),PSTR(" V:%u.%02u"),unsigned(centi/100),unsigned(centi%100)); strlcat(state_line,v,KP3S_MPU_UI_LINE_CAP);
    }

    START_SCREEN();
    STATIC_ITEM_F(kp3s_mpu_role_title(kp3s_mpu_ui_role), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(xline, SS_CENTER);
    STATIC_ITEM_C(yline, SS_CENTER);
    STATIC_ITEM_C(state_line, SS_CENTER);
    END_SCREEN();
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void screen_kp3s_mpu_motion() {
    if (kp3s_runtime_machine_busy()) return ui.goto_previous_screen();
    if (ui.use_click()) return ui.goto_previous_screen();
    float rms=0, peak=0, instant=0;
    char rmsline[KP3S_MPU_UI_LINE_CAP], peakline[KP3S_MPU_UI_LINE_CAP], nowline[KP3S_MPU_UI_LINE_CAP];
    const bool ok=kp3s_mpu6050_motion_for_role(kp3s_mpu_ui_role,rms,peak,instant);
    if (ok) {
      const uint16_t r=uint16_t(_MIN(9.99f,rms)*100.0f+0.5f), p=uint16_t(_MIN(9.99f,peak)*100.0f+0.5f), n=uint16_t(_MIN(9.99f,instant)*100.0f+0.5f);
      snprintf_P(rmsline,sizeof(rmsline),PSTR("RMS:%u.%02ug"),unsigned(r/100),unsigned(r%100));
      snprintf_P(peakline,sizeof(peakline),FTOP(kp3s_tr(F("PEAK:%u.%02ug"),F("PICO:%u.%02ug"),F("PICO:%u.%02ug"),F("CRÊTE:%u.%02ug"),F("SPITZ:%u.%02ug"))),unsigned(p/100),unsigned(p%100));
      snprintf_P(nowline,sizeof(nowline),PSTR("A:%u.%02ug %uHz"),unsigned(n/100),unsigned(n%100),unsigned(kp3s_mpu6050_sample_rate_hz_for_role(kp3s_mpu_ui_role)));
    }
    else { strcpy_P(rmsline,PSTR("RMS:--")); strcpy_P(peakline,FTOP(kp3s_tr(F("PEAK:--"),F("PICO:--"),F("PICO:--"),F("CRÊTE:--"),F("SPITZ:--")))); strcpy_P(nowline,PSTR("A:--")); }
    START_SCREEN();
    STATIC_ITEM_F(kp3s_mpu_role_title(kp3s_mpu_ui_role), SS_CENTER | SS_INVERT);
    STATIC_ITEM_C(rmsline, SS_CENTER);
    STATIC_ITEM_C(peakline, SS_CENTER);
    STATIC_ITEM_C(nowline, SS_CENTER);
    END_SCREEN();
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void screen_kp3s_mpu_temperature() {
    if (kp3s_runtime_machine_busy()) return ui.goto_previous_screen();
    if (ui.use_click()) return ui.goto_previous_screen();
    float temp_c=0, delta_c=0;
    char tline[KP3S_MPU_UI_LINE_CAP], off[KP3S_MPU_UI_LINE_CAP], delta[KP3S_MPU_UI_LINE_CAP];
    const bool ok=kp3s_mpu6050_temperature_c_for_role(kp3s_mpu_ui_role,temp_c);
    const bool delta_ok=kp3s_mpu6050_temperature_delta_c_for_role(kp3s_mpu_ui_role,delta_c);
    if (ok) kp3s_format_mpu_temperature(tline,temp_c); else strcpy_P(tline,PSTR("T: --.- C"));
    const float offset=*kp3s_mpu_role_temp_offset_ptr();
    const int16_t off_t=int16_t(offset*10.0f+(offset>=0?0.5f:-0.5f));
    snprintf_P(off,sizeof(off),FTOP(kp3s_tr(F("OFS:%c%u.%uC"),F("DESV:%c%u.%uC"),F("DESV:%c%u.%uC"),F("DÉC:%c%u.%uC"),F("VERS:%c%u.%uC"))),off_t<0?'-':'+',unsigned(ABS(off_t)/10),unsigned(ABS(off_t)%10));
    if (delta_ok) { const int16_t d=int16_t(delta_c*10.0f+(delta_c>=0?0.5f:-0.5f)); snprintf_P(delta,sizeof(delta),PSTR("DT:%c%u.%uC"),d<0?'-':'+',unsigned(ABS(d)/10),unsigned(ABS(d)%10)); }
    else strcpy_P(delta,PSTR("DT: --.-C"));
    START_SCREEN();
    STATIC_ITEM_F(kp3s_mpu_role_title(kp3s_mpu_ui_role),SS_CENTER|SS_INVERT);
    STATIC_ITEM_C(tline,SS_CENTER);
    STATIC_ITEM_C(off,SS_CENTER);
    STATIC_ITEM_C(delta,SS_CENTER);
    END_SCREEN();
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void menu_kp3s_mpu_role_calibration() {
    const bool busy=kp3s_runtime_machine_busy();
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (!busy) {
      ACTION_ITEM_F(kp3s_tr(F("Set Level Zero"),F("Zerar Nível"),F("Fijar Cero"),F("Définir Zéro"),F("Null Setzen")),kp3s_open_mpu_zero_calibration);
      CONFIRM_ITEM_F(kp3s_tr(F("Clear Level 0"),F("Apagar Zero"),F("Borrar Cero"),F("Effacer Zéro"),F("Null Löschen")),
        MSG_YES, MSG_NO,
        kp3s_run_mpu_clear_zero, nullptr,
        kp3s_tr(F("Clear Zero"),F("Apagar Zero"),F("Borrar Cero"),F("Effacer Zéro"),F("Null Löschen")), (const char *)nullptr, F("?")
      );
      EDIT_ITEM_F(float31,kp3s_tr(F("Temp Offset"),F("Desvio Temp."),F("Desvío Temp."),F("Décal. Temp."),F("Temp.-Versatz")),kp3s_mpu_role_temp_offset_ptr(),-30.0f,30.0f,kp3s_mpu6050_calibration_changed);
    }
    else
      STATIC_ITEM_F(kp3s_tr(F("CALIB. LOCKED"),F("CALIB. BLOQ."),F("CALIB. BLOQ."),F("CALIB. BLOQUÉE"),F("KALIB. GESP.")),SS_CENTER|SS_INVERT);
    END_MENU();
  }

  static void menu_kp3s_mpu_role_data() {
    const bool busy=kp3s_runtime_machine_busy();
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (busy)
      STATIC_ITEM_F(kp3s_tr(F("IMU LOCKED"),F("IMU BLOQ."),F("IMU BLOQ."),F("IMU BLOQUÉE"),F("IMU GESP.")),SS_CENTER|SS_INVERT);
    else {
      SUBMENU_F(kp3s_tr(F("Level"),F("Nível"),F("Nivel"),F("Niveau"),F("Neigung")),screen_kp3s_digital_level);
      SUBMENU_F(kp3s_tr(F("Vibration"),F("Vibração"),F("Vibración"),F("Vibration"),F("Vibration")),screen_kp3s_mpu_motion);
      SUBMENU_F(kp3s_tr(F("Temperature"),F("Temperatura"),F("Temperatura"),F("Température"),F("Temperatur")),screen_kp3s_mpu_temperature);
      SUBMENU_F(kp3s_tr(F("Calibration"),F("Calibração"),F("Calibración"),F("Étalonnage"),F("Kalibrierung")),menu_kp3s_mpu_role_calibration);
    }
    END_MENU();
  }

  static void menu_kp3s_mpu_toolhead_data() { kp3s_mpu_ui_role=KP3SMPU6050Role::TOOLHEAD; menu_kp3s_mpu_role_data(); }
  static void menu_kp3s_mpu_bed_data() { kp3s_mpu_ui_role=KP3SMPU6050Role::BED; menu_kp3s_mpu_role_data(); }

  static void kp3s_mpu_save_role(const KP3SMPU6050Role role) {
    kp3s_mpu6050_set_role(kp3s_mpu_role_edit_addr,role);
    #if ENABLED(EEPROM_SETTINGS)
      MarlinSettings::save();
    #endif
    ui.goto_previous_screen();
  }
  static void kp3s_mpu_role_unused() { kp3s_mpu_save_role(KP3SMPU6050Role::UNUSED); }
  static void kp3s_mpu_role_bed() { kp3s_mpu_save_role(KP3SMPU6050Role::BED); }
  static void kp3s_mpu_role_toolhead() { kp3s_mpu_save_role(KP3SMPU6050Role::TOOLHEAD); }

  static void menu_kp3s_mpu_role_assignment() {
    char current[KP3S_MPU_UI_LINE_CAP];
    snprintf_P(current,sizeof(current),PSTR("0x%02X: %s"),unsigned(kp3s_mpu_role_edit_addr),kp3s_mpu_role_tag(kp3s_mpu6050_role_for_address(kp3s_mpu_role_edit_addr)));
    START_MENU();
    BACK_ITEM(MSG_BACK);
    STATIC_ITEM_C(current,SS_CENTER|SS_INVERT);
    ACTION_ITEM_F(kp3s_tr(F("Unused"),F("Não usado"),F("Sin usar"),F("Non utilisé"),F("Unbenutzt")),kp3s_mpu_role_unused);
    ACTION_ITEM_F(kp3s_tr(F("Bed"),F("Mesa"),F("Cama"),F("Plateau"),F("Bett")),kp3s_mpu_role_bed);
    ACTION_ITEM_F(kp3s_tr(F("Toolhead"),F("Cabeçote"),F("Cabezal"),F("Tête d'outil"),F("Druckkopf")),kp3s_mpu_role_toolhead);
    END_MENU();
  }
  static void menu_kp3s_mpu_role_68() { kp3s_mpu_role_edit_addr=0x68; menu_kp3s_mpu_role_assignment(); }
  static void menu_kp3s_mpu_role_69() { kp3s_mpu_role_edit_addr=0x69; menu_kp3s_mpu_role_assignment(); }

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
      const uint16_t fq=uint16_t(kp3s_res_frequency_hz*10.0f+0.5f);
      snprintf_P(freq,sizeof(freq),PSTR("%c:%u.%u Hz"),kp3s_res_axis==X_AXIS?'X':'Y',unsigned(fq/10),unsigned(fq%10));
      snprintf_P(conf,sizeof(conf),FTOP(kp3s_tr(F("CONF:%u%%"),F("CONF:%u%%"),F("CONF:%u%%"),F("CONF:%u%%"),F("SICH:%u%%"))),unsigned(kp3s_res_confidence));
    }
    else {
      strcpy_P(freq,FTOP(kp3s_tr(F("FREQ: --.-"),F("FREQ: --.-"),F("FREC: --.-"),F("FRÉQ: --.-"),F("FREQ: --.-"))));
      if (kp3s_res_sample_count)
        snprintf_P(conf,sizeof(conf),FTOP(kp3s_tr(F("SAMP:%u"),F("AMOST:%u"),F("MUEST:%u"),F("ÉCH:%u"),F("MESS:%u"))),unsigned(kp3s_res_sample_count));
      else
        strcpy_P(conf,FTOP(kp3s_tr(F("CONF: --"),F("CONF: --"),F("CONF: --"),F("CONF: --"),F("SICH: --"))));
    }
    FSTR_P status=kp3s_tr(F("NO RESULT"),F("SEM RESULTADO"),F("SIN RESULTADO"),F("AUCUN RÉSULTAT"),F("KEIN ERGEBNIS"));
    switch (kp3s_res_state) {
      case KP3SResonanceUIState::HOMING: status=kp3s_tr(F("HOMING..."),F("REFERENCIANDO"),F("REFERENCIANDO"),F("RÉFÉRENÇAGE"),F("REFERENZFAHRT")); break;
      case KP3SResonanceUIState::RUNNING: status=kp3s_tr(F("MEASURING..."),F("MEDINDO..."),F("MIDIENDO..."),F("MESURE..."),F("MESSUNG...")); break;
      case KP3SResonanceUIState::APPLIED: status=kp3s_tr(F("APPLIED+SAVED"),F("APLICADO+SALVO"),F("APLIC.+GUARD."),F("APPL.+SAUVÉ"),F("ANW.+GESPEICH.")); break;
      case KP3SResonanceUIState::LOW_CONF: status=kp3s_tr(F("LOW CONFIDENCE"),F("BAIXA CONFIAN."),F("BAJA CONFIANZA"),F("FIABIL. FAIBLE"),F("GERINGE SICH.")); break;
      case KP3SResonanceUIState::HOME_FAIL: status=kp3s_tr(F("HOME FAILED"),F("FALHA ORIGEM"),F("FALLO ORIGEN"),F("ÉCHEC ORIGINE"),F("REFERENZFEHL.")); break;
      case KP3SResonanceUIState::SAFE_Z_FAIL: status=kp3s_tr(F("SAFE Z FAILED"),F("FALHA Z SEG."),F("FALLO Z SEG."),F("ÉCHEC Z SÉCUR."),F("SICHER-Z FEHL.")); break;
      case KP3SResonanceUIState::BUSY: status=kp3s_tr(F("PRINTER BUSY"),F("IMPR. OCUPADA"),F("IMPRES. OCUP."),F("IMPRIM. OCCUP."),F("DRUCKER BELEGT")); break;
      case KP3SResonanceUIState::NO_MPU: status=kp3s_tr(F("NO MPU DATA"),F("SEM DADOS MPU"),F("SIN DATOS MPU"),F("PAS DE DONNÉES"),F("KEINE MPU-DAT.")); break;
      case KP3SResonanceUIState::NO_SPACE: status=kp3s_tr(F("AXIS TOO CLOSE"),F("EIXO MTO PRÓX."),F("EJE MUY CERCA"),F("AXE TROP PRÈS"),F("ACHSE ZU NAH")); break;
      case KP3SResonanceUIState::CAPTURE_FAIL: status=kp3s_tr(F("CAPTURE FAILED"),F("FALHA CAPTURA"),F("FALLO CAPTURA"),F("ÉCHEC CAPTURE"),F("ERFASS. FEHL.")); break;
      case KP3SResonanceUIState::SAVE_FAIL: status=kp3s_tr(F("SAVE FAILED"),F("ERRO AO SALVAR"),F("ERR. AL GUARD."),F("ÉCHEC SAUVEG."),F("SPEICH.FEHLER")); break;
      default: break;
    }
    START_SCREEN();
    STATIC_ITEM_F(kp3s_tr(F("RESONANCE TUNE"),F("AJUSTE RESSON."),F("AJUSTE RESON."),F("RÉGLAGE RÉSON."),F("RESONANZ-ABGL")),SS_CENTER|SS_INVERT);
    STATIC_ITEM_C(freq,SS_CENTER);
    STATIC_ITEM_C(conf,SS_CENTER);
    STATIC_ITEM_F(status,SS_CENTER);
    END_SCREEN();
  }

  static void kp3s_run_resonance_axis(const AxisEnum axis) {
    kp3s_res_axis=axis; kp3s_res_frequency_hz=0.0f; kp3s_res_confidence=0; kp3s_res_sample_count=0;
    ui.push_current_screen();

    bool resonance_busy=printingIsActive() || printingIsPaused() || planner.has_blocks_queued();
    #if ENABLED(KP3S_SMART_UI)
      resonance_busy |= kp3s_serial_printing(millis()) || kp3s_serial_print_paused();
    #endif
    if (resonance_busy) { kp3s_res_state=KP3SResonanceUIState::BUSY; ui.goto_screen(screen_kp3s_resonance_result); return; }

    const KP3SMPU6050Role resonance_role = axis == X_AXIS ? KP3SMPU6050Role::TOOLHEAD : KP3SMPU6050Role::BED;
    if (!kp3s_mpu6050_detected_role(resonance_role) || !kp3s_mpu6050_sample_for_role(resonance_role).valid) {
      kp3s_res_state=KP3SResonanceUIState::NO_MPU; ui.goto_screen(screen_kp3s_resonance_result); return;
    }

    kp3s_res_state=KP3SResonanceUIState::HOMING;
    ui.goto_screen(screen_kp3s_resonance_result); ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); safe_delay(80);

    #if HAS_LEVELING
      const bool leveling_was_active=planner.leveling_active;
      set_bed_leveling_enabled(false);
    #endif

    gcode.process_subcommands_now(F("G28")); planner.synchronize();
    if (axis_should_home(X_AXIS) || axis_should_home(Y_AXIS) || axis_should_home(Z_AXIS)) {
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::HOME_FAIL; ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    if (current_position.z < 10.0f) do_blocking_move_to_z(10.0f,5.0f);
    planner.synchronize();
    if (current_position.z < 5.0f) {
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::SAFE_Z_FAIL; ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    const float amin=base_min_pos(axis)+7.0f, amax=base_max_pos(axis)-7.0f;
    if (amax-amin < 16.0f) {
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::NO_SPACE; ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }
    const float center=(amin+amax)*0.5f, lo=center-5.0f, hi=center+5.0f;
    kp3s_res_state=KP3SResonanceUIState::RUNNING; ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);

    planner.synchronize();
    const float previous_shaping=stepper.get_shaping_frequency(axis);
    stepper.set_shaping_frequency(axis,0.0f);
    if (axis==X_AXIS) do_blocking_move_to_x(center,45.0f); else do_blocking_move_to_y(center,45.0f);
    if (axis==X_AXIS) do_blocking_move_to_x(lo,45.0f); else do_blocking_move_to_y(lo,45.0f);
    safe_delay(200); kp3s_mpu6050_task(millis());

    if (!kp3s_mpu6050_detected_role(resonance_role) || !kp3s_mpu6050_sample_for_role(resonance_role).valid) {
      stepper.set_shaping_frequency(axis,previous_shaping);
      if (axis==X_AXIS) do_blocking_move_to_x(center,45.0f); else do_blocking_move_to_y(center,45.0f);
      planner.synchronize();
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::NO_MPU; ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    kp3s_mpu6050_resonance_capture_start(resonance_role);
    if (!kp3s_mpu6050_resonance_capturing()) {
      stepper.set_shaping_frequency(axis,previous_shaping);
      if (axis==X_AXIS) do_blocking_move_to_x(center,45.0f); else do_blocking_move_to_y(center,45.0f);
      planner.synchronize();
      #if HAS_LEVELING
        set_bed_leveling_enabled(leveling_was_active);
      #endif
      kp3s_res_state=KP3SResonanceUIState::CAPTURE_FAIL; ui.refresh(LCDVIEW_CALL_REDRAW_NEXT); return;
    }

    current_position[axis]=hi; line_to_current_position(120.0f);
    current_position[axis]=lo; line_to_current_position(120.0f);
    const millis_t capture_deadline=millis()+1400UL;
    while (kp3s_mpu6050_resonance_capturing() && PENDING(millis(),capture_deadline)) {
      kp3s_mpu6050_task(millis()); thermalManager.task(); hal.watchdog_refresh(); delay(1);
    }
    planner.synchronize();
    kp3s_res_sample_count=kp3s_mpu6050_resonance_samples();
    const bool analyzed=kp3s_mpu6050_resonance_capture_analyze(kp3s_res_frequency_hz,kp3s_res_confidence);
    stepper.set_shaping_frequency(axis,previous_shaping);
    if (axis==X_AXIS) do_blocking_move_to_x(center,45.0f); else do_blocking_move_to_y(center,45.0f);
    planner.synchronize();
    #if HAS_LEVELING
      set_bed_leveling_enabled(leveling_was_active);
    #endif

    constexpr uint8_t required_confidence = 45;
    if (analyzed && kp3s_res_confidence >= required_confidence) {
      stepper.set_shaping_frequency(axis,kp3s_res_frequency_hz);
      #if ENABLED(EEPROM_SETTINGS)
        kp3s_res_state=settings.save()?KP3SResonanceUIState::APPLIED:KP3SResonanceUIState::SAVE_FAIL;
      #else
        kp3s_res_state=KP3SResonanceUIState::APPLIED;
      #endif
    }
    else kp3s_res_state=analyzed?KP3SResonanceUIState::LOW_CONF:KP3SResonanceUIState::CAPTURE_FAIL;
    ui.refresh(LCDVIEW_CALL_REDRAW_NEXT);
  }

  static void kp3s_run_resonance_x() { kp3s_run_resonance_axis(X_AXIS); }
  static void kp3s_run_resonance_y() { kp3s_run_resonance_axis(Y_AXIS); }

  void menu_kp3s_resonance_tuning() {
    const bool busy=kp3s_runtime_machine_busy();
    const bool x_ready=kp3s_mpu6050_runtime_enabled && kp3s_mpu6050_address_for_role(KP3SMPU6050Role::TOOLHEAD);
    const bool y_ready=kp3s_mpu6050_runtime_enabled && kp3s_mpu6050_address_for_role(KP3SMPU6050Role::BED);
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (busy)
      STATIC_ITEM_F(kp3s_tr(F("TUNING LOCKED"),F("AJUSTE BLOQ."),F("AJUSTE BLOQ."),F("RÉGLAGE BLOQ."),F("ABGL. GESP.")),SS_CENTER|SS_INVERT);
    else {
      if (x_ready) ACTION_ITEM_F(kp3s_tr(F("Auto Tune X"),F("Autoajuste X"),F("Autoajuste X"),F("Réglage auto X"),F("AUTO-ABGL. X")),kp3s_run_resonance_x);
      else STATIC_ITEM_F(kp3s_tr(F("X: NO TOOL IMU"),F("X: SEM IMU CAB"),F("X: SIN IMU CAB"),F("X: SANS IMU T."),F("X: KEIN K-IMU")),SS_CENTER);
      if (y_ready) ACTION_ITEM_F(kp3s_tr(F("Auto Tune Y"),F("Autoajuste Y"),F("Autoajuste Y"),F("Réglage auto Y"),F("AUTO-ABGL. Y")),kp3s_run_resonance_y);
      else STATIC_ITEM_F(kp3s_tr(F("Y: NO BED IMU"),F("Y: SEM IMU M."),F("Y: SIN IMU C."),F("Y: SANS IMU P."),F("Y: KEIN B-IMU")),SS_CENTER);
    }
    if (kp3s_res_state != KP3SResonanceUIState::NONE)
      SUBMENU_F(kp3s_tr(F("Last Result"),F("Último result."),F("Último result."),F("Dernier rés."),F("Letztes Erg.")),screen_kp3s_resonance_result);
    END_MENU();
  }

  static void menu_kp3s_mpu_devices() {
    const bool busy=kp3s_runtime_machine_busy();
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (!busy) {
      EDIT_ITEM_F(bool,kp3s_tr(F("MPU6050 On"),F("MPU6050 Ativo"),F("MPU6050 Activo"),F("MPU6050 Actif"),F("MPU6050 Aktiv")),&kp3s_mpu6050_runtime_enabled,kp3s_mpu6050_changed);
      EDIT_ITEM_F(bool,kp3s_tr(F("Swap SDA/SCL"),F("Trocar SDA/SCL"),F("Camb. SDA/SCL"),F("Inv. SDA/SCL"),F("SDA/SCL Tausch")),&kp3s_mpu6050_swap_lines,kp3s_mpu6050_wiring_changed);
      SUBMENU_F(kp3s_tr(F("MPU 0x68 Role"),F("Funç. MPU 0x68"),F("Rol MPU 0x68"),F("Rôle MPU 0x68"),F("MPU 0x68 Rolle")),menu_kp3s_mpu_role_68);
      SUBMENU_F(kp3s_tr(F("MPU 0x69 Role"),F("Funç. MPU 0x69"),F("Rol MPU 0x69"),F("Rôle MPU 0x69"),F("MPU 0x69 Rolle")),menu_kp3s_mpu_role_69);
    }
    else
      STATIC_ITEM_F(kp3s_tr(F("SETUP LOCKED"),F("CONFIG. BLOQ."),F("CONFIG. BLOQ."),F("CONFIG. BLOQ."),F("EINST. GESP.")),SS_CENTER|SS_INVERT);
    END_MENU();
  }

  static void menu_kp3s_mpu_diagnostics() {
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (!kp3s_runtime_machine_busy()) {
      ACTION_ITEM_F(kp3s_tr(F("Detect Devices"),F("Detectar disp."),F("Detectar disp."),F("Détecter capt."),F("Geräte suchen")),kp3s_run_mpu_detect_test);
      ACTION_ITEM_F(kp3s_tr(F("Test I2C Bus"),F("Testar bus I2C"),F("Probar bus I2C"),F("Tester bus I2C"),F("I2C-Bus testen")),kp3s_run_mpu_bus_test);
    }
    else
      STATIC_ITEM_F(kp3s_tr(F("DIAG. LOCKED"),F("DIAG. BLOQ."),F("DIAG. BLOQ."),F("DIAG. BLOQ."),F("DIAG. GESP.")),SS_CENTER|SS_INVERT);
    END_MENU();
  }

  static void menu_kp3s_mpu6050_settings() {
    const bool busy=kp3s_runtime_machine_busy();
    START_MENU();
    BACK_ITEM(MSG_BACK);
    if (busy) {
      STATIC_ITEM_F(kp3s_tr(F("IMU BUSY"),F("IMU OCUPADA"),F("IMU OCUPADA"),F("IMU OCCUPÉE"),F("IMU BELEGT")),SS_CENTER|SS_INVERT);
    }
    else {
      SUBMENU_F(kp3s_tr(F("Devices/Wiring"),F("Disp./Fiação"),F("Disp./Cableado"),F("Capteurs/Câbl."),F("Geräte/Kabel")),menu_kp3s_mpu_devices);
      if (kp3s_mpu6050_runtime_enabled && kp3s_mpu6050_address_for_role(KP3SMPU6050Role::BED))
        SUBMENU_F(kp3s_tr(F("Bed IMU"),F("IMU Mesa"),F("IMU Cama"),F("IMU Plateau"),F("Bett-IMU")),menu_kp3s_mpu_bed_data);
      if (kp3s_mpu6050_runtime_enabled && kp3s_mpu6050_address_for_role(KP3SMPU6050Role::TOOLHEAD))
        SUBMENU_F(kp3s_tr(F("Toolhead IMU"),F("IMU Cabeçote"),F("IMU Cabezal"),F("IMU Tête outil"),F("Druckkopf-IMU")),menu_kp3s_mpu_toolhead_data);
      if (kp3s_mpu6050_runtime_enabled)
        SUBMENU_F(kp3s_tr(F("Diagnostics"),F("Diagnósticos"),F("Diagnósticos"),F("Diagnostics"),F("Diagnose")),menu_kp3s_mpu_diagnostics);
    }
    END_MENU();
  }
#endif

void menu_configuration() {
""",
        "Create V1-specific menu callbacks and IMU screens",
    )

    replace_once(
        menu_config,
        '    #if ENABLED(BLTOUCH)\n      SUBMENU(MSG_BLTOUCH, menu_bltouch);\n    #endif\n',
        '    #if ENABLED(BLTOUCH)\n      #if ENABLED(KP3S_RUNTIME_BLTOUCH)\n        if (!kp3s_runtime_machine_busy())\n          EDIT_ITEM_F(bool, kp3s_tr(F("BLTouch On"),F("BLTouch Ativo"),F("BLTouch Activo"),F("BLTouch Actif"),F("BLTouch Aktiv")), &kp3s_bltouch_runtime_enabled, kp3s_runtime_bltouch_changed);\n        if (kp3s_bltouch_runtime_enabled && !kp3s_runtime_machine_busy())\n          SUBMENU(MSG_BLTOUCH, menu_bltouch);\n      #else\n        SUBMENU(MSG_BLTOUCH, menu_bltouch);\n      #endif\n    #endif\n',
        'Keep BLTouch runtime enable and native tools together',
    )

    # Keep Language with display controls instead of as a top-level Main item.
    replace_once(
        menu_config,
        'void menu_advanced_settings();\n',
        'void menu_advanced_settings();\n#if HAS_MULTI_LANGUAGE\n  void menu_language();\n#endif\n',
        'Declare Language menu in Configuration',
    )
    regex_once(
        menu_config,
        r"""  //\n  // Set display backlight / sleep timeout\n  //\n  #if ENABLED\(EDITABLE_DISPLAY_TIMEOUT\)\n    #if HAS_BACKLIGHT_TIMEOUT\n      EDIT_ITEM\(uint8, MSG_SCREEN_TIMEOUT, &ui\.backlight_timeout_minutes, ui\.backlight_timeout_min, ui\.backlight_timeout_max, ui\.refresh_backlight_timeout\);\n    #elif HAS_DISPLAY_SLEEP\n      EDIT_ITEM\(uint8, MSG_SCREEN_TIMEOUT, &ui\.sleep_timeout_minutes, ui\.sleep_timeout_min, ui\.sleep_timeout_max, ui\.refresh_screen_timeout\);\n    #endif\n  #endif\n""",
        '  // V1: Display timeout lives in the dedicated Display submenu.\n',
        'Move display timeout into Display submenu',
    )
    replace_once(
        menu_main,
        '  #if HAS_MULTI_LANGUAGE\n    SUBMENU(LANGUAGE, menu_language);\n  #endif\n',
        '  // V1: Language lives inside the dedicated Display submenu.\n',
        'Remove duplicate Language item from Main',
    )
    replace_once(
        menu_language,
        '  BACK_ITEM(MSG_MAIN_MENU);\n',
        '  BACK_ITEM(MSG_BACK);\n',
        'Make Language Back label match the Display submenu parent',
    )
    replace_once(
        menu_language,
        '#include "../../module/settings.h"\n',
        '#include "../../module/settings.h"\n\nvoid menu_kp3s_display_settings();\n',
        'Declare Display submenu as the V1 Language return target',
    )
    replace_once(
        menu_language,
        '  TERN_(LCD_LANGUAGE_AUTO_SAVE, (void)settings.save());\n',
        '  TERN_(LCD_LANGUAGE_AUTO_SAVE, (void)settings.save());\n  ui.goto_screen(menu_kp3s_display_settings);\n',
        'Return to Display submenu after choosing a language',
    )

    # Consolidate firmware identity into Marlin's native Info menu.
    replace_once(
        menu_info,
        '    STATIC_ITEM(MSG_MARLIN, SS_DEFAULT|SS_INVERT);                // Marlin\n',
        '    STATIC_ITEM(MSG_MARLIN, SS_DEFAULT|SS_INVERT);                // Marlin\n    STATIC_ITEM_F(F("KP3S V1"), SS_CENTER|SS_INVERT);\n    STATIC_ITEM_F(F("spidoug"), SS_CENTER);\n',
        'Add V1 identity to native Printer Info',
    )

    replace_once(
        menu_advanced,
        '#include "../../module/stepper.h"\n',
        '#include "../../module/stepper.h"\n#if ENABLED(KP3S_MPU6050)\n  #include "../../feature/kp3s_ui_text.h"\n#endif\n',
        'Localize V1 additions in Advanced Settings',
    )

    replace_once(
        menu_advanced,
        'void menu_backlash();\n',
        'void menu_backlash();\n#if ENABLED(KP3S_MPU6050) && HAS_ZV_SHAPING\n  void menu_kp3s_resonance_tuning();\n#endif\n',
        'Declare V1 resonance menu for native Input Shaping',
    )

    replace_once(
        menu_advanced,
        '      START_MENU();\n      BACK_ITEM(MSG_ADVANCED_SETTINGS);\n\n      // M593 F Frequency and D Damping ratio\n',
        '      START_MENU();\n      BACK_ITEM(MSG_ADVANCED_SETTINGS);\n\n      #if ENABLED(KP3S_MPU6050) && HAS_ZV_SHAPING\n        SUBMENU_F(kp3s_tr(F("Auto Resonance"),F("Resson. Auto"),F("Reson. Auto"),F("Résonance Auto"),F("Auto-Resonanz")), menu_kp3s_resonance_tuning);\n      #endif\n\n      // M593 F Frequency and D Damping ratio\n',
        'Place resonance autotune inside native Input Shaping',
    )

    replace_once(
        menu_probe_level,
        '#if HAS_BED_PROBE\n  #include "../../module/probe.h"\n#endif\n',
        '#if HAS_BED_PROBE\n  #include "../../module/probe.h"\n#endif\n#if ENABLED(KP3S_RUNTIME_BLTOUCH)\n  #include "../../feature/kp3s_bltouch_runtime.h"\n  #include "../../feature/kp3s_ui_text.h"\n#endif\n',
        'Make native Probe / Level menu aware of runtime BLTouch state',
    )

    replace_once(
        menu_probe_level,
        '  BACK_ITEM(MSG_MAIN_MENU);\n\n  if (!g29_in_progress) {\n',
        '  BACK_ITEM(MSG_MAIN_MENU);\n\n  #if ENABLED(KP3S_RUNTIME_BLTOUCH)\n    if (!kp3s_bltouch_runtime_enabled)\n      STATIC_ITEM_F(kp3s_tr(F("BLTouch OFF"),F("BLTouch Desl."),F("BLTouch Apag."),F("BLTouch Inact."),F("BLTouch Aus")), SS_CENTER | SS_INVERT);\n  #endif\n\n  if (!g29_in_progress) {\n',
        'Show runtime BLTouch state in Probe / Level without duplicating its toggle',
    )

    replace_once(
        menu_probe_level,
        '      #else\n        // Automatic leveling can just run the G-code\n        GCODES_ITEM(MSG_LEVEL_BED, is_homed ? F("G29") : F("G29N"));\n      #endif\n',
        '      #else\n        // Automatic leveling can just run the G-code. V1 hides this action when the runtime probe is disabled.\n        #if ENABLED(KP3S_RUNTIME_BLTOUCH)\n          if (kp3s_bltouch_runtime_enabled) GCODES_ITEM(MSG_LEVEL_BED, is_homed ? F("G29") : F("G29N"));\n        #else\n          GCODES_ITEM(MSG_LEVEL_BED, is_homed ? F("G29") : F("G29N"));\n        #endif\n      #endif\n',
        'Hide automatic leveling when runtime BLTouch is disabled',
    )

    replace_once(
        menu_probe_level,
        '    #if ENABLED(PROBE_OFFSET_WIZARD)\n      SUBMENU(MSG_PROBE_WIZARD, goto_probe_offset_wizard);\n    #endif\n',
        '    #if ENABLED(PROBE_OFFSET_WIZARD)\n      #if ENABLED(KP3S_RUNTIME_BLTOUCH)\n        if (kp3s_bltouch_runtime_enabled) SUBMENU(MSG_PROBE_WIZARD, goto_probe_offset_wizard);\n      #else\n        SUBMENU(MSG_PROBE_WIZARD, goto_probe_offset_wizard);\n      #endif\n    #endif\n',
        'Hide probe offset wizard when runtime BLTouch is disabled',
    )

    replace_once(
        menu_probe_level,
        '    //\n    // Store to EEPROM\n    //\n    #if ENABLED(EEPROM_SETTINGS)\n      ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);\n    #endif\n\n',
        '    // V1 keeps EEPROM actions in Configuration only, avoiding duplicate Save Settings entries.\n\n',
        'Remove duplicate EEPROM save action from Probe / Level',
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
  return kp3s_tr(F("READY"),F("PRONTO"),F("LISTO"),F("PRÊT"),F("BEREIT"));
}

static FSTR_P kp3s_printing_text() {
  return kp3s_tr(F("PRINTING"),F("IMPRIMINDO"),F("IMPRIMIENDO"),F("IMPRESSION"),F("DRUCKT"));
}

static FSTR_P kp3s_paused_text() {
  return kp3s_tr(F("PAUSED"),F("PAUSADO"),F("PAUSADO"),F("EN PAUSE"),F("PAUSIERT"));
}

static FSTR_P kp3s_hotend_prefix() {
  return kp3s_tr(F("H:"),F("B:"),F("B:"),F("B:"),F("D:"));
}

static FSTR_P kp3s_bed_prefix() {
  return kp3s_tr(F("B:"),F("M:"),F("C:"),F("P:"),F("B:"));
}

static FSTR_P kp3s_progress_prefix() {
  return kp3s_tr(F("P:"),F("P:"),F("P:"),F("P:"),F("F:"));
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
    const KP3SMPU6050Role role = kp3s_mpu6050_detected_role(KP3SMPU6050Role::TOOLHEAD) ? KP3SMPU6050Role::TOOLHEAD : KP3SMPU6050Role::BED;
    if (!kp3s_mpu6050_temperature_c_for_role(role, temperature_c)) return false;
    const int16_t tenths = int16_t(temperature_c * 10.0f + (temperature_c >= 0 ? 0.5f : -0.5f));
    const uint16_t mag = uint16_t(tenths < 0 ? -tenths : tenths);
    snprintf_P(out, KP3S_STATUS_LINE_CAP, PSTR("IMU:%c%u.%uC"), tenths < 0 ? '-' : '+', unsigned(mag / 10), unsigned(mag % 10));
    return true;
  }

  static bool kp3s_status_startup_level_line(char * const out) {
    if (!kp3s_mpu6050_runtime_enabled || !kp3s_mpu6050_address_for_role(KP3SMPU6050Role::BED)) return false;
    float roll=0,pitch=0; bool level_ok=false;
    constexpr KP3SMPU6050Role role = KP3SMPU6050Role::BED;
    if (!kp3s_mpu6050_startup_level_for_role(role,roll,pitch,level_ok)) {
      if (!kp3s_mpu6050_detected_role(role)) {
        strcpy_P(out,FTOP(kp3s_tr(F("LEVEL: MPU..."),F("NÍVEL: MPU..."),F("NIVEL: MPU..."),F("NIV.: MPU..."),F("NEIG.: MPU..."))));
        return true;
      }
      snprintf_P(out,KP3S_STATUS_LINE_CAP,FTOP(kp3s_tr(F("LEVEL:%u%%"),F("NÍVEL:%u%%"),F("NIVEL:%u%%"),F("NIV.:%u%%"),F("NEIG.:%u%%"))),unsigned(kp3s_mpu6050_startup_progress_pct_for_role(role)));
      return true;
    }
    if (!kp3s_mpu6050_startup_notice_for_role(role,roll,pitch,level_ok)) return false;
    if (level_ok) {
      strcpy_P(out,FTOP(kp3s_tr(F("LEVEL OK"),F("NÍVEL OK"),F("NIVEL OK"),F("NIVEAU OK"),F("NEIGUNG OK"))));
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
BLTouch starts disabled and can be enabled from Configuration > BLTouch On.

FILAMENT RUNOUT
SIGNAL -> PA4 / Filament Detection 1
GND    -> sensor connector GND
Runout triggers M600 / Advanced Pause.

MPU6050 - SOFTWARE I2C
VCC -> FFC1 / 3.3V
GND -> FFC2 / GND
DEFAULT SDA -> FFC17 / PD9
DEFAULT SCL -> FFC16 / PD8
LCD: Configuration > MPU6050 / IMU > Devices / Wiring > Swap SDA/SCL exchanges these two roles and auto-saves the orientation
INT/XDA/XCL -> NC
AD0 -> LOW selects 0x68; HIGH selects 0x69. Up to two MPU6050 modules may share PD8/PD9 when their AD0 straps differ.
Runtime -> assign 0x68 and/or 0x69 independently as MESA, EXTRUSORA or NAO USADO. V1 defaults: both addresses are unassigned until configured.
Printing/paused -> MPU I2C is always suspended. Sensor polling, retries and bus recovery are idle-only.
Calibration -> independent zero and temperature offset for bed and toolhead. Disabled releases PD8/PD9.

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
            '#define CUSTOM_MACHINE_NAME "KINGROON KP3S V1"',
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
            "kp3s_draw_select_choice",
            "own clipped half-screen field",
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
            'uint8_t MarlinUI::language = 0; // V1 primary/default: English',
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
            "kp3s_mpu6050_startup_progress_pct_for_role",
            "kp3s_mpu6050_temperature_c_for_role",
            'F("NÍVEL:%u%%")',
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
            "enum class KP3SMPU6050Role",
            "kp3s_mpu6050_role_68",
            "kp3s_mpu6050_role_69",
            "kp3s_mpu6050_detected_at",
            "kp3s_mpu6050_detected_role",
            "kp3s_mpu6050_set_role",
            "kp3s_mpu6050_level_for_role",
            "kp3s_mpu6050_motion_for_role",
            "kp3s_mpu6050_temperature_c_for_role",
            "kp3s_mpu6050_resonance_capture_start(const KP3SMPU6050Role role",
        ],
        OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050_impl.h": [
            "SET_INPUT_PULLUP",
            "static KP3SMPU6050DeviceState kp3s_mpu_devices[2]",
            "address == 0x68",
            "address == 0x69",
            "kp3s_i2c_probe_ack(0x68)",
            "kp3s_i2c_probe_ack(0x69)",
            "kp3s_mpu_configure_and_verify(KP3SMPU6050DeviceState &dev)",
            "kp3s_mpu_read_sample_now(KP3SMPU6050DeviceState &dev",
            "kp3s_mpu_write_reg(dev,0x6B,0x80,true)",
            "kp3s_mpu_read_regs(dev,0x3B",
            "kp3s_mpu_job_active",
            "kp3s_mpu_background_blocked",
            "planner.has_blocks_queued()",
            "if (kp3s_mpu_job_active(now)) { kp3s_res_capture=false; return; }",
            "if (kp3s_mpu_background_blocked(now)) return;",
            "kp3s_mpu_read_sample_now(*dev,now,true)",
            "Missing assigned devices are retried only while idle",
            "#define KP3S_MPU6050_POLL_IDLE_MS 20UL",
            "kp3s_mpu6050_role_for_address",
            "kp3s_mpu6050_set_role",
            "kp3s_mpu6050_bed_temp_offset_c",
            "kp3s_mpu6050_bed_level_zero_valid",
            "const float alpha=tau_s/(tau_s+dt);",
            "dev.gyro_bias_valid",
            "dev.stable_since+500UL",
            "KP3S_MPU_TEMP_BASELINE_SAMPLES = 20",
            "dev.boot_last_good_ms+250UL",
            "KP3S_MPU_BOOT_SAMPLES_REQUIRED = 40",
            "dev.boot_notice_until=now+60000UL",
            "float(dev.data.temperature) / 340.0f + 36.53f",
            "void kp3s_mpu6050_resonance_capture_start(const KP3SMPU6050Role role)",
            "kp3s_mpu6050_resonance_role()",
            "static float kp3s_res_goertzel_power",
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
            "menu_kp3s_display_settings",
            "kp3s_mpu6050_changed",
            "kp3s_mpu6050_wiring_changed",
            "menu_kp3s_mpu6050_settings",
            "menu_kp3s_mpu_devices",
            "menu_kp3s_mpu_diagnostics",
            "menu_kp3s_mpu_role_calibration",
            "kp3s_run_mpu_bus_test",
            "kp3s_run_mpu_detect_test",
            "screen_kp3s_digital_level",
            "screen_kp3s_mpu_zero_calibration",
            "kp3s_open_mpu_zero_calibration",
            "kp3s_mpu6050_set_level_zero_for_role",
            "menu_kp3s_mpu_role_68",
            "menu_kp3s_mpu_role_69",
            "menu_kp3s_mpu_bed_data",
            "menu_kp3s_mpu_toolhead_data",
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
            'SUBMENU_F(kp3s_tr(F("Display"), F("Tela")',
            '&kp3s_display_flipped, kp3s_display_rotation_changed);',
            'EDIT_ITEM_F(bool, kp3s_tr(F("BLTouch On"), F("BLTouch Ativo")',
            'SUBMENU_F(kp3s_tr(F("MPU6050 / IMU"), F("MPU6050 / IMU")',
            'SUBMENU(MSG_ADVANCED_SETTINGS, menu_advanced_settings);',
            'SUBMENU(MSG_RETRACT, menu_config_retract);',
            'EDIT_ITEM(bool, MSG_RUNOUT_SENSOR, &runout.enabled, runout.reset);',
            'EDIT_ITEM(bool, MSG_OUTAGE_RECOVERY, &recovery.enabled, recovery.changed);',
            'ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);',
            'ACTION_ITEM(MSG_LOAD_EEPROM, ui.load_settings);',
            'CONFIRM_ITEM(MSG_RESTORE_DEFAULTS',
            'kp3s_serial_printing() || kp3s_serial_print_paused()',
        ],
        OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_main.cpp": [
            "V1: Language lives inside the dedicated Display submenu.",
        ],
        OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_language.cpp": [
            "BACK_ITEM(MSG_BACK);",
            "ui.goto_screen(menu_kp3s_display_settings);",
        ],
        OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_info.cpp": [
            'STATIC_ITEM_F(F("KP3S V1"), SS_CENTER|SS_INVERT);',
            'STATIC_ITEM_F(F("spidoug"), SS_CENTER);',
        ],
        OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_advanced.cpp": [
            'SUBMENU_F(kp3s_tr(F("Auto Resonance"), F("Resson. Auto")',
            'SUBMENU(MSG_MAX_SPEED, menu_advanced_velocity);',
            'SUBMENU(MSG_ACCELERATION, menu_advanced_acceleration);',
            'SUBMENU(MSG_INPUT_SHAPING, menu_advanced_input_shaping);',
            'SUBMENU(MSG_STEPS_PER_MM, menu_advanced_steps_per_mm);',
        ],
        OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_probe_level.cpp": [
            '#include "../../feature/kp3s_bltouch_runtime.h"',
            'STATIC_ITEM_F(kp3s_tr(F("BLTouch OFF")',
            'if (kp3s_bltouch_runtime_enabled) GCODES_ITEM(MSG_LEVEL_BED',
            'if (kp3s_bltouch_runtime_enabled) SUBMENU(MSG_PROBE_WIZARD',
            'V1 keeps EEPROM actions in Configuration only',
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
            '#define EEPROM_VERSION "V01"',
            "bool kp3s_display_flipped;",
            "bool kp3s_bltouch_enabled;",
            "bool kp3s_mpu6050_enabled;",
            "bool kp3s_mpu6050_swap_lines;",
            "uint8_t kp3s_mpu6050_role_68;",
            "uint8_t kp3s_mpu6050_role_69;",
            "EEPROM_WRITE(kp3s_display_flipped)",
            "EEPROM_WRITE(kp3s_bltouch_runtime_enabled)",
            "EEPROM_WRITE(kp3s_mpu6050_runtime_enabled)",
            "EEPROM_WRITE(kp3s_mpu6050_swap_lines)",
            "EEPROM_WRITE(kp3s_mpu6050_role_68)",
            "EEPROM_WRITE(kp3s_mpu6050_role_69)",
            "EEPROM_WRITE(kp3s_mpu6050_toolhead_temp_offset_c)",
            "EEPROM_WRITE(kp3s_mpu6050_bed_temp_offset_c)",
            "EEPROM_WRITE(kp3s_mpu6050_bed_level_zero_valid)",
            "stored_mpu6050_swap_lines",
            "stored_role_68",
            "stored_role_69",
            "kp3s_mpu6050_sanitize_configuration()",
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

    def normalize_cpp_layout(text: str) -> str:
        """Remove layout whitespace outside C/C++ string/char literals.

        Generated Marlin source may differ only in spaces after commas or around
        operators. Validation must not depend on formatter layout, while spaces
        inside user-visible strings remain semantically significant.
        """
        out: list[str] = []
        quote: str | None = None
        escaped = False
        for ch in text:
            if quote is not None:
                out.append(ch)
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == quote:
                    quote = None
                continue
            if ch in ('"', "'"):
                quote = ch
                out.append(ch)
            elif not ch.isspace():
                out.append(ch)
        return "".join(out)

    def has_marker(text: str, marker: str) -> bool:
        if marker in text:
            return True
        return normalize_cpp_layout(marker) in normalize_cpp_layout(text)

    def marker_pos(text: str, marker: str) -> int:
        return normalize_cpp_layout(text).find(normalize_cpp_layout(marker))

    for path, markers in files_and_markers.items():
        if not path.exists():
            raise RuntimeError(f"Required file missing: {path}")
        text = read(path)
        for marker in markers:
            if not has_marker(text, marker):
                raise RuntimeError(f"Validation failed in {path.name}: missing {marker!r}")

    cfg_text = read(OUT / "Marlin" / "Configuration.h")
    if not re.search(r"^[ \t]*#define[ \t]+SDSUPPORT\b", cfg_text, flags=re.M):
        raise RuntimeError("SDSUPPORT is required for V1 serial spooling and local printing.")
    for index, code in enumerate(V1_LCD_LANGUAGES, start=1):
        suffix = f"_{index}" if index > 1 else ""
        language_marker = f"#define LCD_LANGUAGE{suffix} {code}"
        if language_marker not in cfg_text:
            raise RuntimeError(f"Missing language configuration: {language_marker}")
    if V1_LCD_LANGUAGES[0] != V1_DEFAULT_LCD_LANGUAGE or V1_DEFAULT_LCD_LANGUAGE != "en":
        raise RuntimeError("English must remain the primary/default V1 LCD language.")
    language_dir = OUT / "Marlin" / "src" / "lcd" / "language"
    for code in V1_LCD_LANGUAGES:
        language_file = language_dir / f"language_{code}.h"
        if not language_file.exists():
            raise RuntimeError(f"Required Marlin language file missing: {language_file.name}")

    # Prove that every V1 supplement made it into the final generated language
    # namespace with the exact intended text. This catches later patch-order
    # regressions that could otherwise reintroduce an English fallback.
    for code, translations in V1_NATIVE_LANGUAGE_SUPPLEMENTS.items():
        language_text = read(language_dir / f"language_{code}.h")
        namespace = f"namespace LanguageNarrow_{code} {{"
        wide_namespace = f"namespace LanguageWide_{code} {{"
        start = language_text.find(namespace)
        wide = language_text.find(wide_namespace, start + len(namespace))
        close = language_text.rfind("}", start, wide)
        if start < 0 or wide < 0 or close < 0:
            raise RuntimeError(f"Generated {code} language namespace is malformed.")
        narrow = language_text[start:close]
        for key, value in translations.items():
            expected = f'_UxGT("{value}")'
            rx = re.compile(rf"^[ \t]*LSTR[ \t]+{re.escape(key)}[ \t]*=[^\r\n]*{re.escape(expected)}[^\r\n]*$", flags=re.M)
            if len(rx.findall(narrow)) != 1:
                raise RuntimeError(f"Generated {code}/{key} translation is missing or incorrect: {value!r}")

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
    mpu_header_text = read(OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050.h")
    mpu_impl_text = read(OUT / "Marlin" / "src" / "feature" / "kp3s_mpu6050_impl.h")
    if "WRITE(KP3S_MPU6050_SDA_PIN, HIGH)" in mpu_impl_text or "WRITE(KP3S_MPU6050_SCL_PIN, HIGH)" in mpu_impl_text:
        raise RuntimeError("Software I2C must remain open-drain.")

    cfg_text = read(OUT / "Marlin" / "Configuration.h")
    if '#define CUSTOM_MACHINE_NAME "KINGROON KP3S V1"' not in cfg_text:
        raise RuntimeError("V1 machine identity must be exactly KINGROON KP3S V1.")
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
        "ADVANCED_OK", "EDITABLE_DISPLAY_TIMEOUT", "MEDIA_MENU_AT_TOP", "HOTEND_IDLE_TIMEOUT",
    ):
        if not re.search(rf"^[ \t]*#define[ \t]+{runtime_feature}\b", adv_text, flags=re.M):
            raise RuntimeError(f"V1 runtime feature is missing: {runtime_feature}")

    # Validate the V1 safety rules against the effective KP3S architecture, not
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

    # The V1 340C target is valid only as a coherent high-temperature profile.
    thermal_profile = {
        "TEMP_SENSOR_0": V1_HOTEND_SENSOR,
        "HEATER_0_MAXTEMP": V1_HOTEND_MAXTEMP_C,
        "HOTEND_OVERSHOOT": V1_HOTEND_OVERSHOOT_C,
    }
    for name, value in thermal_profile.items():
        if not re.search(rf"^[ \t]*#define[ \t]+{name}[ \t]+{value}(?:[ \t/]|$)", cfg_text, flags=re.M):
            raise RuntimeError(f"V1 high-temperature hotend profile is invalid: {name} must be {value}.")
    if V1_HOTEND_MAXTEMP_C - V1_HOTEND_OVERSHOOT_C != V1_HOTEND_TARGET_MAX_C:
        raise RuntimeError("V1 high-temperature constants must produce an exact 340C selectable target.")

    thermistor_61 = OUT / "Marlin" / "src" / "module" / "thermistor" / "thermistor_61.h"
    if not thermistor_61.exists():
        raise RuntimeError("Marlin thermistor table 61 is required for the V1 340C hotend profile.")
    thermistor_61_text = read(thermistor_61)
    if "350" not in thermistor_61_text or "100 kOhm" not in thermistor_61_text or "3950 K" not in thermistor_61_text:
        raise RuntimeError("Unexpected Marlin thermistor table 61; refusing the V1 high-temperature profile.")

    for name, value in (
        ("HOTEND_IDLE_TIMEOUT_SEC", V1_HOTEND_IDLE_TIMEOUT_SEC),
        ("HOTEND_IDLE_MIN_TRIGGER", 180),
        ("HOTEND_IDLE_NOZZLE_TARGET", 0),
        ("HOTEND_IDLE_BED_TARGET", 0),
    ):
        if not re.search(rf"^[ \t]*#define[ \t]+{name}[ \t]+{value}(?:[ \t/]|$)", adv_text, flags=re.M):
            raise RuntimeError(f"V1 hotend idle protection is invalid: {name} must be {value}.")

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
    if ui_cpp_text.count("if (kp3s_ui_selection_mode || kp3s_ui_edit_mode) break;") < 2:
        raise RuntimeError("UP/DOWN must be silent no-ops on horizontal selection/edit screens.")
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
    # MPU6050 has only two legal AD0 addresses. Do not scan unrelated I2C
    # addresses or perform bus discovery work during a print.
    if "KP3S_I2C_SCAN_FIRST" in mpu_impl_text or "kp3s_mpu_scan_bus" in mpu_impl_text:
        raise RuntimeError("Dual-MPU V1 must probe only 0x68 and 0x69, not scan the whole I2C bus.")
    for fixed_probe in ("kp3s_i2c_probe_ack(0x68)", "kp3s_i2c_probe_ack(0x69)"):
        if fixed_probe not in mpu_impl_text:
            raise RuntimeError(f"Dual-MPU detection is missing legal address probe: {fixed_probe}")
    config_menu_start = menu_text.rfind("void menu_configuration() {")
    if config_menu_start < 0:
        raise RuntimeError("Configuration menu function was not found after V1 patching.")
    config_menu_body = menu_text[config_menu_start:]

    bltouch_toggle = 'EDIT_ITEM_F(bool, kp3s_tr(F("BLTouch On"), F("BLTouch Ativo")'
    bltouch_tools = 'SUBMENU(MSG_BLTOUCH, menu_bltouch);'
    bltouch_guard = 'if (kp3s_bltouch_runtime_enabled && !kp3s_runtime_machine_busy())'
    toggle_pos = marker_pos(config_menu_body, bltouch_toggle)
    tools_pos = marker_pos(config_menu_body, bltouch_tools)
    guard_pos = marker_pos(config_menu_body, bltouch_guard)
    if min(toggle_pos, guard_pos, tools_pos) < 0 or not (toggle_pos < guard_pos < tools_pos):
        raise RuntimeError(
            "Configuration must keep the runtime BLTouch toggle, runtime guard, and native BLTouch tools together."
        )
    if not has_marker(config_menu_body, 'SUBMENU_F(kp3s_tr(F("Display"), F("Tela")'):
        raise RuntimeError("Configuration must expose the dedicated V1 Display submenu.")
    display_menu_start = menu_text.find("void menu_kp3s_display_settings() {")
    display_menu_end = menu_text.find("#if ENABLED(KP3S_MPU6050)", display_menu_start)
    if display_menu_start < 0 or display_menu_end < 0:
        raise RuntimeError("V1 Display submenu function was not found after patching.")
    display_menu_body = menu_text[display_menu_start:display_menu_end]
    for marker in (
        'EDIT_ITEM_FAST(uint8, MSG_BRIGHTNESS',
        'EDIT_ITEM_FAST(uint8, MSG_CONTRAST',
        'EDIT_ITEM(uint8, MSG_SCREEN_TIMEOUT',
        '&kp3s_display_flipped, kp3s_display_rotation_changed);',
        'menu_language);',
    ):
        if not has_marker(display_menu_body, marker):
            raise RuntimeError(f"V1 Display submenu is incomplete: {marker}")
    if not has_marker(config_menu_body, 'SUBMENU_F(kp3s_tr(F("MPU6050 / IMU"), F("MPU6050 / IMU")'):
        raise RuntimeError("Configuration must expose the V1-specific MPU6050 / IMU submenu.")

    config_order = (
        'SUBMENU(MSG_ADVANCED_SETTINGS, menu_advanced_settings);',
        'EDIT_ITEM_F(bool, kp3s_tr(F("BLTouch On")',
        'SUBMENU_F(kp3s_tr(F("Display"), F("Tela")',
        'SUBMENU(MSG_RETRACT, menu_config_retract);',
        'EDIT_ITEM(bool, MSG_RUNOUT_SENSOR, &runout.enabled, runout.reset);',
        'SUBMENU_F(kp3s_tr(F("MPU6050 / IMU")',
        'EDIT_ITEM(bool, MSG_OUTAGE_RECOVERY, &recovery.enabled, recovery.changed);',
        'ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);',
        'CONFIRM_ITEM(MSG_RESTORE_DEFAULTS',
    )
    config_positions = [marker_pos(config_menu_body, marker) for marker in config_order]
    if any(pos < 0 for pos in config_positions) or config_positions != sorted(config_positions):
        raise RuntimeError("Configuration menu order is no longer the V1 native hierarchy.")
    if "About KP3S V1" in config_menu_body or "screen_kp3s_about" in menu_text:
        raise RuntimeError("Firmware identity must use Marlin's native Info menu, not duplicate Configuration entries.")
    main_menu_text = read(OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_main.cpp")
    if "SUBMENU(LANGUAGE, menu_language);" in main_menu_text:
        raise RuntimeError("Language must not be duplicated in the V1 main menu.")
    language_menu_text = read(OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_language.cpp")
    if "BACK_ITEM(MSG_BACK);" not in language_menu_text or "ui.goto_screen(menu_kp3s_display_settings);" not in language_menu_text:
        raise RuntimeError("Language selection must return coherently to the Display submenu.")
    info_menu_text = read(OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_info.cpp")
    if not has_marker(info_menu_text, 'STATIC_ITEM_F(F("KP3S V1"), SS_CENTER|SS_INVERT);') \
       or not has_marker(info_menu_text, 'STATIC_ITEM_F(F("spidoug"), SS_CENTER);'):
        raise RuntimeError("Native Printer Info must carry the KP3S V1 identity and author.")
    if not has_marker(config_menu_body, '[]{ ui.reset_settings(); ui.goto_previous_screen(); }'):
        raise RuntimeError("Restore Defaults confirmation must leave the selection screen cleanly.")
    if not has_marker(menu_text, "kp3s_mpu6050_calibration_changed();\n    ui.completion_feedback();\n    ui.goto_previous_screen();"):
        raise RuntimeError("Clear Level Zero must confirm, save, give feedback and return to calibration.")
    if not has_marker(menu_text, 'STATIC_ITEM_F(kp3s_tr(F("IMU LOCKED")'):
        raise RuntimeError("Per-role IMU pages must lock if a print or motion starts while already inside the menu.")
    if menu_text.count("if (kp3s_runtime_machine_busy()) return ui.goto_previous_screen();") < 4:
        raise RuntimeError("Live IMU screens must exit automatically when a print or normal motion starts.")
    if "axis == X_AXIS ? KP3SMPU6050Role::TOOLHEAD : KP3SMPU6050Role::BED" not in menu_text:
        raise RuntimeError("V1 resonance tuning must use TOOLHEAD for X and BED for Y.")
    advanced_menu_text = read(OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_advanced.cpp")
    if not has_marker(advanced_menu_text, 'SUBMENU_F(kp3s_tr(F("Auto Resonance"), F("Resson. Auto")'):
        raise RuntimeError("Resonance autotune must live inside native Input Shaping.")
    probe_menu_text = read(OUT / "Marlin" / "src" / "lcd" / "menu" / "menu_probe_level.cpp")
    if "ACTION_ITEM(MSG_STORE_EEPROM, ui.store_settings);" in probe_menu_text:
        raise RuntimeError("Probe / Level must not duplicate the EEPROM Save action from Configuration.")
    if not has_marker(probe_menu_text, 'if (kp3s_bltouch_runtime_enabled) GCODES_ITEM(MSG_LEVEL_BED'):
        raise RuntimeError("Probe / Level must hide automatic leveling while runtime BLTouch is disabled.")
    for forbidden_menu_marker in (
        "menu_kp3s_" + "v1_settings", "menu_kp3s_" + "motion_tuning",
        "menu_kp3s_" + "sensor_settings", "menu_kp3s_" + "recovery_settings", "menu_kp3s_" + "storage_settings",
        'F("KP3S ' + 'Setup")', 'F("Motion / ' + 'Tuning")', 'F("Sensors / ' + 'IMU")', 'F("BLTouch / ' + 'Leveling")',
        'F("Startup ' + 'Level")'
    ):
        if forbidden_menu_marker in menu_text:
            raise RuntimeError(f"V1 menu audit found a duplicate menu path: {forbidden_menu_marker}")
    for marker in (
        'kp3s_tr(F("MPU6050 On"),F("MPU6050 Ativo")',
        'kp3s_tr(F("Swap SDA/SCL"),F("Trocar SDA/SCL")',
        'kp3s_tr(F("Detect Devices"),F("Detectar disp.")',
        'kp3s_tr(F("Test I2C Bus"),F("Testar bus I2C")',
        'kp3s_tr(F("Devices/Wiring"),F("Disp./Fiação")',
        'kp3s_tr(F("Level"),F("Nível")',
        'kp3s_tr(F("Vibration"),F("Vibração")',
        'kp3s_tr(F("Temperature"),F("Temperatura")',
        'kp3s_tr(F("Calibration"),F("Calibração")',
        'kp3s_tr(F("Toolhead IMU"),F("IMU Cabeçote")',
        'kp3s_tr(F("Bed IMU"),F("IMU Mesa")',
        'menu_kp3s_mpu_role_68', 'menu_kp3s_mpu_role_69',
        'screen_kp3s_mpu_zero_calibration',
        'kp3s_tr(F("Auto Tune X"),F("Autoajuste X")',
        'kp3s_tr(F("Auto Tune Y"),F("Autoajuste Y")',
    ):
        if not has_marker(menu_text, marker):
            raise RuntimeError(f"MPU6050 dual-role diagnostics menu is incomplete: {marker}")
    mpu_line_cap = menu_text.find("static constexpr uint8_t KP3S_MPU_UI_LINE_CAP = 24;")
    first_mpu_line_use = menu_text.find("char xline[KP3S_MPU_UI_LINE_CAP]")
    if mpu_line_cap < 0 or first_mpu_line_use < 0 or mpu_line_cap > first_mpu_line_use:
        raise RuntimeError("MPU UI line capacity must be declared before the first menu buffer that uses it.")
    if "MarlinSettings::save();" not in menu_text:
        raise RuntimeError("SDA/SCL orientation must auto-save to EEPROM when changed from the LCD.")
    for marker in (
        "kp3s_mpu_configure_and_verify", "kp3s_mpu_read_sample_now",
        "kp3s_mpu_write_reg(dev,0x6B,0x80,true)", "kp3s_mpu_delay_ms(100)",
        "static bool kp3s_i2c_read_byte(uint8_t &v", "kp3s_mpu_read_regs_mode",
        "stop_before_read", "if (!kp3s_i2c_read_byte(dst[i]",
        "kp3s_mpu_update_derived", "const float alpha=tau_s/(tau_s+dt);",
        "dev.gyro_bias_valid", "dev.stable_since+500UL",
        "KP3S_MPU_TEMP_BASELINE_SAMPLES = 20", "dev.boot_last_good_ms+250UL",
        "if (kp3s_mpu_background_blocked(now)) return;",
        "kp3s_mpu_read_sample_now(*dev,now,true)",
        "Missing assigned devices are retried only while idle",
        "kp3s_res_restore_pending", "kp3s_mpu_restore_resonance_config_idle",
        "if (kp3s_mpu_background_blocked(millis())) return false;",
        "kp3s_mpu6050_set_level_zero_for_role", "kp3s_mpu6050_level_raw_for_role",
        "kp3s_mpu6050_startup_progress_pct_for_role", "KP3S_MPU_BOOT_SAMPLES_REQUIRED = 40",
        "kp3s_mpu6050_bed_temp_offset_c", "kp3s_mpu6050_role_68", "kp3s_mpu6050_role_69"
    ):
        if marker not in mpu_impl_text:
            raise RuntimeError(f"MPU dual-role/print-isolation validation missing: {marker}")
    for forbidden_mpu_marker in (
        "kp3s_mpu6050_print_" + "telemetry", "KP3S_MPU6050_POLL_" + "PRINT_MS",
        "KP3S_MPU6050_MIN_" + "PLANNER_MOVES", "kp3s_mpu_" + "planner_budget_ok",
        "planner.movesplanned()"
    ):
        if forbidden_mpu_marker in mpu_impl_text or forbidden_mpu_marker in mpu_header_text or forbidden_mpu_marker in menu_text:
            raise RuntimeError(f"V1 MPU path reintroduced print-time/background coupling: {forbidden_mpu_marker}")
    bltouch_runtime_text = read(OUT / "Marlin" / "src" / "feature" / "kp3s_bltouch_runtime.h")
    if "kp3s_bltouch_runtime_apply(/*stow_when_disabling=*/true);" not in menu_text:
        raise RuntimeError("The BLTouch display callback must apply the runtime probe state.")
    if "if (kp3s_bltouch_runtime_enabled)" not in bltouch_runtime_text \
       or "bltouch.init(/*set_voltage=*/true);" not in bltouch_runtime_text:
        raise RuntimeError("Enabling BLTouch from the display must initialize the probe through the runtime driver.")
    if "set_bed_leveling_enabled(false);" not in bltouch_runtime_text \
       or "if (stow_when_disabling) bltouch._stow();" not in bltouch_runtime_text:
        raise RuntimeError("Disabling BLTouch must disable leveling and safely stow the probe.")
    if 'EDIT_ITEM(bool, MSG_RUNOUT_SENSOR, &runout.enabled, runout.reset);' not in menu_text:
        raise RuntimeError("Native filament runout control must remain in Configuration.")
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
    if "kp3s_status_vibration_line" in status_text or "kp3s_mpu6050_motion_for_role" in status_text:
        raise RuntimeError("V1 status must not request MPU motion data during printing.")
    if "kp3s_status_startup_level_line" not in status_text or "kp3s_mpu6050_startup_notice" not in status_text:
        raise RuntimeError("Status screen must expose the automatic startup level assessment.")
    if "constexpr KP3SMPU6050Role role = KP3SMPU6050Role::BED;" not in status_text:
        raise RuntimeError("V1 startup LEVEL status must represent only the bed-assigned MPU.")
    forbidden_bottom_row = "lcd_moveto(0, " + "47);"
    if forbidden_bottom_row in status_text or "lcd_moveto(0, 44);" not in status_text:
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
        "lcd_put_u8str_max(kp3s_marquee_advance", "kp3s_edit_label", "kp3s_visible_chars",
        "utf8_byte_pos_by_char_num_P(FTOP(text), offset_chars)", "right ? 0xFD : 0xFC"
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

    print("[OK] V1 validated: safety rules + native menu hierarchy + robust serial/UI + isolated IMU tuning")



def verify_release_tree():
    """Audit the maintained source tree before download, generation, or build."""
    root = BASE.parent
    version_file = root / "VERSION"
    if not version_file.exists() or version_file.read_text(encoding="utf-8").strip() != "V1":
        raise RuntimeError("VERSION must contain exactly V1.")

    # The maintained V1 package is intentionally flat and release-only.
    # Development-only, historical, test-suite and policy-folder names are not allowed.
    forbidden_dir_names = {
        "te" + "st", "te" + "sts", "test" + "ing",
        "con" + "tract", "con" + "tracts",
        "leg" + "acy", "depre" + "cated", "reti" + "red",
        "o" + "ld", "back" + "up", "back" + "ups",
    }
    bad_dirs = sorted(
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_dir() and path.name.lower() in forbidden_dir_names
    )
    if bad_dirs:
        raise RuntimeError("V1 package contains forbidden development/history folders:\n  " + "\n  ".join(bad_dirs))

    forbidden = (
        "V1" + ".1",
        "1" + ".1.0",
        "V" + "11",
        "firmware" + "\\current",
        "Print " + "Telemetry",
        "Telemetria " + "Print",
    )
    skip_parts = {".git", ".build_env", ".pio", "cache", "__pycache__", "firmware_output", "marlin-2.1.3-b3"}
    text_suffixes = {".py", ".md", ".txt", ".bat", ".json", ".ini", ".h", ".hpp", ".c", ".cpp", ".svg", ".yml", ".yaml", ""}
    offenders = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in skip_parts for part in path.parts):
            continue
        if path.suffix.lower() not in text_suffixes and path.name != "VERSION":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for token in forbidden:
            if token.lower() in text.lower():
                offenders.append(f"{path.relative_to(root)}: {token}")
    if offenders:
        raise RuntimeError("V1 source-tree audit failed:\n  " + "\n  ".join(offenders))

    # Reject historical implementation labels in maintained project text.
    history_pattern = re.compile(r"\b(?:legac[y]|retir(?:ed|ement)|deprecat(?:ed|ion))\b", re.I)
    history_hits = []
    for path in root.rglob("*"):
        if not path.is_file() or any(part in skip_parts for part in path.parts) or path.name == "LICENSE":
            continue
        if path.suffix.lower() not in text_suffixes and path.name != "VERSION":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if history_pattern.search(text):
            history_hits.append(str(path.relative_to(root)))
    if history_hits:
        raise RuntimeError("V1 package contains historical implementation labels:\n  " + "\n  ".join(sorted(history_hits)))

    build_text = Path(__file__).read_text(encoding="utf-8")
    build_bat_text = (BASE / "BUILD_FIRMWARE.bat").read_text(encoding="utf-8")

    # Keep the build-system identity singular and exact. Firmware V1 identity
    # remains separate and is intentionally preserved in firmware metadata/docs.
    if BUILD_SYSTEM_NAME != "KINGROON KP3S MARLIN FIRMWARE":
        raise RuntimeError("Build-system name must remain exactly KINGROON KP3S MARLIN FIRMWARE.")
    for required_line in (f"title {BUILD_SYSTEM_NAME}", f"echo  {BUILD_SYSTEM_NAME}"):
        if required_line not in build_bat_text:
            raise RuntimeError(f"BUILD_FIRMWARE.bat is missing exact build-system identity: {required_line}")
    if V1_LCD_LANGUAGES != ("en", "pt_br", "es", "fr", "de"):
        raise RuntimeError("V1 LCD language order must remain English, Portuguese (Brazil), Spanish, French, German.")
    if V1_DEFAULT_LCD_LANGUAGE != "en" or V1_LCD_LANGUAGES[0] != "en":
        raise RuntimeError("English must remain the primary/default V1 LCD language.")

    if (V1_HOTEND_SENSOR, V1_HOTEND_TARGET_MAX_C, V1_HOTEND_MAXTEMP_C, V1_HOTEND_OVERSHOOT_C) != (61, 340, 350, 10):
        raise RuntimeError("V1 high-temperature profile must remain sensor 61, target 340C, MAXTEMP 350C, overshoot 10C.")
    if V1_HOTEND_MAXTEMP_C - V1_HOTEND_OVERSHOOT_C != V1_HOTEND_TARGET_MAX_C:
        raise RuntimeError("V1 high-temperature constants no longer produce a 340C selectable target.")
    if V1_HOTEND_IDLE_TIMEOUT_SEC != 600:
        raise RuntimeError("V1 hotend idle protection must remain 10 minutes (600 seconds).")

    # Every V1-specific translation is authored as a five-language kp3s_tr()
    # tuple in the same canonical order. Keep these labels within the Nokia
    # 14-column viewport so every language remains readable even without
    # relying on marquee behavior. Native Marlin labels use the pinned upstream
    # language files plus the V1 supplement above for any visible fallback gaps.
    translation_pattern = re.compile(
        r'kp3s_tr\(\s*F\("([^"\n]*)"\)\s*,\s*F\("([^"\n]*)"\)\s*,\s*'
        r'F\("([^"\n]*)"\)\s*,\s*F\("([^"\n]*)"\)\s*,\s*F\("([^"\n]*)"\)\s*\)'
    )
    translation_rows = translation_pattern.findall(build_text)
    if len(translation_rows) < 50:
        raise RuntimeError("V1 translation audit found too few complete five-language strings.")
    for row in translation_rows:
        if any(not label for label in row):
            raise RuntimeError(f"V1 translation contains an empty language entry: {row!r}")
        for code, label in zip(V1_LCD_LANGUAGES, row):
            if len(label) > 14:
                raise RuntimeError(f"V1 {code} label exceeds Nokia 14-column width: {label!r} ({len(label)})")

    required_language_menu = 'SUBMENU_F(kp3s_tr(F("Language"),F("Idioma"),F("Idioma"),F("Langue"),F("Sprache")), menu_language);'
    if required_language_menu not in build_text:
        raise RuntimeError("V1 Display language selector must be localized in all five languages.")

    # Display rotation validation is intentionally structural, not tied to UI wording.
    # This prevents a legitimate translation cleanup from making verify_project()
    # reject a correctly generated menu simply because its visible label changed.
    rotation_binding = '&kp3s_display_flipped, kp3s_display_rotation_changed);'
    if rotation_binding not in build_text:
        raise RuntimeError("V1 display rotation control is missing its runtime binding/callback.")
    for stale_rotation_label in ("Invert LCD " + "180", "Inverter " + "LCD"):
        if stale_rotation_label in build_text:
            raise RuntimeError(f"V1 generator still contains obsolete display-rotation validation text: {stale_rotation_label!r}")

    required_native_keys = (
        "LANGUAGE",
        "MSG_BRIGHTNESS", "MSG_BRIGHTNESS_OFF", "MSG_SCREEN_TIMEOUT",
        "MSG_LCD_ON", "MSG_LCD_OFF", "MSG_TIMEOUT", "MSG_TEMPERATURE",
        "MSG_INPUT_SHAPING", "MSG_SHAPING_ENABLE_N", "MSG_SHAPING_DISABLE_N",
        "MSG_SHAPING_FREQ_N", "MSG_SHAPING_ZETA_N",
        "MSG_HOTEND_IDLE_TIMEOUT", "MSG_HOTEND_IDLE_DISABLE",
        "MSG_HOTEND_IDLE_NOZZLE_TARGET", "MSG_HOTEND_IDLE_BED_TARGET",
        "MSG_PROBE_WIZARD", "MSG_PROBE_WIZARD_PROBING", "MSG_PROBE_WIZARD_MOVING",
        "MSG_INFO_BUILD",
        "MSG_BED_TRAMMING_MANUAL", "MSG_BED_TRAMMING_RAISE",
        "MSG_BED_TRAMMING_IN_RANGE", "MSG_BED_TRAMMING_GOOD_POINTS",
        "MSG_BED_TRAMMING_LAST_Z", "MSG_BUTTON_DONE", "MSG_BUTTON_SKIP",
        "MSG_PID_AUTOTUNE", "MSG_PID_AUTOTUNE_E", "MSG_PID_CYCLE",
        "MSG_PID_AUTOTUNE_DONE", "MSG_PID_AUTOTUNE_FAILED",
        "MSG_BAD_HEATER_ID", "MSG_TEMP_TOO_HIGH", "MSG_TEMP_TOO_LOW",
        "MSG_PID_BAD_HEATER_ID", "MSG_PID_TEMP_TOO_HIGH", "MSG_PID_TIMEOUT",
        "MSG_INFO_MENU", "MSG_INFO_PRINTER_MENU", "MSG_INFO_BOARD_MENU",
        "MSG_INFO_THERMISTOR_MENU", "MSG_INFO_STATS_MENU",
        "MSG_INFO_PRINT_COUNT", "MSG_INFO_COMPLETED_PRINTS", "MSG_INFO_PRINT_TIME",
        "MSG_INFO_PRINT_LONGEST", "MSG_INFO_PRINT_FILAMENT",
        "MSG_INFO_MIN_TEMP", "MSG_INFO_MAX_TEMP", "MSG_INFO_RUNAWAY_ON",
        "MSG_INFO_RUNAWAY_OFF", "MSG_INFO_BAUDRATE", "MSG_INFO_PROTOCOL",
        "MSG_INFO_PSU", "MSG_INFO_EXTRUDERS",
        "MSG_MEDIA_SORT",
        "MSG_MEDIA_INSERTED_SD", "MSG_MEDIA_INSERTED_USB",
        "MSG_MEDIA_REMOVED_SD", "MSG_MEDIA_REMOVED_USB",
        "MSG_MEDIA_INIT_FAIL", "MSG_MEDIA_INIT_FAIL_SD", "MSG_MEDIA_INIT_FAIL_USB",
        "MSG_MEDIA_READ_ERROR", "MSG_MEDIA_UPDATE",
        "MSG_USB_FD_WAITING_FOR_MEDIA", "MSG_USB_FD_MEDIA_REMOVED",
        "MSG_ATTACH_MEDIA", "MSG_ATTACH_SD", "MSG_ATTACH_USB",
        "MSG_RELEASE_MEDIA", "MSG_RELEASE_SD", "MSG_RELEASE_USB",
        "MSG_CHANGE_MEDIA", "MSG_CHANGE_SD", "MSG_CHANGE_USB",
        "MSG_RUN_AUTOFILES", "MSG_RUN_AUTOFILES_SD", "MSG_RUN_AUTOFILES_USB",
        "MSG_MEDIA_MENU", "MSG_MEDIA_MENU_SD", "MSG_MEDIA_MENU_USB", "MSG_NO_MEDIA",
        "MSG_TRAMMING_WIZARD", "MSG_SELECT_ORIGIN", "MSG_LAST_VALUE_SP",
        "MSG_HOMING", "MSG_HOME_ALL", "MSG_HOME_FIRST",
        "MSG_RUNOUT_SENSOR", "MSG_OUTAGE_RECOVERY",
        "MSG_ADVANCE_K", "MSG_AUTORETRACT", "MSG_FILAMENT_LOAD", "MSG_FILAMENT_UNLOAD",
    )
    required_native_groups = {code: required_native_keys for code in ("pt_br", "es", "fr", "de")}
    for code, keys in required_native_groups.items():
        translations = V1_NATIVE_LANGUAGE_SUPPLEMENTS.get(code, {})
        missing = [key for key in keys if not translations.get(key)]
        if missing:
            raise RuntimeError(f"V1 native language supplement {code} is incomplete: {', '.join(missing)}")

    native_keysets = {code: set(values) for code, values in V1_NATIVE_LANGUAGE_SUPPLEMENTS.items()}
    reference_keys = native_keysets["pt_br"]
    for code, keys in native_keysets.items():
        if keys != reference_keys:
            missing = sorted(reference_keys - keys)
            extra = sorted(keys - reference_keys)
            raise RuntimeError(f"V1 native translation key mismatch for {code}; missing={missing}, extra={extra}")

    # Common English UI prose is forbidden inside non-English V1 supplements.
    forbidden_fallback_words = (
        "input shaping", "screen timeout", "brightness", "probe wizard",
        "print count", "completed prints", "hotend idle timeout",
        "disable timeout", "nozzle idle", "bed idle", "build date",
        "release sd", "release usb", "select from", "attach sd", "attach usb",
        "run autofiles", "no media", "tramming wizard", "select origin",
    )
    for code, translations in V1_NATIVE_LANGUAGE_SUPPLEMENTS.items():
        for key, value in translations.items():
            lower = value.casefold()
            if any(word in lower for word in forbidden_fallback_words):
                raise RuntimeError(f"V1 {code}/{key} still contains English fallback prose: {value!r}")

    # All KP3S-authored LCD prose must pass through kp3s_tr(). Technical tokens
    # (axis letters, units, addresses, product names) may remain language-neutral.
    for forbidden_raw_lcd in (
        'STATIC_ITEM_F(F("SDA ' + 'STUCK")', 'STATIC_ITEM_F(F("SCL ' + 'STUCK")',
        'STATIC_ITEM_F(F("NO I2C ' + 'ACK")', 'status=F("HOM' + 'ING...")',
        'status=F("HOME ' + 'FAILED")', 'status=F("SAFE Z ' + 'FAILED")',
        'status=F("AXIS TOO ' + 'CLOSE")', 'status=F("CAPTURE ' + 'FAILED")',
        'status=F("SAVE ' + 'FAILED")', 'PSTR("LIVE / ' + 'MOVING")',
        'PSTR("ADJUST ' + 'BASE")', 'SUBMENU_F(F("MPU 0x68 ' + 'Role")',
        'SUBMENU_F(F("MPU 0x69 ' + 'Role")',
        'PSTR("MAX:' + '")', 'PSTR("OFF:' + '")', 'PSTR("FREQ:' + '")',
        'PSTR("SAMP:' + '")', 'PSTR("CONF:' + '")',
    ):
        if forbidden_raw_lcd in build_text:
            raise RuntimeError(f"V1 contains untranslated KP3S LCD text: {forbidden_raw_lcd}")

    # Guard the generated-project validator itself. Variables ending in `_text`
    # are generated-file snapshots and must always be bound locally before use.
    # This catches accidental removal of a `read(...)` line during future UI
    # refactors before any download or project generation starts.
    module_ast = ast.parse(build_text, filename=str(Path(__file__)))
    verify_ast = next(
        (node for node in module_ast.body if isinstance(node, ast.FunctionDef) and node.name == "verify_project"),
        None,
    )
    if verify_ast is None:
        raise RuntimeError("V1 source-tree audit could not locate verify_project().")
    text_loads = {
        node.id for node in ast.walk(verify_ast)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load) and node.id.endswith("_text")
    }
    local_bindings = {
        node.id for node in ast.walk(verify_ast)
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param))
    }
    missing_text_bindings = sorted(text_loads - local_bindings)
    if missing_text_bindings:
        raise RuntimeError(
            "V1 validator reads generated text before binding it locally: "
            + ", ".join(missing_text_bindings)
        )

    # Custom menu macro validation must use has_marker()/marker_pos() so harmless
    # formatter whitespace cannot break a build after generation has succeeded.
    fragile_macro_checks = []
    for node in ast.walk(verify_ast):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1 or not isinstance(node.ops[0], ast.NotIn):
            continue
        if not isinstance(node.left, ast.Constant) or not isinstance(node.left.value, str):
            continue
        marker = node.left.value
        if any(macro in marker for macro in ("EDIT_ITEM_F(", "SUBMENU_F(", "CONFIRM_ITEM(", "STATIC_ITEM_F(")):
            fragile_macro_checks.append((node.lineno, marker[:80]))
    if fragile_macro_checks:
        details = "; ".join(f"line {line}: {marker!r}" for line, marker in fragile_macro_checks)
        raise RuntimeError(
            "V1 validator contains whitespace-sensitive custom menu checks; use has_marker()/marker_pos(): " + details
        )

    for forbidden_menu_symbol in (
        "menu_kp3s_" + "v1_settings", "menu_kp3s_" + "motion_tuning",
        "menu_kp3s_" + "sensor_settings", "menu_kp3s_" + "recovery_settings", "menu_kp3s_" + "storage_settings",
        'F("KP3S ' + 'Setup")', 'F("Motion / ' + 'Tuning")', 'F("Sensors / ' + 'IMU")', 'F("BLTouch / ' + 'Leveling")',
    ):
        if forbidden_menu_symbol in build_text:
            raise RuntimeError(f"V1 generator contains duplicate menu architecture: {forbidden_menu_symbol}")

    for forbidden_symbol in (
        "kp3s_mpu6050_print_telemetry" + "_enabled",
        "KP3S_MPU6050_POLL_" + "PRINT_MS",
        "KP3S_MPU6050_MIN_" + "PLANNER_MOVES",
        "kp3s_mpu_" + "planner_budget_ok",
    ):
        if forbidden_symbol in build_text:
            raise RuntimeError(f"V1 generator contains forbidden MPU print-coupling symbol: {forbidden_symbol}")

    print("[OK] Source tree audit: single V1 identity, English default, 5-language UI, 340C high-temp hotend profile, clean menu hierarchy, no non-V1 branches or print-time MPU path")

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


def platformio_version(candidate: Path) -> str | None:
    """Return a validated PlatformIO Core version without producing build-log noise."""
    try:
        proc = subprocess.run(
            [str(candidate), "--version"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    match = re.search(r"\bversion\s+([0-9]+(?:\.[0-9]+){2})\b", proc.stdout or "", flags=re.I)
    return match.group(1) if match else None


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
        version = platformio_version(resolved)
        if version == PLATFORMIO_CORE_VERSION:
            return resolved
        if version:
            print(f"[INFO] Ignoring PlatformIO Core {version}; V1 requires {PLATFORMIO_CORE_VERSION}.")
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
    run([py, "-m", "pip", "install", "--disable-pip-version-check", f"platformio=={PLATFORMIO_CORE_VERSION}"])

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
    flash = FLASH_DIR / FLASH_BINARY
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

Use the normal KP3S microSD bootloader procedure: power the printer off, insert
a FAT32 microSD containing Robin_nano.bin in the card root, then power the printer
on again. Direct debug-interface upload is not required for the normal update.
""",
        encoding="utf-8",
    )

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
    for extra in (CACHE, BASE / ".build_env", BASE / "__pycache__"):
        if extra.exists():
            shutil.rmtree(extra)
            print("[OK] removed", extra.name)
    if LOG.exists():
        LOG.unlink()
        print("[OK] removed", LOG.name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=BUILD_SYSTEM_NAME)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true", help="Build after generating the project")
    mode.add_argument("--generate-only", action="store_true", help="Generate and validate without compiling")
    mode.add_argument("--audit-only", action="store_true", help="Audit the maintained V1 source tree without downloading or generating")
    mode.add_argument("--clean", action="store_true", help="Remove generated files and exit")
    parser.add_argument("--auto-toolchain", action="store_true", help="Prepare the pinned isolated build toolchain when needed")
    parser.add_argument("--build-tool", dest="pio", help="Explicit path to the pinned PlatformIO Core executable")
    args = parser.parse_args()
    if args.clean and (args.auto_toolchain or args.pio):
        parser.error("--clean cannot be combined with build-tool options")
    if args.audit_only and (args.auto_toolchain or args.pio):
        parser.error("--audit-only cannot be combined with build-tool options")
    return args


def main(args: argparse.Namespace):
    if args.clean:
        clean()
        return

    verify_release_tree()
    if args.audit_only:
        return

    # Remove any existing firmware artifact before creating the V1 build.
    if args.build and FW_OUT.exists():
        shutil.rmtree(FW_OUT)
        print("[OK] Existing firmware output removed before this build")

    banner(BUILD_SYSTEM_NAME)

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
    args = parse_args()  # Parse before creating any build artifacts.

    # Read-only/help paths and cleanup never create cache or log files.
    if args.clean:
        clean()
        sys.exit(0)
    if args.audit_only:
        verify_release_tree()
        sys.exit(0)

    CACHE.mkdir(exist_ok=True)

    with open(LOG, "w", encoding="utf-8", buffering=1) as log:
        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout = Tee(original_out, log)
        sys.stderr = Tee(original_err, log)
        try:
            main(args)
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
