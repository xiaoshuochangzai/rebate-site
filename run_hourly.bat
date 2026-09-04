@echo off
cd /d %~dp0
set "PY=C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\python.exe"
if not exist "%PY%" set "PY=C:\Users\23058\.workbuddy\binaries\python\versions\3.13.12\python.exe"
"%PY%" build_site.py >> run.log 2>&1
git add -A >> run.log 2>&1
git commit -m "data: auto update" >> run.log 2>&1
git push origin main >> run.log 2>&1
