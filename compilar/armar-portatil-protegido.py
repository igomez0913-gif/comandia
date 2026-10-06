#!/usr/bin/env python3
"""Arma el portátil PROTEGIDO en Windows (sin bash) a partir del portátil normal y de dist/protegido.

  python compilar/armar-portatil-protegido.py comandia-portatil-3.4.0.zip

Quita los .py de app/, agrega el módulo compilado (.pyd) y los .js ofuscados, y escribe comandia-portatil-<versión>-protegido.zip
junto al zip original. Antes hay que haber corrido compilar/compilar-protegido.py (o compilar-protegido.bat).
"""
import glob
import os
import shutil
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROT = os.path.join(ROOT, "dist", "protegido")


def main():
    if len(sys.argv) != 2 or not os.path.isfile(sys.argv[1]):
        sys.exit("Uso: python compilar/armar-portatil-protegido.py <comandia-portatil-X.zip>")
    src = os.path.abspath(sys.argv[1])
    pyd = glob.glob(os.path.join(PROT, "app.*.pyd"))
    if not pyd:
        sys.exit("No encuentro dist/protegido/app.*.pyd: corre primero compilar-protegido.bat")
    out = src[:-4] + "-protegido.zip"
    with tempfile.TemporaryDirectory() as work:
        with zipfile.ZipFile(src) as z:
            z.extractall(work)
        for path in glob.glob(os.path.join(work, "app", "*.py")):
            os.remove(path)
        shutil.copy(pyd[0], work)
        for js in glob.glob(os.path.join(PROT, "static", "*.js")):
            shutil.copy(js, os.path.join(work, "static"))
        if os.path.exists(out):
            os.remove(out)
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for folder, _, files in os.walk(work):
                for name in files:
                    full = os.path.join(folder, name)
                    z.write(full, os.path.relpath(full, work))
    print("Listo:", out)


if __name__ == "__main__":
    main()
