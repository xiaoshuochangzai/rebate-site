@echo off
cd /d E:\Jingdong\rebate-site
set PY=C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\python.exe

rem ---- pre-check via psutil (WMI CommandLine is unreliable, caused double-start) ----
"%PY%" "%~dp0monitor_ctl.py" check | findstr "STATE=RUNNING" >nul
if "%errorlevel%"=="0" (
  echo ALREADY RUNNING. Double-click stop_monitor.bat FIRST, then start again.
  pause
  exit /b 1
)

rem ---- auto-clean stale lock ----
if exist monitor.lock (
  del /f /q monitor.lock
  echo Stale monitor.lock removed.
)

echo Starting linebao monitor (hidden background)...
start "" "C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe" -u incremental.py --interval 15

rem ---- poll up to 30s via psutil (cold-boot may take over 6s) ----
"%PY%" "%~dp0monitor_ctl.py" verify
if errorlevel 1 (
  start notepad "E:\Jingdong\rebate-site\monitor_err.txt"
  pause
  exit /b 1
)

echo.
echo Log: check_log.bat   /   Stop: stop_monitor.bat
pause
