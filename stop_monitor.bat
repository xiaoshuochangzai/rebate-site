@echo off
echo Stopping linebao monitor...
"C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\python.exe" "%~dp0monitor_ctl.py" stop
echo.
pause
