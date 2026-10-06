@echo off
setlocal
rem Usalo si cambiaste los nombres/IP en servidor.conf o si la IP del servidor cambio. La autoridad de Comandia se conserva,
rem asi que las computadoras que ya instalaron el certificado NO tienen que repetir nada.
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
"%PY%" comandia_cmd.py servidor certs
schtasks /End /TN "Comandia Servidor" >nul 2>&1
ping -n 4 127.0.0.1 >nul
schtasks /Run /TN "Comandia Servidor" >nul
echo Listo. El servidor se reinicio con el certificado nuevo.
pause
