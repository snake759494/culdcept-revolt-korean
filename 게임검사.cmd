@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 게임을 켜 둔 상태에서 실행하세요.
echo.
python check_running_game.py %*
echo.
pause
