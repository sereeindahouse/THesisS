@echo off
where code >nul 2>nul
if errorlevel 1 (
  start "" "%~dp0THesisS.code-workspace"
) else (
  call code "%~dp0THesisS.code-workspace"
)
