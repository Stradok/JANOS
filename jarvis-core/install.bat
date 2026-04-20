@echo off
title JAN Installer
echo ========================================
echo   JAN - Joint Autonomous Neural Agent
echo   Installation Script
echo ========================================
echo.

cd /d "%~dp0"

:: ------------------------------------------------------------------
:: 1. Check Python
:: ------------------------------------------------------------------
python --version 2>nul
if errorlevel 1 (
    echo [ERROR] Python not found! Please install Python 3.10+ first.
    echo         https://www.python.org/downloads/
    pause
    exit /b 1
)

:: ------------------------------------------------------------------
:: 2. Install Python dependencies
:: ------------------------------------------------------------------
echo [1/4] Installing Python dependencies...
if exist "requirements_full.txt" (
    pip install -r requirements_full.txt
) else if exist "requirements.txt" (
    pip install -r requirements.txt
) else (
    echo [WARNING] No requirements file found — skipping pip install.
)
if errorlevel 1 (
    echo [WARNING] Some packages failed to install. JAN will work with reduced features.
)

:: ------------------------------------------------------------------
:: 3. Playwright browsers
:: ------------------------------------------------------------------
echo.
echo [2/4] Installing browser engine...
playwright install chromium 2>nul
if errorlevel 1 (
    echo [WARNING] Playwright browser install failed — web features may be limited.
)

:: ------------------------------------------------------------------
:: 4. Check Ollama
:: ------------------------------------------------------------------
echo.
echo [3/4] Checking Ollama...
ollama --version 2>nul
if errorlevel 1 (
    echo [WARNING] Ollama not found.
    echo          Please install from https://ollama.com
    echo          JAN needs Ollama to think. After install run:
    echo            ollama pull llama3.1:8b
) else (
    echo Pulling small monitor model...
    ollama pull qwen2.5:1.5b
    echo Pulling main reasoning model...
    ollama pull llama3.1:8b
)

:: ------------------------------------------------------------------
:: 5. Create runtime directories
:: ------------------------------------------------------------------
echo.
echo [4/4] Setting up directories...
if not exist "memory\audio\tts"          mkdir "memory\audio\tts"
if not exist "memory\vision\faces"       mkdir "memory\vision\faces"
if not exist "memory\vision\captures"    mkdir "memory\vision\captures"
if not exist "memory\vision\voices"      mkdir "memory\vision\voices"
if not exist "memory\logs"               mkdir "memory\logs"
if not exist "modules\generated"         mkdir "modules\generated"

echo.
echo ========================================
echo   Installation Complete!
echo.
echo   To run JAN:
echo     python jan_service.py standalone
echo   Or:
echo     python -m uvicorn main:app
echo.
echo   To add to Windows Startup:
echo     Copy startup.bat to:
echo     %%APPDATA%%\Microsoft\Windows\Start Menu\Programs\Startup
echo ========================================
pause
