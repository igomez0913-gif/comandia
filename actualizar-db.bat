@echo off
setlocal
cd /d "%~dp0"
title Comandia - Actualizar base de datos
rem Cierra Comandia (la ventana negra de iniciar.bat) antes de ejecutar esto.
set "PY="
if exist python\python.exe set "PY=python\python.exe"
if not defined PY if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if not defined PY (
  echo No encontre Python para Comandia.
  echo Abre iniciar.bat una vez para prepararlo, o usa la version portatil que ya lo incluye.
  pause
  exit /b 1
)
if not exist database.url (
  echo No encontre database.url. Copialo de tu instalacion anterior o ejecuta configurar-mysql.bat.
  pause
  exit /b 1
)
"%PY%" comandia_cmd.py actualizar_db
echo.
pause
