@echo off
chcp 65001 >nul
setlocal

set "AZAHAR_DIR=%APPDATA%\Azahar"
if not "%~1"=="" set "AZAHAR_DIR=%~1"

echo Checking Azahar user directory: "%AZAHAR_DIR%"
python "%~dp0verify_install.py" "%AZAHAR_DIR%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
    echo Check complete: core paths and patch structure are valid.
) else (
    echo Review the results above. See README.md if an X item is reported.
)
pause
exit /b %EXIT_CODE%
