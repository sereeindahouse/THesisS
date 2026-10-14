@echo off
cd /d "%~dp0.."
if exist ".venv-modeltools\Scripts\python.exe" (
  ".venv-modeltools\Scripts\python.exe" -X utf8 open_demo.py --data
) else (
  ".venv\Scripts\python.exe" -X utf8 open_demo.py --data
)
if errorlevel 1 pause
