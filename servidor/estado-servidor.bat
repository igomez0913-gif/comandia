@echo off
setlocal
cd /d "%~dp0.."
set "PH=443"
set "PY="
if exist python\python.exe set "PY=python\python.exe"
if not defined PY if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if defined PY for /f %%P in ('%PY% -c "from app import servidor; print(servidor.read_conf()['puerto_https'])" 2^>nul') do set "PH=%%P"
echo ===== Tarea programada =====
schtasks /Query /TN "Comandia Servidor" /FO LIST 2>nul | findstr /i "Estado Status Nombre TaskName"
echo.
echo ===== Respuesta del sistema =====
curl.exe -sk "https://localhost:%PH%/api/health"
echo.
echo.
echo ===== Equipos conectados al puerto %PH% =====
netstat -ano | findstr /R /C:":%PH% .*ESTABLISHED"
echo.
echo ===== Direcciones =====
if defined PY %PY% comandia_cmd.py servidor info
echo.
echo ===== Ultimas lineas del registro =====
if exist logs\servidor.log powershell -NoProfile -Command "Get-Content -Tail 15 logs\servidor.log"
echo.
pause
