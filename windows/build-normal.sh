#!/usr/bin/env bash
# Arma el zip «normal» de Comandia (para equipos con Python 3.11+ instalado): los mismos archivos que el portátil, sin el Python incluido.
# En Windows: se descomprime en C:\Comandia y se abre Comandia.exe (o iniciar.bat); la primera vez crea el entorno e instala las librerías (necesita internet).
#   Uso: windows/build-normal.sh            → dist/comandia-<versión>.zip
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(python3 -c "import re;print(re.search(r'version=\"([^\"]+)\"', open('app/main.py').read()).group(1))")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/Comandia"
mkdir -p "$OUT" dist
# Solo lo que está en el repositorio (nunca .secret, database.url, respaldos ni la llave privada de licencias); los .bat conservan sus saltos CRLF.
git ls-files -z -- . ':(exclude).gitignore' ':(exclude)windows' ':(exclude)herramientas' ':(exclude)compilar' ':(exclude).github' ':(exclude)iniciar.sh' ':(exclude)tests' ':(exclude)pytest.ini' ':(exclude)requirements-dev.txt' | tar --null -T - -cf - | tar -x -C "$OUT"
git diff --quiet HEAD -- . || { echo "AVISO: hay cambios sin confirmar; el zip solo lleva lo confirmado en git"; }
ZIP="$PWD/dist/comandia-$VERSION.zip"
rm -f "$ZIP"
(cd "$OUT" && zip -q -r -9 "$ZIP" .)
echo "Listo: $ZIP ($(du -h "$ZIP" | cut -f1))"
