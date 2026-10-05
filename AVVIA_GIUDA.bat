@echo off
cd /d "%~dp0"
if not exist data\pythonw_path.txt (
  echo Prima esegui INSTALLA_GIUDA.bat
  pause
  exit /b 1
)
set /p PYW=<data\pythonw_path.txt
for /f "tokens=* delims=" %%a in ("%PYW%") do set "PYW=%%~a"
start "" "%PYW%" "%~dp0giuda.py" %*
