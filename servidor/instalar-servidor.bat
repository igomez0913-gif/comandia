@echo off
setlocal EnableExtensions
title Comandia - instalar servidor multiusuario
cd /d "%~dp0.."
set "RAIZ=%CD%"

net session >nul 2>&1
if errorlevel 1 (
  echo Se necesitan permisos de administrador. Acepta el aviso que aparece en pantalla.
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

echo.
echo ============================================================
echo   COMANDIA - INSTALAR SERVIDOR MULTIUSUARIO
echo ============================================================
echo Esta computadora quedara como servidor: las demas entran por
echo el navegador. Carpeta de Comandia: %RAIZ%
echo.

set "PY="
if exist "%RAIZ%\python\python.exe" set "PY=%RAIZ%\python\python.exe"
if not defined PY if exist "%RAIZ%\.venv\Scripts\python.exe" set "PY=%RAIZ%\.venv\Scripts\python.exe"
if not defined PY (
  echo No encontre Python de Comandia. Usa el paquete "portatil" (trae todo incluido).
  pause
  exit /b 1
)

echo [1/7] Conexion a MySQL
if not exist database.url (
  "%PY%" comandia_cmd.py setup_mysql
  if errorlevel 1 (
    echo No se pudo configurar MySQL. Instala y arranca MySQL o MariaDB en este equipo y vuelve a ejecutar este archivo.
    pause
    exit /b 1
  )
) else (
  echo       Ya existe database.url, se conserva.
)

echo [2/7] Clave propia de este servidor
if exist .secret for %%A in (.secret) do if %%~zA LSS 32 del .secret
if not exist .secret "%PY%" -c "import secrets;print(secrets.token_hex(32))" > .secret

echo [3/7] Nombre y direccion con los que entraran los usuarios
set "NOMBRES="
for /f "usebackq delims=" %%N in (`"%PY%" -c "from app import servidor; c=servidor.read_conf(); print(c['nombres'] or ','.join(servidor.detect_names()))"`) do set "NOMBRES=%%N"
echo       Detectado: %NOMBRES%
echo       Puedes escribir otros nombres o IP separados por coma (por ejemplo: comandia,192.168.1.50).
echo       Los usuarios podran entrar con cualquiera de ellos. Se recomienda una IP FIJA para este equipo.
set "OTROS="
set /p "OTROS=Nombres o IP [Enter = usar los detectados]: "
if defined OTROS set "NOMBRES=%OTROS%"
"%PY%" -c "from app import servidor; c=servidor.read_conf(); c['nombres']=r'%NOMBRES%'; servidor.write_conf(c)"
if errorlevel 1 (
  echo No se pudo guardar servidor.conf
  pause
  exit /b 1
)
set "PH=443"
set "PW=80"
for /f %%P in ('"%PY%" -c "from app import servidor; print(servidor.read_conf()['puerto_https'])"') do set "PH=%%P"
for /f %%P in ('"%PY%" -c "from app import servidor; print(servidor.read_conf()['puerto_http'])"') do set "PW=%%P"

echo [4/7] Certificados de seguridad (HTTPS)
"%PY%" comandia_cmd.py servidor certs
if errorlevel 1 (
  echo No se pudieron crear los certificados.
  pause
  exit /b 1
)

echo [5/7] Firewall de Windows (solo la red local)
netsh advfirewall firewall delete rule name="Comandia HTTPS" >nul 2>&1
netsh advfirewall firewall delete rule name="Comandia instalacion" >nul 2>&1
netsh advfirewall firewall add rule name="Comandia HTTPS" dir=in action=allow protocol=TCP localport=%PH% remoteip=localsubnet profile=any >nul
netsh advfirewall firewall add rule name="Comandia instalacion" dir=in action=allow protocol=TCP localport=%PW% remoteip=localsubnet profile=any >nul
echo       Puertos %PH% (sistema) y %PW% (instalacion en cada PC) abiertos para la red local.

echo [6/7] Inicio automatico al encender el equipo
powershell -NoProfile -Command "(Get-Content -Raw -Encoding Unicode '%~dp0tarea-comandia.xml').Replace('__RAIZ__', '%RAIZ%') | Set-Content -Encoding Unicode '%TEMP%\comandia-tarea.xml'"
schtasks /End /TN "Comandia Servidor" >nul 2>&1
schtasks /Create /TN "Comandia Servidor" /XML "%TEMP%\comandia-tarea.xml" /F
if errorlevel 1 (
  echo No se pudo crear la tarea programada.
  pause
  exit /b 1
)
del "%TEMP%\comandia-tarea.xml" >nul 2>&1

echo [7/7] Iniciando el servidor
rem Si habia un Comandia de un solo equipo abierto (Comandia.exe), se cierra para no duplicar.
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8100 .*LISTENING"') do taskkill /f /pid %%P >nul 2>&1
schtasks /Run /TN "Comandia Servidor" >nul
set "OK="
for /l %%I in (1,1,40) do if not defined OK (
  curl.exe -sk "https://localhost:%PH%/api/health" 2>nul | findstr /c:"ok" >nul && set "OK=1"
  if not defined OK ping -n 3 127.0.0.1 >nul
)

set "PRIMER="
for /f "tokens=1 delims=," %%N in ("%NOMBRES%") do set "PRIMER=%%N"
set "PUERTOURL="
if not "%PH%"=="443" set "PUERTOURL=:%PH%"
if not exist "%~dp0clientes" mkdir "%~dp0clientes"
> "%~dp0clientes\Comandia.url" echo [InternetShortcut]
>> "%~dp0clientes\Comandia.url" echo URL=https://%PRIMER%%PUERTOURL%
echo.
if defined OK (
  echo ============================================================
  echo   LISTO. El servidor esta funcionando.
  echo ============================================================
) else (
  echo ============================================================
  echo   Se instalo, pero el servidor no respondio todavia.
  echo   Revisa logs\servidor.log y que MySQL este iniciado.
  echo   Luego ejecuta servidor\estado-servidor.bat
  echo ============================================================
)
echo.
echo EN ESTE SERVIDOR: abre https://localhost%PUERTOURL%  (acepta el certificado una vez con servidor\instalar-certificado-aqui.bat)
echo EN CADA COMPUTADORA DE LOS USUARIOS, abre el navegador y entra a:
set "PUERTOHTTP="
if not "%PW%"=="80" set "PUERTOHTTP=:%PW%"
echo       http://%PRIMER%%PUERTOHTTP%
echo   y sigue los 2 pasos de esa pagina (instalar certificado y abrir el sistema).
echo   Despues guarda https://%PRIMER%%PUERTOURL% como favorito o copia servidor\clientes\Comandia.url al escritorio.
echo.
echo IMPORTANTE: en este equipo NO uses Comandia.exe (es para un solo equipo).
echo Usuario inicial: luis@miempresa.hn / comandia123  -> cambia la clave al entrar.
echo.
pause
