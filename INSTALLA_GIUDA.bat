@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"
title Installazione di Giuda
echo.
echo   =============================================
echo     GIUDA - "Chi l'ha deciso!!!"
echo     Installazione automatica
echo   =============================================
echo.
set "PYEXE="
where py >nul 2>nul
if !errorlevel!==0 (
  for /f "delims=" %%i in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
)
if not defined PYEXE (
  for /f "delims=" %%i in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PYEXE=%%i"
)
if not defined PYEXE (
  echo [..] Python non trovato: lo installo con winget ^(serve qualche minuto^)...
  winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PYEXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
)
if not defined PYEXE (
  echo.
  echo [X] Non riesco a installare Python automaticamente.
  echo     Scaricalo da https://www.python.org/downloads/ ^(spunta "Add python.exe to PATH"^)
  echo     e poi rilancia questo file.
  pause
  exit /b 1
)
"%PYEXE%" -c "import sys;sys.exit(0 if sys.version_info>=(3,9) else 1)"
if errorlevel 1 (
  echo [X] Serve Python 3.9 o superiore.
  pause & exit /b 1
)
echo [OK] Python: %PYEXE%
for %%i in ("%PYEXE%") do set "PYDIR=%%~dpi"
set "PYW=%PYDIR%pythonw.exe"
if not exist "%PYW%" set "PYW=%PYEXE%"
if not exist data mkdir data
> data\pythonw_path.txt echo %PYW%
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Giuda.lnk');" ^
 "$s.TargetPath='%~dp0AVVIA_GIUDA.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;" ^
 "$s.IconLocation='%SystemRoot%\System32\shell32.dll,22';$s.Description='Giuda - revisore di codice';$s.Save()"
echo [OK] Icona "Giuda" creata sul desktop
echo.
choice /c SN /m "Vuoi che Giuda parta da solo all'accensione del PC (sorveglianza continua)"
if !errorlevel!==1 (
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
   "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Giuda.lnk');" ^
   "$s.TargetPath='%~dp0AVVIA_GIUDA.bat';$s.Arguments='--no-browser';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;$s.Save()"
  echo [OK] Avvio automatico attivato
)
echo.
echo [OK] Installazione completata. Avvio Giuda...
call "%~dp0AVVIA_GIUDA.bat"
timeout /t 3 >nul
exit /b 0
