@echo off
echo Starting linebao monitor (hidden background)...
schtasks /run /tn LinebaoMonitor
echo.
echo Started. Log: E:\Jingdong\rebate-site\monitor_log.txt
echo (view log: check_log.bat  /  stop: stop_monitor.bat)
pause
