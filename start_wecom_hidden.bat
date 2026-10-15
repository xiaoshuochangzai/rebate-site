@echo off
chcp 65001 >nul
cd /d E:\Jingdong\rebate-site
set PY=C:\Users\23058\.workbuddy\binaries\python\envs\default\Scripts\python.exe

echo 启动隐身推送桌面（企微+WextWorker 搬进隐藏桌面, 热键 Ctrl+Alt+Z 查看）...
"%PY%" wecom_hidden.py start
if errorlevel 1 (
  echo 启动失败，见 wecom_hidden.log
  pause
  exit /b 1
)
echo.
echo 完成！企业微信已隐身。Ctrl+Alt+Z 切换查看。
echo 首次启动请在隐身桌面里打开 3 个线报群的独立会话窗口（右键群-独立窗口）。
pause
