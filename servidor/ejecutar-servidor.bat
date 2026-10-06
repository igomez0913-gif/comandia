@echo off
setlocal
rem Lo ejecuta la tarea programada "Comandia Servidor" al encender el equipo. Mantiene Comandia corriendo:
rem si se cae (por ejemplo MySQL todavia no habia arrancado) espera 15 segundos y lo vuelve a iniciar.
cd /d "%~dp0.."
set "RAIZ=%CD%"
set "PY="
if exist "%RAIZ%\python\python.exe" set "PY=%RAIZ%\python\python.exe"
if not defined PY if exist "%RAIZ%\.venv\Scripts\python.exe" set "PY=%RAIZ%\.venv\Scripts\python.exe"
if not exist logs mkdir logs
if not defined PY (
  echo [%date% %time%] No se encontro Python de Comandia. >> logs\servidor.log
  exit /b 1
)
if not exist database.url (
  echo [%date% %time%] Falta database.url: ejecuta servidor\instalar-servidor.bat >> logs\servidor.log
  exit /b 1
)
set /p DATABASE_URL=<database.url
set /p COMANDIA_SECRET=<.secret
:bucle
if exist logs\servidor.log for %%F in (logs\servidor.log) do if %%~zF GTR 10485760 move /y logs\servidor.log logs\servidor.anterior.log >nul
echo [%date% %time%] Iniciando Comandia (servidor) >> logs\servidor.log
"%PY%" comandia_cmd.py servidor >> logs\servidor.log 2>&1
echo [%date% %time%] Comandia se detuvo (codigo %errorlevel%). Reintento en 15 segundos. >> logs\servidor.log
ping -n 16 127.0.0.1 >nul
goto bucle
