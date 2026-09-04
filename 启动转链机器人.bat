@echo off
setlocal
set "EXE=C:\Program Files\Google\Chrome\Application\chrome.exe"
if not exist "%EXE%" set "EXE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if not exist "%EXE%" set "EXE=C:\Users\23058\AppData\Local\Google\Chrome\Application\chrome.exe"

start "" "%EXE%" --remote-debugging-port=9222 --user-data-dir="%~dp0.jd-bot-profile" --no-first-run --no-default-browser-check --window-size=1400,900 --window-position=60,60 --remote-allow-origins=* "https://union.jd.com/proManager/custompromotion"

echo.
echo ==========================================
echo  Browser launched on debug port 9222.
echo  Please log in to JD Union in the new window.
echo  After login you can minimize it.
echo ==========================================
endlocal
pause
