@echo off
setlocal
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
schtasks /Run /TN "Comandia Servidor"
echo Iniciando. Revisa en unos segundos con servidor\estado-servidor.bat
timeout /t 4 >nul
