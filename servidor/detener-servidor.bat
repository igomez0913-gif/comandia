@echo off
setlocal
cd /d "%~dp0.."
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
set "PH=443"
set "PY="
if exist python\python.exe set "PY=python\python.exe"
if not defined PY if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if defined PY for /f %%P in ('%PY% -c "from app import servidor; print(servidor.read_conf()['puerto_https'])" 2^>nul') do set "PH=%%P"
schtasks /End /TN "Comandia Servidor" >nul 2>&1
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PH% .*LISTENING"') do taskkill /f /pid %%P >nul 2>&1
echo Comandia (servidor) detenido. Para volver a iniciarlo: servidor\iniciar-servidor.bat
timeout /t 4 >nul
