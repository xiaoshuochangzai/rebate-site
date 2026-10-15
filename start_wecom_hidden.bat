@echo off
cd /d E://Jingdong//rebate-site
set PY=C://Users//23058//.workbuddy//binaries//python//envs//default//Scripts//python.exe
echo [1/2] Starting hidden wecom desktop (WXWork + worker + peek)...
"%PY%" wecom_hidden.py start
if errorlevel 1 goto fail
echo [2/2] Done. Press Ctrl+Alt+Z to peek the hidden desktop (open the 3 group windows there).
echo This window can be closed now.
pause
exit /b 0
:fail
echo START FAILED - see wecom_hidden.log
pause
exit /b 1
