@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title MIKEIZU Stock Intelligence PRO
color 0B
echo.
echo ==============================================================
echo           MIKEIZU STOCK INTELLIGENCE PRO
echo ==============================================================
echo.
set "PYCMD="
where py >nul 2>&1
if not errorlevel 1 (
  py -3.13 --version >nul 2>&1 && set "PYCMD=py -3.13"
  if not defined PYCMD (py -3.12 --version >nul 2>&1 && set "PYCMD=py -3.12")
  if not defined PYCMD (py -3.11 --version >nul 2>&1 && set "PYCMD=py -3.11")
)
if not defined PYCMD (
  python --version >nul 2>&1 && set "PYCMD=python"
)
if not defined PYCMD (
  echo ERROR: Python 3.11-3.13 is required. Install it from python.org.
  echo During installation enable "Add Python to PATH".
  pause
  exit /b 1
)
echo Using %PYCMD%
if not exist ".venv\Scripts\python.exe" (
  echo Creating a private virtual environment...
  %PYCMD% -m venv .venv
  if errorlevel 1 goto failed
)
echo Installing / updating dependencies; internet needed on first launch...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto failed
if not exist "data" mkdir "data"
echo Opening private local dashboard at http://127.0.0.1:8501
echo Press Ctrl+C here to stop the app.
".venv\Scripts\python.exe" -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --server.headless=false --browser.gatherUsageStats=false
if errorlevel 1 goto failed
exit /b 0
:failed
echo.
echo Startup failed. Check errors above; ensure Python and internet work.
pause
exit /b 1
