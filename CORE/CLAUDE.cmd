@echo off
setlocal
cd /d "%~dp0.."
set "THESIS_CLAUDE=%USERPROFILE%\.local\bin\claude.exe"
if exist "%THESIS_CLAUDE%" goto found
set "THESIS_CLAUDE="
for /f "delims=" %%C in ('where claude.exe 2^>nul') do if not defined THESIS_CLAUDE set "THESIS_CLAUDE=%%C"
if defined THESIS_CLAUDE goto found
echo Claude Code is not installed. Read CORE\CLAUDE-HANDOFF.mn.md.
pause
exit /b 1
:found
if /i "%~1"=="--version" goto version
if /i "%~1"=="desktop" (
  "%THESIS_CLAUDE%" --desktop
) else (
  "%THESIS_CLAUDE%" "/thesis-resume"
)
goto finish
:version
"%THESIS_CLAUDE%" --version
:finish
set "THESIS_CLAUDE_EXIT=%ERRORLEVEL%"
endlocal & exit /b %THESIS_CLAUDE_EXIT%
