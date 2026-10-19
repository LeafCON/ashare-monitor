@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY=%LocalAppData%\Programs\Python\Python314\python.exe"
if not exist "%PY%" set "PY=python"

if not exist "venv\Scripts\python.exe" (
  echo 正在创建虚拟环境...
  "%PY%" -m venv venv
  if errorlevel 1 goto :fail
)

if not exist ".env" copy /Y ".env.example" ".env" >nul
if not exist "config.yaml" copy /Y "config.example.yaml" "config.yaml" >nul

echo 正在安装 Python 依赖...
venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if errorlevel 1 goto :fail

if not exist "frontend\dist\index.html" (
  echo 正在构建看板...
  pushd frontend
  call npm install
  if errorlevel 1 goto :fail
  call npm run build
  if errorlevel 1 goto :fail
  popd
)

echo.
echo 正在打开监测台窗口...
start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0desktop.py"
goto :eof

:fail
echo 启动失败。
exit /b 1
