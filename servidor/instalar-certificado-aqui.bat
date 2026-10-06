@echo off
setlocal
rem Hace que ESTE equipo (el servidor) confie en el certificado de Comandia para poder abrir https://localhost sin avisos.
cd /d "%~dp0.."
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
if not exist certs\ca.crt (
  echo Aun no existen los certificados. Ejecuta primero servidor\instalar-servidor.bat
  pause
  exit /b 1
)
certutil -addstore -f "Root" "%CD%\certs\ca.crt"
echo.
echo Listo. Cierra y vuelve a abrir el navegador.
pause
