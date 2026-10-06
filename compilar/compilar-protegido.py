#!/usr/bin/env python3
"""Compila Comandia para entregarlo SIN código fuente. SOLO PARA EL DESARROLLADOR.

  python compilar/compilar-protegido.py            → dist/protegido/

Qué hace:
  1. Compila el paquete `app` (todo el backend) con Nuitka a un único módulo nativo (app.*.pyd en Windows).
     Debe correrse con el MISMO Python y sistema que el destino: para el portátil de Windows, Python 3.11 de 64 bits
     en Windows con un compilador C (Visual Studio Build Tools o el que Nuitka descarga: MinGW). Lo hace el flujo
     de GitHub Actions `.github/workflows/protegido.yml`.
  2. Minifica y ofusca los .js de static/ (terser + javascript-obfuscator vía npx; si no hay Node, avisa y los deja iguales).

Salida en dist/protegido/: el módulo compilado y static/ con los .js ofuscados. `windows/build-portable.sh` con la variable
COMANDIA_PROTEGIDO=dist/protegido arma el portátil usando esos archivos y quitando los .py de app/.
"""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "protegido")


def run(cmd, **kw):
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True, **kw)


def compilar_backend():
    print("1) Compilando app/ con Nuitka")
    tmp = os.path.join(OUT, "_nuitka")
    run([sys.executable, "-m", "nuitka", "--module", "app", "--include-package=app", f"--output-dir={tmp}",
         "--assume-yes-for-downloads", "--remove-output", "--no-pyi-file"], cwd=ROOT)
    found = glob.glob(os.path.join(tmp, "app.*.pyd")) + glob.glob(os.path.join(tmp, "app.*.so"))
    if not found:
        sys.exit("ERROR: Nuitka no generó el módulo compilado.")
    for path in found:
        shutil.move(path, os.path.join(OUT, os.path.basename(path)))
    shutil.rmtree(tmp, ignore_errors=True)
    print("   →", ", ".join(os.path.basename(p) for p in found))


def ofuscar_js():
    print("2) Minificando y ofuscando el JavaScript")
    dest = os.path.join(OUT, "static")
    os.makedirs(dest, exist_ok=True)
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    for src in sorted(glob.glob(os.path.join(ROOT, "static", "*.js"))):
        name = os.path.basename(src)
        out = os.path.join(dest, name)
        if not npx:
            print(f"   AVISO: no hay Node/npx; {name} queda sin ofuscar")
            shutil.copy(src, out)
            continue
        tmp = out[:-3] + ".min.js"  # el ofuscador solo acepta archivos .js
        run([npx, "--yes", "terser", src, "--compress", "--mangle", "-o", tmp])
        run([npx, "--yes", "javascript-obfuscator", tmp, "--output", out, "--compact", "true", "--string-array", "true",
             "--string-array-threshold", "0.75", "--identifier-names-generator", "hexadecimal", "--self-defending", "false"])
        os.remove(tmp)


if __name__ == "__main__":
    if "--solo-js" in sys.argv:  # reutiliza el módulo ya compilado en dist/protegido y solo rehace el JavaScript
        os.makedirs(OUT, exist_ok=True)
    else:
        shutil.rmtree(OUT, ignore_errors=True)
        os.makedirs(OUT)
        compilar_backend()
    ofuscar_js()
    print(f"\nListo: {OUT}")
