@echo off
echo Starting linebao monitor (hidden background)...
cd /d E:\Jingdong\rebate-site
start "" "C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\pythonw.exe" -u incremental.py --interval 30
echo.
echo Started. Log: E:\Jingdong\rebate-site\monitor_log.txt
echo (view log: check_log.bat  /  stop: stop_monitor.bat)
pause
