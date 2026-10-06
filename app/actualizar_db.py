"""Actualiza la base de datos de Comandia a la versión actual (v2.9).

Hace lo mismo que Comandia al iniciar, pero por separado y mostrando cada paso:
1. Respalda la base con mysqldump (si lo encuentra) en la carpeta `respaldos`.
2. Crea las tablas nuevas (bitácora) y agrega las columnas nuevas.
3. Verifica que no falte nada y lo informa.

Se puede ejecutar varias veces: lo que ya existe no se toca y no borra datos.
Uso:  python comandia_cmd.py actualizar_db            (lee la conexión de database.url)
      python comandia_cmd.py actualizar_db --sin-respaldo
"""
import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_FILE = os.path.join(BASE_DIR, "database.url")


def read_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url and os.path.exists(URL_FILE):
        with open(URL_FILE, encoding="utf-8") as handle:
            url = handle.readline().strip()
    return url


def backup(url, label: str = "antes-de-actualizar"):
    """Respaldo completo con mysqldump. Devuelve la ruta del archivo, o "" si no se pudo."""
    from app.respaldos import backup_name, dump_mysql
    folder = os.path.join(BASE_DIR, "respaldos")
    os.makedirs(folder, exist_ok=True)
    target = os.path.join(folder, backup_name(url, label, ".sql"))
    error = dump_mysql(url, target)
    if error:
        print(f"  El respaldo con mysqldump no se pudo hacer: {error}")
        return ""
    print(f"  Respaldo guardado en {target}")
    return target


def main() -> int:
    print("\n=== Actualizar la base de datos de Comandia a la versión actual ===\n")
    url_text = read_url()
    if not url_text:
        print("No encontré database.url. Abre primero iniciar.bat (o configurar-mysql.bat) para configurar MySQL.")
        return 1
    os.environ["DATABASE_URL"] = url_text
    sys.path.insert(0, BASE_DIR)

    from sqlalchemy import inspect
    from sqlalchemy.engine import make_url

    url = make_url(url_text)
    print(f"Base de datos: {url.get_backend_name()} · {url.host or ''} · {url.database}")

    from app import main as comandia  # usa DATABASE_URL

    try:
        with comandia.engine.connect():
            pass
    except Exception as exc:  # noqa: BLE001
        print("\nNO SE PUDO CONECTAR A LA BASE DE DATOS")
        print(f" {str(exc).splitlines()[0][:300]}")
        print(" Revisa que MySQL esté iniciado. Si cambiaste la clave, ejecuta configurar-mysql.bat")
        return 1

    if "--sin-respaldo" not in sys.argv and url.get_backend_name() == "mysql":
        print("\n1) Respaldo")
        if not backup(url):
            answer = input("  ¿Continuar SIN respaldo? Hazlo antes con MySQL Workbench si no estás seguro (s/N): ").strip().lower()
            if answer not in ("s", "si", "sí"):
                print("Actualización cancelada. No se cambió nada.")
                return 1

    before = inspect(comandia.engine)
    tables_before = set(before.get_table_names())
    cols_before = {t: {c["name"] for c in before.get_columns(t)} for t in tables_before}

    print("\n2) Actualizando estructura")
    comandia.Base.metadata.create_all(comandia.engine)
    comandia.add_missing_columns(comandia.engine)
    comandia.add_missing_indexes(comandia.engine)
    db = comandia.SessionLocal()
    try:
        comandia.migrate_users(db)
    finally:
        db.close()

    after = inspect(comandia.engine)
    tables_after = set(after.get_table_names())
    changes = [f"  + tabla nueva: {t}" for t in sorted(tables_after - tables_before)]
    missing = []
    for table, column, _ddl in comandia.NEW_COLUMNS:
        if table not in tables_after:
            continue
        now = {c["name"] for c in after.get_columns(table)}
        if column not in now:
            missing.append(f"{table}.{column}")
        elif table in cols_before and column not in cols_before[table]:
            changes.append(f"  + columna nueva: {table}.{column}")
    for table in comandia.Base.metadata.tables:
        if table not in tables_after:
            missing.append(f"tabla {table}")

    print("\n".join(changes) if changes else "  La base ya estaba al día: no hubo nada que agregar.")
    if missing:
        print("\n3) FALTAN CAMBIOS: " + ", ".join(missing))
        print("   Revisa que el usuario de MySQL tenga permiso ALTER y CREATE, o ejecuta actualizar-db.sql en MySQL Workbench.")
        return 1
    print("\n3) Verificación correcta: la base de datos está lista para esta versión de Comandia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
