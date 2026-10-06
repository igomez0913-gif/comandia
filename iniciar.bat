@echo off
setlocal
cd /d "%~dp0"
title Comandia - Gestion comercial (MySQL)
set PORT=8000

rem --- Si ya hay un Comandia corriendo en este puerto, solo abre el navegador
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if %errorlevel%==0 (
  echo Comandia ya esta corriendo en el puerto %PORT%. Abriendo el navegador...
  start "" http://127.0.0.1:%PORT%
  timeout /t 5 >nul
  exit /b 0
)

rem --- Version portatil: trae su propio Python con las librerias en la carpeta python (no instala nada)
if exist python\python.exe (
  set "PY=python\python.exe"
  goto python_listo
)

rem --- Entorno de Python (solo la primera vez)
if not exist .venv\Scripts\python.exe (
  echo Creando el entorno de Python por unica vez...
  python -m venv .venv
  if errorlevel 1 (
    echo No se encontro Python. Instalalo desde python.org y marca "Add python.exe to PATH".
    pause
    exit /b 1
  )
)
set "PY=.venv\Scripts\python.exe"
rem --- Librerias: se instalan la primera vez y otra vez cuando una version nueva de Comandia cambia requirements.txt
rem INICIO-LIBRERIAS
if not exist .venv\requirements.instalado goto instalar_librerias
.venv\Scripts\python.exe -c "import filecmp,sys; sys.exit(0 if filecmp.cmp('requirements.txt', '.venv/requirements.instalado', shallow=False) else 1)"
if errorlevel 1 goto instalar_librerias
goto librerias_listas
:instalar_librerias
echo Instalando o actualizando librerias, se necesita internet...
.venv\Scripts\python.exe -m pip install -q --disable-pip-version-check -r requirements.txt
if errorlevel 1 (
  echo Fallo la instalacion. Revisa tu conexion a internet y vuelve a intentar.
  pause
  exit /b 1
)
copy /y requirements.txt .venv\requirements.instalado >nul
:librerias_listas
rem FIN-LIBRERIAS
:python_listo

rem --- Conexion a MySQL: la primera vez pregunta servidor, usuario y clave y los guarda en database.url
if not exist database.url (
  "%PY%" comandia_cmd.py setup_mysql
  if errorlevel 1 (
    echo.
    echo No se pudo configurar MySQL. Corrige los datos y vuelve a abrir este archivo.
    pause
    exit /b 1
  )
)
set /p DATABASE_URL=<database.url

rem --- Clave propia de este equipo (se genera una vez y se guarda en el archivo .secret)
rem Si quedo vacio o danado (por ejemplo, un corte de luz en el primer arranque) se vuelve a generar.
if exist .secret for %%A in (.secret) do if %%~zA LSS 32 del .secret
if not exist .secret "%PY%" -c "import secrets;print(secrets.token_hex(32))" > .secret
set /p COMANDIA_SECRET=<.secret

echo.
echo Comandia iniciando en http://127.0.0.1:%PORT%  (base de datos: MySQL)
echo Deja esta ventana abierta mientras uses el sistema. Para detenerlo, cierrala.
echo.
start "" /min cmd /c "timeout /t 3 >nul & start http://127.0.0.1:%PORT%"
"%PY%" -m uvicorn app.main:app --app-dir . --host 127.0.0.1 --port %PORT%
echo.
echo Comandia se detuvo.
pause
