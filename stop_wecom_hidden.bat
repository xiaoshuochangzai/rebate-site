@echo off
chcp 65001 >nul
cd /d E:\Jingdong\rebate-site
set PY=C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\python.exe
"%PY%" wecom_hidden.py stop
echo 隐身桌面已停止，监控自带派发已自动接管（主桌面企微恢复可见需手动打开企业微信）。
pause
