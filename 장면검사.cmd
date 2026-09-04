@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 문제의 장면(대사)을 화면에 띄워 둔 채로 실행하세요.
echo 게임을 끄지 마세요 - 그 장면이 화면에 있어야 합니다.
echo.
python check_scene.py %*
echo.
pause
