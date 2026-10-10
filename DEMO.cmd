@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
  if not errorlevel 1 goto use_venv
)
py -3.11 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 goto use_py
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if not errorlevel 1 goto use_python
echo Python 3.11 буюу түүнээс шинэ хувилбар олдсонгүй.
echo Төслийн .venv орчноо бэлтгээд DEMO.cmd-ийг дахин нээнэ үү.
goto failed

:use_venv
".venv\Scripts\python.exe" -X utf8 open_demo.py %*
goto done

:use_py
py -3.11 -X utf8 open_demo.py %*
goto done

:use_python
python -X utf8 open_demo.py %*

:done
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
echo Demo нээхэд алдаа гарлаа. Дээрх тайлбарыг уншина уу.
pause
exit /b 1
