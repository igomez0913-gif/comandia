@echo off
setlocal
cd /d "%~dp0"
rem Crea en el escritorio un acceso directo "Comandia" que abre Comandia.exe (con su icono).
if not exist Comandia.exe (
  echo No encontre Comandia.exe en esta carpeta.
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d=[Environment]::GetFolderPath('Desktop'); $s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Comandia.lnk')); $s.TargetPath='%~dp0Comandia.exe'; $s.WorkingDirectory='%~dp0'; $s.IconLocation='%~dp0Comandia.exe,0'; $s.Description='Comandia - Gestion comercial'; $s.Save(); $t=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Detener Comandia.lnk')); $t.TargetPath='%~dp0Comandia.exe'; $t.Arguments='/detener'; $t.WorkingDirectory='%~dp0'; $t.IconLocation='%~dp0Comandia.exe,0'; $t.Description='Apaga Comandia'; $t.Save()"
if errorlevel 1 (
  echo No se pudo crear el acceso directo. Puedes hacerlo a mano: clic derecho en Comandia.exe, Enviar a, Escritorio.
) else (
  echo Listo: ya tienes en el escritorio el icono "Comandia" y el de "Detener Comandia".
)
pause
