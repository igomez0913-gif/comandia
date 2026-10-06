@echo off
setlocal
rem Para actualizar: descomprime el zip nuevo ENCIMA de esta carpeta (acepta reemplazar) y ejecuta este archivo.
rem Detiene el servidor, actualiza la base de datos (con respaldo previo) y lo vuelve a iniciar.
cd /d "%~dp0.."
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "PY="
if exist python\python.exe set "PY=python\python.exe"
if not defined PY if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if not defined PY (
  echo No encontre Python de Comandia.
  pause
  exit /b 1
)
set "PH=443"
for /f %%P in ('%PY% -c "from app import servidor; print(servidor.read_conf()['puerto_https'])" 2^>nul') do set "PH=%%P"
schtasks /End /TN "Comandia Servidor" >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PH% .*LISTENING"') do taskkill /f /pid %%P >nul 2>&1
ping -n 4 127.0.0.1 >nul
set /p DATABASE_URL=<database.url
"%PY%" comandia_cmd.py actualizar_db
if errorlevel 1 (
  echo La actualizacion de la base de datos fallo. El servidor NO se inicio. Revisa el mensaje de arriba.
  pause
  exit /b 1
)
schtasks /Run /TN "Comandia Servidor" >nul
echo Listo. Comandia actualizado e iniciado. Los usuarios deben pulsar Ctrl+F5 en el navegador.
pause
