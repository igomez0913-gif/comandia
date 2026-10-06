@echo off
setlocal
cd /d "%~dp0.."
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
echo Esto detiene Comandia como servidor y quita el inicio automatico y las reglas del firewall.
echo NO borra tus datos (la base de datos MySQL ni la carpeta de Comandia).
set /p "SEGURO=Escribe SI para continuar: "
if /i not "%SEGURO%"=="SI" exit /b
schtasks /End /TN "Comandia Servidor" >nul 2>&1
schtasks /Delete /TN "Comandia Servidor" /F >nul 2>&1
netsh advfirewall firewall delete rule name="Comandia HTTPS" >nul 2>&1
netsh advfirewall firewall delete rule name="Comandia instalacion" >nul 2>&1
echo Listo.
pause
