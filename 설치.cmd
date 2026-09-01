@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
  echo Python 이 필요합니다. https://www.python.org 에서 설치한 뒤 다시 실행하세요.
  pause
  exit /b 1
)

python install_patch.py %*
echo.
pause
