@echo off
setlocal
cd /d "%~dp0"
rem Muestra un resumen de la base de datos para comparar ANTES y DESPUES de actualizar (solo lee). Guarda el resultado en un archivo:
rem    resumen-db.bat > antes.txt
set "PY="
if exist python\python.exe set "PY=python\python.exe"
if not defined PY if exist .venv\Scripts\python.exe set "PY=.venv\Scripts\python.exe"
if not defined PY (
  echo No encontre Python de Comandia.
  exit /b 1
)
"%PY%" comandia_cmd.py resumen_db
