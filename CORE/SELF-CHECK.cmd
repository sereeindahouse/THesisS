@echo off
setlocal
cd /d "%~dp0.."
set "THESIS_PYTHON=.venv-modeltools\Scripts\python.exe"
if not exist "%THESIS_PYTHON%" set "THESIS_PYTHON=.venv\Scripts\python.exe"
if not exist "%THESIS_PYTHON%" (
  echo Python environment missing. Read CORE\README.mn.md.
  pause
  exit /b 1
)
"%THESIS_PYTHON%" open_demo.py --no-browser
if errorlevel 1 (
  pause
  exit /b 1
)
"%THESIS_PYTHON%" tools\evaluate_voice_loop.py --open-report
if errorlevel 1 pause
endlocal
