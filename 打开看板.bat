@echo off
cd /d "%~dp0"
if not exist "venv\Scripts\pythonw.exe" (
  echo 还没有安装依赖，请先双击 start.bat
  pause
  exit /b 1
)
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0desktop.py"
