"""Respaldos de Comandia: con mysqldump si está instalado; si no, un respaldo propio en JSON comprimido.

- MySQL: archivo .sql de mysqldump (se restaura con MySQL Workbench › Data Import o con `mysql`).
- MySQL sin mysqldump: archivo .json.gz propio (se restaura con `python comandia_cmd.py restaurar archivo`).
- SQLite (solo pruebas/demo): copia consistente del archivo .db.

Este módulo no importa app.main para poder usarse desde los scripts sin arrancar el servidor.
"""
import glob
import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Numeric

BACKUP_EXTENSIONS = (".sql", ".json.gz", ".db")
SAFE_NAME = re.compile(r"^[\w.\-]+$")
STAMP = re.compile(r"-(\d{8}-\d{6})(?:\.|$)")


def find_mysqldump() -> str:
    found = shutil.which("mysqldump")
    if found:
        return found
    patterns = [
        r"C:\Program Files\MySQL\MySQL Server *\bin\mysqldump.exe",
        r"C:\Program Files (x86)\MySQL\MySQL Server *\bin\mysqldump.exe",
        r"C:\xampp\mysql\bin\mysqldump.exe",
    ]
    for pattern in patterns:
        hits = sorted(glob.glob(pattern))
        if hits:
            return hits[-1]
    return ""


def _stamp(when=None) -> str:
    return (when or datetime.now()).strftime("%Y%m%d-%H%M%S")


def backup_name(url, label: str, ext: str, when=None) -> str:
    """Nombre del respaldo; `when` es la hora local del negocio (la misma con la que se decide si ya se respaldó hoy)."""
    base = os.path.splitext(os.path.basename(url.database or "comandia"))[0] or "comandia"
    base = re.sub(r"[^\w-]", "_", base)
    return f"{base}-{label}-{_stamp(when)}{ext}"


def dump_mysql(url, target: str) -> str:
    """Respaldo con mysqldump. Devuelve "" si salió bien o el motivo del error."""
    dump = find_mysqldump()
    if not dump:
        return "no se encontró mysqldump"
    env = dict(os.environ, MYSQL_PWD=url.password or "")  # la clave no queda visible en la línea de comandos
    cmd = [dump, "-h", url.host or "localhost", "-P", str(url.port or 3306), "-u", url.username or "root",
           "--single-transaction", "--routines", "--default-character-set=utf8mb4", url.database]
    try:
        with open(target, "wb") as out:
            result = subprocess.run(cmd, stdout=out, stderr=subprocess.PIPE, env=env, timeout=1800)
    except Exception as exc:  # noqa: BLE001
        result, error = None, str(exc)
    else:
        error = result.stderr.decode("utf-8", "replace").strip()[:300] if result.returncode != 0 else ""
    if error or not os.path.exists(target) or os.path.getsize(target) == 0:
        try:
            os.remove(target)
        except OSError:
            pass
        return error or "el respaldo quedó vacío"
    return ""


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def dump_json(engine, metadata, target: str):
    """Respaldo propio: todas las tablas de Comandia en un JSON comprimido."""
    data = {"comandia_backup": 1, "created": datetime.now().isoformat(timespec="seconds"), "tables": {}}
    with engine.connect() as conn:
        for table in metadata.sorted_tables:
            rows = conn.execute(table.select().order_by(*table.primary_key.columns)).mappings().all()
            data["tables"][table.name] = [{k: _plain(v) for k, v in row.items()} for row in rows]
    with gzip.open(target, "wt", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)


def dump_sqlite(engine, target: str):
    source = engine.url.database
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)  # copia consistente aunque el sistema esté en uso
    finally:
        dst.close()
        src.close()


def make_backup(engine, metadata, folder: str, label: str, when=None):
    """Hace un respaldo en `folder`. Devuelve (ruta, método). Lanza RuntimeError si no se pudo."""
    os.makedirs(folder, exist_ok=True)
    url = engine.url
    backend = url.get_backend_name()
    if backend == "sqlite":
        target = os.path.join(folder, backup_name(url, label, ".db", when))
        dump_sqlite(engine, target)
        return target, "copia SQLite"
    if backend == "mysql":
        target = os.path.join(folder, backup_name(url, label, ".sql", when))
        if not dump_mysql(url, target):
            return target, "mysqldump"
    target = os.path.join(folder, backup_name(url, label, ".json.gz", when))
    dump_json(engine, metadata, target)
    return target, "respaldo propio de Comandia"


def list_backups(folder: str) -> list:
    if not os.path.isdir(folder):
        return []
    out = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path) and name.endswith(BACKUP_EXTENSIONS) and SAFE_NAME.match(name):
            stat = os.stat(path)
            match = STAMP.search(name)  # la fecha del nombre manda; si no hay, la del archivo
            created = datetime.strptime(match.group(1), "%Y%m%d-%H%M%S") if match else datetime.fromtimestamp(stat.st_mtime)
            out.append({"name": name, "size": stat.st_size, "created": created.isoformat(timespec="seconds"), "auto": "-auto-" in name})
    return sorted(out, key=lambda r: (r["created"], r["name"]), reverse=True)


def prune_auto(folder: str, keep: int, protect: str = "") -> int:
    """Borra los respaldos automáticos más viejos y deja `keep`. Los manuales y `protect` no se tocan."""
    autos = [r for r in list_backups(folder) if r["auto"] and r["name"] != os.path.basename(protect)]
    removed = 0
    for row in autos[max(keep, 1) - (1 if protect else 0):]:
        try:
            os.remove(os.path.join(folder, row["name"]))
            removed += 1
        except OSError:
            pass
    return removed


def _typed(column, value):
    if value is None:
        return None
    if isinstance(column.type, DateTime):
        return datetime.fromisoformat(value)
    if isinstance(column.type, Date):
        return date.fromisoformat(value[:10])
    if isinstance(column.type, Numeric):
        return Decimal(str(value))
    return value


def restore_json(engine, metadata, path: str, force: bool = False) -> dict:
    """Carga un respaldo .json.gz en la base. Si la base ya tiene datos, solo continúa con force=True (y los reemplaza)."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data = json.load(handle)
    if data.get("comandia_backup") != 1:
        raise ValueError("El archivo no es un respaldo de Comandia")
    metadata.create_all(engine)
    counts = {}
    with engine.begin() as conn:
        mysql = engine.url.get_backend_name() == "mysql"
        has_data = any(conn.execute(t.select().limit(1)).first() for t in metadata.sorted_tables)
        if has_data and not force:
            raise ValueError("La base de datos ya tiene información. Usa --forzar para reemplazarla con el respaldo.")
        if mysql:
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        for table in reversed(metadata.sorted_tables):
            conn.execute(table.delete())
        for table in metadata.sorted_tables:
            rows = data["tables"].get(table.name, [])
            cols = {c.name: c for c in table.columns}
            clean = [{k: _typed(cols[k], v) for k, v in row.items() if k in cols} for row in rows]
            for i in range(0, len(clean), 500):
                conn.execute(table.insert(), clean[i:i + 500])
            counts[table.name] = len(clean)
        if mysql:
            conn.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")
    return counts
