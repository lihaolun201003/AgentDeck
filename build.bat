@echo off
rem ---------------------------------------------------------------------
rem  AgentDeck build script (PyInstaller)
rem  NOTE: keep this file ASCII-only. Chinese text here gets mangled by
rem        the cmd.exe code page and breaks batch parsing.
rem ---------------------------------------------------------------------
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ==========================================
echo   AgentDeck - build exe with PyInstaller
echo ==========================================
echo.

set "PY=.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] virtual env not found: %PY%
    echo         run these first:
    echo             python -m venv .venv
    echo             .venv\Scripts\python.exe -m pip install -r requirements.txt
    exit /b 1
)

echo [1/4] Checking dev dependencies ...
rem Do NOT upgrade PyInstaller on every build: that makes the build
rem environment drift. Install from requirements-dev.txt only if missing.
"%PY%" -c "import PyInstaller" >nul 2>&1
if errorlevel 1 (
    echo       PyInstaller not found, installing dev dependencies ...
    "%PY%" -m pip install -r requirements-dev.txt
    if errorlevel 1 (
        echo [ERROR] failed to install dev dependencies
        exit /b 1
    )
)

echo.
echo [2/4] Generating icon ...
"%PY%" tools\make_icon.py
if errorlevel 1 echo [WARN] icon generation failed, using default icon

echo.
echo [3/4] Building ...
"%PY%" -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --distpath build\release ^
    --workpath build\pyinstaller ^
    AgentDeck.spec
if errorlevel 1 (
    echo [ERROR] build failed
    exit /b 1
)

echo.
echo [4/4] Preparing writable data folders ...
if not exist "dist\AgentDeck" mkdir "dist\AgentDeck"
xcopy /e /i /q /y "build\release\AgentDeck" "dist\AgentDeck" >nul
if errorlevel 1 (
    echo [ERROR] failed to update app files. Exit AgentDeck and try again.
    exit /b 1
)
if not exist "dist\AgentDeck\prompts" (
    xcopy /e /i /q /y "prompts" "dist\AgentDeck\prompts" >nul
    echo       copied prompts folder
)
if not exist "dist\AgentDeck\data" mkdir "dist\AgentDeck\data" 2>nul
if not exist "dist\AgentDeck\README.md" copy /y "README.md" "dist\AgentDeck\README.md" >nul

echo.
echo ==========================================
echo   Build finished
echo   Executable: dist\AgentDeck\AgentDeck.exe
echo   prompts\ and data\ live next to the exe
echo ==========================================
endlocal
