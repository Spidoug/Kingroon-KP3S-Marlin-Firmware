@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title KINGROON KP3S MARLIN FIRMWARE
color 0A
chcp 65001 >nul 2>&1

echo.
echo ============================================================
echo  KINGROON KP3S MARLIN FIRMWARE
echo ============================================================
echo.

set "PYEXE="

rem Use an installed Python 3.10+ when available.
where py.exe >nul 2>&1
if errorlevel 1 goto TRY_PYTHON
for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if defined PYEXE "%PYEXE%" -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if defined PYEXE if not errorlevel 1 goto BUILD
set "PYEXE="

:TRY_PYTHON
where python.exe >nul 2>&1
if errorlevel 1 goto INSTALL_PYTHON
for /f "delims=" %%P in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%P"
if defined PYEXE "%PYEXE%" -c "import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)" >nul 2>&1
if defined PYEXE if not errorlevel 1 goto BUILD
set "PYEXE="

:INSTALL_PYTHON
echo Python 3.10+ was not found. Installing Python 3.12...
where winget.exe >nul 2>&1
if errorlevel 1 goto DIRECT_PYTHON
winget install --id Python.Python.3.12 -e --source winget --scope user --silent --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PYEXE goto BUILD

:DIRECT_PYTHON
set "PYARCH=amd64"
if /I "%PROCESSOR_ARCHITECTURE%"=="ARM64" set "PYARCH=arm64"
if /I "%PROCESSOR_ARCHITEW6432%"=="ARM64" set "PYARCH=arm64"
set "PYSETUP=%TEMP%\python-3.12.10-%PYARCH%-kp3s-v1.exe"
set "PYURL=https://www.python.org/ftp/python/3.12.10/python-3.12.10-%PYARCH%.exe"

where curl.exe >nul 2>&1
if errorlevel 1 goto POWERSHELL_DOWNLOAD
curl.exe -L --fail --retry 4 --retry-all-errors -o "%PYSETUP%" "%PYURL%"
if not errorlevel 1 goto INSTALL_PYTHON_EXE

:POWERSHELL_DOWNLOAD
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%PYURL%' -OutFile '%PYSETUP%'"
if errorlevel 1 goto NO_PYTHON

:INSTALL_PYTHON_EXE
"%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_pip=1 Include_test=0
set "RC=%ERRORLEVEL%"
del /q "%PYSETUP%" >nul 2>&1
if not "%RC%"=="0" goto NO_PYTHON
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PYEXE goto NO_PYTHON

:BUILD
echo Python: "%PYEXE%"
echo.
rem Avoid FOR /F command execution with a quoted Python executable path:
rem CMD removes nested quotes and can corrupt the executable name on Windows.
rem Capture Python output to a temporary file before reading it with SET /P.
set "PROFILE_FILE=%TEMP%\kp3s_profile_%RANDOM%_%RANDOM%.tmp"
"%PYEXE%" -c "from kp3s_project_config import DEFAULT_HOTEND_PROFILE; print(DEFAULT_HOTEND_PROFILE)" > "%PROFILE_FILE%"
if errorlevel 1 (
  del /q "%PROFILE_FILE%" >nul 2>&1
  echo Failed to load internal hotend configuration.
  exit /b 1
)
set "DEFAULT_HOTEND="
set /p "DEFAULT_HOTEND=" < "%PROFILE_FILE%"
del /q "%PROFILE_FILE%" >nul 2>&1
if /I not "%DEFAULT_HOTEND%"=="stock" if /I not "%DEFAULT_HOTEND%"=="high-temp" (
  echo Invalid DEFAULT_HOTEND_PROFILE in kp3s_project_config.py.
  exit /b 2
)
if /I "%~1"=="--show-default-profile" (
  echo Default hotend profile: %DEFAULT_HOTEND%
  exit /b 0
)
set "DEFAULT_CHOICE=1"
if /I "%DEFAULT_HOTEND%"=="high-temp" set "DEFAULT_CHOICE=2"
echo Standard hardware: Nokia 5110 / Samsung UE5000 (not the factory touchscreen)
echo Available hotend profiles:
echo   1 - stock: thermistor table 1, 235 C target, 250 C thermal cutoff
echo   2 - high-temp: thermistor table 61, 340 C target, 350 C thermal cutoff
echo Only choose high-temp if all installed hotend components are independently rated for 350 C.
set "PROFILE_CHOICE="
set /p "PROFILE_CHOICE=Select profile [1/2] (default %DEFAULT_CHOICE%): "
if "%PROFILE_CHOICE%"=="" set "PROFILE_CHOICE=%DEFAULT_CHOICE%"
if "%PROFILE_CHOICE%"=="2" goto HIGH_TEMP_PROFILE
if "%PROFILE_CHOICE%"=="1" goto STOCK_PROFILE
echo Invalid profile choice.
exit /b 2

:HIGH_TEMP_PROFILE
echo WARNING: 340 C target / 350 C thermal cutoff. Do not use with a PTFE-lined hotend.
echo Confirm thermistor, all-metal hotend, heater, wiring and connectors.
set "HOTEND_CONFIRM="
set /p "HOTEND_CONFIRM=Type 340 to confirm upgraded hardware: "
if not "%HOTEND_CONFIRM%"=="340" (
  echo Build cancelled: high-temperature hardware was not confirmed.
  exit /b 2
)
"%PYEXE%" "%~dp0build_firmware.py" --build --auto-toolchain --hotend-profile high-temp --confirm-high-temp-hardware
goto CHECK_BUILD

:STOCK_PROFILE
echo Stock-style profile selected. Verify actual table-1 thermistor and PTFE limits.
"%PYEXE%" "%~dp0build_firmware.py" --build --auto-toolchain --hotend-profile stock

:CHECK_BUILD
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" goto SUCCESS

echo ============================================================
echo  BUILD FAILED
echo ============================================================
echo See BUILD.log in this folder.
echo.
pause
exit /b "%RC%"

:SUCCESS
echo ============================================================
echo  BUILD COMPLETED SUCCESSFULLY
echo ============================================================
echo Firmware ready for the printer:
echo   firmware_output\FLASH_KP3S\Robin_nano.bin
echo.
pause
exit /b 0

:NO_PYTHON
echo.
echo Python could not be installed automatically.
echo Check the Internet connection and run this file again.
echo.
pause
exit /b 1
