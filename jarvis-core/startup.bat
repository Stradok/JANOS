@echo off
title JAN - Joint Autonomous Neural Agent
cd /d "%~dp0"

echo ========================================
echo   JAN - Joint Autonomous Neural Agent
echo   Starting in standalone mode...
echo ========================================
echo.

:: Activate venv if it exists
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

python jan_service.py standalone
pause
