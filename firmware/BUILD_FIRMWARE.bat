@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title KP3S Marlin Firmware V1 - Build Firmware
color 0A
chcp 65001 >nul 2>&1

echo.
echo ============================================================
echo  KINGROON KP3S MARLIN FIRMWARE V1 - CLEAN BUILD
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
"%PYEXE%" "%~dp0build_firmware.py" --build --auto-toolchain
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
