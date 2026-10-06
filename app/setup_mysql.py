"""Asistente de conexión a MySQL para Comandia.

Pregunta servidor, usuario y clave, prueba la conexión, crea la base si no existe
y guarda la cadena de conexión en el archivo `database.url` (junto a iniciar.bat).
Uso interactivo:  python comandia_cmd.py setup_mysql
Uso por parámetros: python comandia_cmd.py setup_mysql --host localhost --port 3306 --user root --password X --db comandia
"""
import argparse
import getpass
import os
import re
import sys
from urllib.parse import quote_plus

import pymysql

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL_FILE = os.path.join(BASE_DIR, "database.url")


def ask(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    prompt = f"{label}{suffix}: "
    value = getpass.getpass(prompt) if secret else input(prompt)
    return (value or default) if secret else (value.strip() or default)  # Enter = el valor por defecto


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--db")
    a = ap.parse_args()
    interactive = not any(v is not None for v in vars(a).values())

    print("\n=== Conexión de Comandia a MySQL ===")
    print("Usa el usuario con el que entras a MySQL (por ejemplo root). Si ya tienes una base creada, escribe su nombre;")
    print("si no existe, se creará sola (necesita permiso para crear bases).\n")
    host = a.host or (ask("Servidor", "localhost") if interactive else "localhost")
    port = a.port or (int(ask("Puerto", "3306") or 3306) if interactive else 3306)
    user = a.user or (ask("Usuario", "root") if interactive else "root")
    password = a.password if a.password is not None else (ask("Clave de ese usuario (no se ve al escribir)", "", secret=True) if interactive else "")
    db = a.db or (ask("Nombre de la base de datos", "comandia") if interactive else "comandia")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,64}", db):
        print("\nERROR: el nombre de la base solo puede tener letras, números y guion bajo.")
        return 1

    try:
        conn = pymysql.connect(host=host, port=port, user=user, password=password, charset="utf8mb4", connect_timeout=8)
    except pymysql.err.OperationalError as exc:
        code = exc.args[0] if exc.args else 0
        print(f"\nNO SE PUDO CONECTAR a MySQL en {host}:{port} -> {exc}")
        if code == 1045:
            print("  La clave o el usuario no son correctos.")
        elif code in (2003, 2002, 2005):
            print("  MySQL no responde. Revisa que el servicio esté iniciado (Servicios de Windows > MySQL80) y el puerto.")
        return 1
    try:
        with conn.cursor() as cur:
            try:
                cur.execute(f"USE `{db}`")  # si ya existe y tienes acceso, no hace falta permiso para crear bases
            except pymysql.err.MySQLError:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                cur.execute(f"USE `{db}`")
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
    except pymysql.err.MySQLError as exc:
        print(f"\nNo se pudo crear/usar la base «{db}»: {exc}")
        print("  Crea la base a mano (CREATE DATABASE ...) o usa un usuario con más permisos.")
        return 1
    finally:
        conn.close()

    url = f"mysql+pymysql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{db}"
    with open(URL_FILE, "w", encoding="ascii", newline="") as handle:
        handle.write(url + "\n")
    print(f"\nListo: conectado a MySQL {version}. Base «{db}» lista.")
    print("Datos guardados en database.url (contiene tu clave: no compartas ese archivo).")
    if interactive:
        print("Las tablas se crean solas la primera vez que inicias Comandia.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
