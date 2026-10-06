#!/usr/bin/env bash
# Arma «Comandia portátil» para Windows (64 bits) desde Linux: Python 3.11 oficial (paquete NuGet de la
# Python Software Foundation) con todas las librerías ya instaladas. En Windows no hay que instalar Python
# ni descargar nada: se descomprime en C:\Comandia y se abre Comandia.exe. Solo hace falta MySQL.
#   Uso: windows/build-portable.sh            → dist/comandia-portatil-<versión>.zip
set -euo pipefail
cd "$(dirname "$0")/.."
PYVER="3.11.9"
VERSION=$(python3 -c "import re;print(re.search(r'version=\"([^\"]+)\"', open('app/main.py').read()).group(1))")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/Comandia"
mkdir -p "$OUT" dist

echo "1) Python $PYVER oficial para Windows"
curl -sSfL -o "$WORK/python.nupkg" "https://api.nuget.org/v3-flatcontainer/python/$PYVER/python.$PYVER.nupkg"
unzip -q "$WORK/python.nupkg" 'tools/*' -d "$WORK/nupkg"
mv "$WORK/nupkg/tools" "$OUT/python"

echo "2) Librerías para Windows (requirements.txt)"
python3 -m venv "$WORK/pip"  # pip aislado: no mezcla nada de este equipo
"$WORK/pip/bin/python" -m pip install -q --disable-pip-version-check --no-compile --target "$OUT/python/Lib/site-packages" \
  --platform win_amd64 --python-version 3.11 --implementation cp --abi cp311 --only-binary=:all: -r requirements.txt

echo "   quitando lo que Comandia no usa (pip, IDLE, Tkinter, pruebas de Python, archivos para compilar)"
rm -rf "$OUT/python/Tools" "$OUT/python/include" "$OUT/python/libs" "$OUT/python/tcl" \
       "$OUT/python/Lib/site-packages/pip" "$OUT/python/Lib/site-packages/pip-"* \
       "$OUT/python/Lib/site-packages/setuptools" "$OUT/python/Lib/site-packages/setuptools-"* "$OUT/python/Lib/site-packages/_distutils_hack" "$OUT/python/Lib/site-packages/distutils-precedence.pth" \
       "$OUT/python/Lib/ensurepip" "$OUT/python/Lib/idlelib" "$OUT/python/Lib/tkinter" "$OUT/python/Lib/turtledemo" "$OUT/python/Lib/turtle.py" \
       "$OUT/python/Lib/test" "$OUT/python/Lib/lib2to3" "$OUT/python/Lib/pydoc_data" "$OUT/python/DLLs/_tkinter.pyd" "$OUT/python/DLLs/tcl"*.dll "$OUT/python/DLLs/tk"*.dll
find "$OUT/python" -name "__pycache__" -type d -prune -exec rm -rf {} +

echo "3) Comandia (archivos del repositorio, tal como están en esta carpeta)"
git ls-files -z -- . ':(exclude).gitignore' ':(exclude)windows' ':(exclude)herramientas' ':(exclude)compilar' ':(exclude).github' ':(exclude)iniciar.sh' ':(exclude)tests' ':(exclude)pytest.ini' ':(exclude)requirements-dev.txt' | tar --null -T - -cf - | tar -x -C "$OUT"
if [ -n "${COMANDIA_PROTEGIDO:-}" ]; then  # versión sin código fuente: backend compilado y JS ofuscado (compilar/compilar-protegido.py)
  echo "   modo PROTEGIDO: backend compilado, sin .py"
  ls "$COMANDIA_PROTEGIDO"/app.*.pyd >/dev/null  # falla si no está el módulo compilado
  rm -f "$OUT"/app/*.py
  cp "$COMANDIA_PROTEGIDO"/app.*.pyd "$OUT/"
  cp "$COMANDIA_PROTEGIDO"/static/*.js "$OUT/static/"
  VERSION="$VERSION-protegido"
fi
echo "$VERSION" > "$OUT/python/COMANDIA-PORTATIL.txt"

echo "4) Empaquetando"
ZIP="$PWD/dist/comandia-portatil-$VERSION.zip"
rm -f "$ZIP"
(cd "$OUT" && zip -q -r -9 "$ZIP" .)
echo "Listo: $ZIP ($(du -h "$ZIP" | cut -f1))"
