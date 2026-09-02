@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title KP3S Marlin Firmware V1 - Serial Spool Print
chcp 65001 >nul 2>&1

set "PYEXE="
where py.exe >nul 2>&1 && for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE where python.exe >nul 2>&1 && for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if not defined PYEXE (
  echo Python was not found. Run BUILD_FIRMWARE.bat once to install the V1 toolchain.
  exit /b 1
)

"%PYEXE%" -c "import serial" >nul 2>&1
if errorlevel 1 (
  echo Installing pyserial for the V1 serial print client...
  "%PYEXE%" -m pip install --user "pyserial>=3.5,<4"
  if errorlevel 1 exit /b 1
)

"%PYEXE%" "%~dp0serial_spool.py" %*
exit /b %ERRORLEVEL%
