"""Resumen de la base de datos para comparar ANTES y DESPUÉS de actualizar (solo lee, no cambia nada).

Uso:  python comandia_cmd.py resumen_db            (usa database.url, igual que Comandia)
      python comandia_cmd.py resumen_db > antes.txt
Si los números de antes y después coinciden (documentos, totales, cobros, existencias, clientes, productos),
la actualización no tocó los datos. Funciona con bases de cualquier versión desde la 2.3.
"""
import os
import sys

from sqlalchemy import create_engine, text

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def database_url() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    try:
        with open(os.path.join(BASE_DIR, "database.url"), encoding="utf-8-sig") as handle:
            return handle.readline().strip()
    except OSError:
        return ""


QUERIES = [
    ("Documentos (facturas, notas, cotizaciones)", "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM documents"),
    ("  · facturas", "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM documents WHERE kind = 'factura'"),
    ("  · notas de crédito", "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM documents WHERE kind = 'nota'"),
    ("  · cotizaciones", "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM documents WHERE kind = 'cotizacion'"),
    ("Cobros", "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM payments"),
    ("Compras", "SELECT COUNT(*), COALESCE(SUM(total), 0) FROM purchases"),
    ("Existencias (renglones, unidades)", "SELECT COUNT(*), COALESCE(SUM(qty), 0) FROM stocks"),
    ("Productos", "SELECT COUNT(*), 0 FROM products"),
    ("Clientes", "SELECT COUNT(*), 0 FROM clients"),
    ("Proveedores", "SELECT COUNT(*), 0 FROM suppliers"),
    ("Usuarios", "SELECT COUNT(*), 0 FROM users"),
    ("Bodegas", "SELECT COUNT(*), 0 FROM warehouses"),
    ("Cuentas de banco (saldo)", "SELECT COUNT(*), COALESCE(SUM(balance), 0) FROM banks"),
]


def main() -> int:
    url = database_url()
    if not url:
        print("No encontré database.url. Ejecuta configurar-mysql.bat o define DATABASE_URL.")
        return 1
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 5} if url.startswith("mysql") else {})
        conn = engine.connect()
    except Exception as exc:  # noqa: BLE001
        print(f"No se pudo conectar a la base de datos: {str(exc).splitlines()[0][:200]}")
        return 1
    print(f"Resumen de {engine.url.database or engine.url.render_as_string(hide_password=True)}")
    with conn:
        for label, sql in QUERIES:
            try:
                count, total = conn.execute(text(sql)).one()
                print(f"{label:<46}{int(count):>8}   {float(total):>16,.2f}" if float(total) else f"{label:<46}{int(count):>8}")
            except Exception:  # noqa: BLE001
                print(f"{label:<46}  (tabla no existe en esta versión)")
        try:
            rows = conn.execute(text("SELECT doc_type, establishment, emission_point, current, range_to, active FROM cai_ranges ORDER BY id")).all()
            print("CAI (tipo, establecimiento, punto, próximo número, hasta, activo):")
            for r in rows:
                print(f"  {r[0]} {r[1]}-{r[2]}  próximo {int(r[3])} de {int(r[4])}  {'activo' if r[5] else 'inactivo'}")
        except Exception:  # noqa: BLE001
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
