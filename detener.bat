@echo off
setlocal
rem Apaga Comandia cuando se inicio con Comandia.exe (sin ventana). Equivale a Comandia.exe /detener
set PORT=8100
set FOUND=0
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%PORT% .*LISTENING"') do (
  taskkill /f /pid %%P >nul 2>&1
  set FOUND=1
)
if "%FOUND%"=="1" (
  echo Comandia se detuvo. Para volver a usarlo, abre Comandia.exe.
) else (
  echo Comandia no estaba corriendo.
)
timeout /t 4 >nul
