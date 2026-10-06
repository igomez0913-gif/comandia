@echo off
rem Compila Comandia SIN codigo fuente (solo para el desarrollador).
rem Requisitos: Python 3.11 de 64 bits (puede convivir con otras versiones), Node.js y un compilador C (Visual Studio Build Tools o MinGW que Nuitka puede bajar).
rem Uso:  compilar-protegido.bat comandia-portatil-3.4.0.zip     (si omites el zip, solo compila)
setlocal
cd /d "%~dp0.."
echo === Compilar Comandia protegido ===
echo Carpeta: %CD%

rem Busca Python 3.11: primero con el lanzador "py", luego con "python"
set "PY="
py -3.11 -c "import sys,struct; sys.exit(0 if struct.calcsize('P')==8 else 1)" >nul 2>nul
if not errorlevel 1 set "PY=py -3.11"
if defined PY goto py_listo
python -c "import sys,struct; sys.exit(0 if sys.version_info[:2]==(3,11) and struct.calcsize('P')==8 else 1)" >nul 2>nul
if not errorlevel 1 set "PY=python"
if defined PY goto py_listo
goto sin_python311

:py_listo
echo Usando: %PY%
%PY% --version
where npx >nul 2>nul
if errorlevel 1 goto sin_node

echo.
echo [1/3] Instalando Nuitka y librerias (necesita internet)...
%PY% -m pip install --disable-pip-version-check nuitka==2.5.9 ordered-set zstandard ecdsa -r requirements.txt
if errorlevel 1 goto fallo

echo.
echo [2/3] Compilando (puede tardar varios minutos; si Nuitka pregunta por MinGW, escribe yes)...
%PY% compilar\compilar-protegido.py
if errorlevel 1 goto fallo

if "%~1"=="" goto fin
echo.
echo [3/3] Armando el zip protegido...
%PY% compilar\armar-portatil-protegido.py "%~1"
if errorlevel 1 goto fallo
goto fin

:sin_python311
echo ERROR: no se encontro Python 3.11 de 64 bits. Tienes otra version, pero el sistema portatil usa 3.11 y el modulo compilado debe coincidir.
echo Instalalo desde https://www.python.org/downloads/release/python-3119/ (Windows installer 64-bit). Puede convivir con tu version actual.
echo Luego abre una consola nueva y vuelve a ejecutar este archivo.
goto salir
:sin_node
echo ERROR: falta Node.js. Instalalo desde nodejs.org y abre una consola nueva.
goto salir
:fallo
echo.
echo ERROR: algo fallo. Copia el mensaje de arriba para revisarlo.
goto salir
:fin
echo.
echo Terminado. Resultado en la carpeta dist
:salir
pause
