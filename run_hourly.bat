@echo off
chcp 65001 >nul
cd /d %~dp0
"C:\Users\23058\.workbuddy\binaries\python\versions\3.13.12\python.exe" build_site.py >> run.log 2>&1
