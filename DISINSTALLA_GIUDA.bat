@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Spengo Giuda e rimuovo icone e avvio automatico.
powershell -NoProfile -Command "try{Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8765/api/shutdown -ContentType 'application/json' -Body '{}' | Out-Null}catch{}"
powershell -NoProfile -Command "Remove-Item ([Environment]::GetFolderPath('Desktop')+'\Giuda.lnk') -ErrorAction SilentlyContinue; Remove-Item ([Environment]::GetFolderPath('Startup')+'\Giuda.lnk') -ErrorAction SilentlyContinue"
echo Fatto. Le recensioni restano nella cartella "recensioni": cancella la cartella di Giuda per eliminare tutto.
pause
