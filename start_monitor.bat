@echo off
cd /d E:\Jingdong\rebate-site

rem ---- pre-check: is a monitor already running? ----
powershell -NoProfile -Command "$ps = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*incremental.py*' -and $_.Name -like 'python*' }; if ($ps) { Write-Host ('ALREADY RUNNING, PID ' + ($ps.ProcessId -join ', ')); Write-Host 'Old monitor is still alive. Double-click stop_monitor.bat FIRST, then start again.'; exit 9 }"
if "%errorlevel%"=="9" (
  pause
  exit /b 1
)

rem ---- auto-clean stale lock left by force-kill ----
if exist monitor.lock (
  del /f /q monitor.lock
  echo Stale monitor.lock removed.
)

echo Starting linebao monitor (hidden background)...
start "" "C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe" -u incremental.py --interval 30

rem ---- verify the new monitor is really alive after 6s ----
timeout /t 6 /nobreak >nul
powershell -NoProfile -Command "$ps = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*incremental.py*' -and $_.Name -like 'python*' }; if ($ps) { Write-Host ('START OK. Monitor PID ' + ($ps.ProcessId -join ', ')) } else { Write-Host 'START FAILED! New monitor died within 6s. Check monitor_err.txt'; start notepad E:\Jingdong\rebate-site\monitor_err.txt }"
echo.
echo Log: check_log.bat   /   Stop: stop_monitor.bat
pause
