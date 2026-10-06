@echo off
setlocal
cd /d "%~dp0"
rem Generador de claves de Comandia (solo para el desarrollador). Instala la libreria ecdsa si falta.
set "PY="
py -3.11 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3.11"
if defined PY goto py_listo
py -3 --version >nul 2>nul
if not errorlevel 1 set "PY=py -3"
if defined PY goto py_listo
python --version >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto py_listo
echo No se encontro Python. Instalalo desde python.org (marca "Add python.exe to PATH").
pause
exit /b 1
:py_listo
%PY% -c "import ecdsa" >nul 2>nul
if not errorlevel 1 goto correr
echo Instalando la libreria ecdsa (necesita internet, solo la primera vez)...
%PY% -m pip install --disable-pip-version-check ecdsa
if errorlevel 1 (
  echo No se pudo instalar ecdsa. Revisa tu conexion a internet.
  pause
  exit /b 1
)
:correr
%PY% generador-de-claves.py %*
if "%~1"=="" pause
