@echo off
setlocal
cd /d "%~dp0"
title Comandia - Configurar MySQL
set "PY="
if exist python\python.exe set "PY=python\python.exe"
if not defined PY if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if not defined PY (
  echo No encontre Python para Comandia.
  echo Abre iniciar.bat una vez para prepararlo, o usa la version portatil que ya lo incluye.
  pause
  exit /b 1
)
"%PY%" comandia_cmd.py setup_mysql
echo.
pause
