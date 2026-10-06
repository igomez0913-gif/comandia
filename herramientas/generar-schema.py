#!/usr/bin/env python3
"""Genera schema-completo.sql (base «comandia», MySQL/MariaDB) a partir de los modelos de Comandia: todas las tablas, llaves, únicos e índices.
Se corre cada vez que cambian los modelos:  python herramientas/generar-schema.py"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATABASE_URL", "sqlite://")
from sqlalchemy.dialects import mysql  # noqa: E402
from sqlalchemy.schema import CreateIndex, CreateTable  # noqa: E402

from app import main  # noqa: E402

dialect = mysql.dialect()
out = [f"""-- Comandia {main.app.version} · Esquema COMPLETO para MySQL 8 / MariaDB 10.4+ (generado de los modelos; no lo edites a mano).
-- Crea la base, el usuario, las {len(main.Base.metadata.tables)} tablas con sus llaves foráneas, únicos e índices.
-- Úsalo en una base NUEVA y vacía (una sola vez). Comandia, al iniciar, agrega los datos iniciales (usuario administrador, empresa, catálogos).
-- Si ya tienes una base de una versión anterior NO uses este archivo: usa actualizar-db.bat / actualizar-db.sql.
--
-- Cambia la clave del usuario antes de ejecutar. En MySQL Workbench: abre el archivo y pulsa el rayo (Ejecutar todo).

CREATE DATABASE IF NOT EXISTS comandia CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'comandia'@'%' IDENTIFIED BY 'cambia-esta-clave';
CREATE USER IF NOT EXISTS 'comandia'@'localhost' IDENTIFIED BY 'cambia-esta-clave';
GRANT ALL PRIVILEGES ON comandia.* TO 'comandia'@'%';
GRANT ALL PRIVILEGES ON comandia.* TO 'comandia'@'localhost';
FLUSH PRIVILEGES;

USE comandia;
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;
"""]
for table in main.Base.metadata.sorted_tables:
    out.append(f"-- {table.name}")
    stmt = str(CreateTable(table, if_not_exists=True).compile(dialect=dialect)).strip()
    out.append(stmt + " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;\n")
    for index in sorted(table.indexes, key=lambda i: i.name or ""):
        out.append(str(CreateIndex(index).compile(dialect=dialect)).strip() + ";")
    if table.indexes:
        out.append("")
have = {i.name for t in main.Base.metadata.tables.values() for i in t.indexes}
extra = [(n, t, c) for n, t, c in main.NEW_INDEXES if n not in have]  # los que ya están en los modelos ya salieron arriba
if extra:
    out.append("-- Índices extra para listados y reportes por fecha")
    out += [f"CREATE INDEX {n} ON {t} ({c});" for n, t, c in extra]
out.append("\nSET FOREIGN_KEY_CHECKS = 1;\n")
with open(os.path.join(ROOT, "schema-completo.sql"), "w", encoding="utf-8", newline="\n") as handle:
    handle.write("\n".join(out))
print("schema-completo.sql:", len(main.Base.metadata.tables), "tablas")
