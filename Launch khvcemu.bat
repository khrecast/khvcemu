@echo off
rem Double-click to open the khvcemu launcher (needs Python 3.10+ from python.org).
cd /d "%~dp0"
where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" pythonw -m khvcemu.launcher
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python was not found. Install it from https://www.python.org/downloads/
        echo and tick "Add python.exe to PATH" during setup, then try again.
        pause
        exit /b 1
    )
    python -m khvcemu.launcher
)
