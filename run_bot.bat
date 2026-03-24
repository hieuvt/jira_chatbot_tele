@echo off
setlocal

set "BASE_DIR=%~dp0"
set "LOG_DIR=%BASE_DIR%logs"
if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"
set "LOG_FILE=%LOG_DIR%\startup-bot.log"

cd /d "%BASE_DIR%"

echo [%DATE% %TIME%] Starting JiraTelegramBot >> "%LOG_FILE%"

set "PYTHON_EXE=%PYTHON_EXE%"
if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"

"%PYTHON_EXE%" "src\bot\entrypoint.py" >> "%LOG_FILE%" 2>&1
set "EXIT_CODE=%ERRORLEVEL%"
echo [%DATE% %TIME%] JiraTelegramBot exited with code %EXIT_CODE% >> "%LOG_FILE%"

exit /b %EXIT_CODE%
