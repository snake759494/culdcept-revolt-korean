@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo 문제의 화면(원문이 보이는 대사나 카드 이름)을 띄워 둔 채로 실행하세요.
echo 게임을 끄지 마세요.
echo.
python trace_source.py %*
echo.
pause
