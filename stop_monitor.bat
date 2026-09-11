@echo off
echo Stopping linebao monitor...
powershell -NoProfile -Command "$ps = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*incremental.py*' -and $_.Name -like 'python*' }; if ($ps) { $ps | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('  Killed monitor PID ' + $_.ProcessId) } } else { Write-Host '  No monitor process found.' }"
if exist "E:\Jingdong\rebate-site\monitor.lock" (
  del /f /q "E:\Jingdong\rebate-site\monitor.lock"
  echo   monitor.lock removed.
)
echo.
echo All stopped. Now you can double-click start_monitor.bat.
pause
