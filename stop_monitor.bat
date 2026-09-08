@echo off
echo Stopping linebao monitor...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*incremental.py*' -and $_.Name -like 'python*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('Stopped monitor PID ' + $_.ProcessId) }"
echo Done. (No PID output = monitor was not running)
pause
