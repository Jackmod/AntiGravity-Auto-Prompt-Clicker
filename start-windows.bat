@echo off
REM ===========================================================
REM  Auto Picker - Windows launcher
REM  Double-click this file to install (first run) and start.
REM ===========================================================
setlocal enabledelayedexpansion
title Auto Picker
cd /d "%~dp0"

REM --- Locate Node.js -----------------------------------------
where node >nul 2>nul
if %errorlevel%==0 (
    set "NODE_OK=1"
) else (
    if exist "%ProgramFiles%\nodejs\node.exe" (
        set "PATH=%ProgramFiles%\nodejs;%PATH%"
        set "NODE_OK=1"
    ) else if exist "%ProgramFiles(x86)%\nodejs\node.exe" (
        set "PATH=%ProgramFiles(x86)%\nodejs;%PATH%"
        set "NODE_OK=1"
    )
)

if not defined NODE_OK (
    echo.
    echo  [!] Node.js was not found.
    echo      Please install the LTS version from https://nodejs.org
    echo      then double-click this file again.
    echo.
    pause
    exit /b 1
)

echo.
echo   Auto Picker
echo   -----------
node -v

REM --- Install dependencies on first run ----------------------
if not exist "node_modules" (
    echo.
    echo   First run detected - installing dependencies...
    echo   ^(this happens only once and may take a couple of minutes^)
    echo.
    call npm install
    if errorlevel 1 (
        echo.
        echo  [!] Dependency installation failed. See messages above.
        pause
        exit /b 1
    )
)

echo.
echo   Starting Auto Picker...
echo.
REM Ensure Electron runs as a GUI app, not as plain Node.
set "ELECTRON_RUN_AS_NODE="
call npm start
