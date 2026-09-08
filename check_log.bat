@echo off
cd /d E:\Jingdong\rebate-site
if not exist monitor_log.txt (
  echo No log yet. Start the monitor first: start_monitor.bat
  pause
  exit /b
)
powershell -NoProfile -Command "Get-Content 'E:\Jingdong\rebate-site\monitor_log.txt' -Tail 40"
echo.
echo ==== full log: E:\Jingdong\rebate-site\monitor_log.txt ====
pause
