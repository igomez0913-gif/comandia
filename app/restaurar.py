"""Restaura un respaldo propio de Comandia (.json.gz) en la base configurada en database.url.

Uso:  python comandia_cmd.py restaurar respaldos\\comandia-auto-20261003-120000.json.gz
      python comandia_cmd.py restaurar archivo.json.gz --forzar     (reemplaza los datos actuales)

Los respaldos .sql (hechos con mysqldump) se restauran con MySQL Workbench › Server › Data Import.
Cierra Comandia antes de restaurar.
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    force = "--forzar" in sys.argv
    if not args:
        print(__doc__)
        return 1
    path = args[0]
    if not os.path.exists(path):
        print(f"No encontré el archivo {path}")
        return 1
    if path.endswith(".sql"):
        print("Ese respaldo es de mysqldump: restáuralo con MySQL Workbench › Server › Data Import.")
        return 1
    sys.path.insert(0, BASE_DIR)
    from app.actualizar_db import read_url
    url = read_url()
    if not url:
        print("No encontré database.url. Configura MySQL primero (configurar-mysql.bat).")
        return 1
    os.environ["DATABASE_URL"] = url
    from app import main as comandia
    from app.respaldos import restore_json
    try:
        counts = restore_json(comandia.engine, comandia.Base.metadata, path, force=force)
    except ValueError as exc:
        print(exc)
        return 1
    total = sum(counts.values())
    print(f"Respaldo restaurado: {total} registros en {len(counts)} tablas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
