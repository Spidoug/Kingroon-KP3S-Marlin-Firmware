@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 kp3s_console.py %*
) else (
  python kp3s_console.py %*
)
exit /b %ERRORLEVEL%
