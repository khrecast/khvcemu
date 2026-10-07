@echo off
rem Opens the Re-Cast website stats in your browser: double-click this.
rem (It reads the anonymous counters from the live database, read-only, through wrangler.)
cd /d "%~dp0.."
set PY=python
where python >nul 2>nul || set PY=py -3
%PY% tools\site_stats.py --open
if errorlevel 1 (
  echo.
  echo Something went wrong, see the message above.
  pause
)
