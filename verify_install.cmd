@echo off
setlocal

set "AZAHAR_DIR=%APPDATA%\Azahar"
if not "%~1"=="" set "AZAHAR_DIR=%~1"

echo Azahar 사용자 폴더를 검사합니다: "%AZAHAR_DIR%"
python "%~dp0verify_install.py" "%AZAHAR_DIR%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo 검사 완료: 핵심 경로와 패치 구조는 정상입니다.
) else (
    echo 검사 결과를 확인하세요. X 항목이 있으면 README.md의 적용 방법을 참고하세요.
)
pause
exit /b %EXIT_CODE%
