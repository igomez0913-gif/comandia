#!/usr/bin/env python3
"""Generador de claves de Comandia. SOLO PARA EL DESARROLLADOR: no se entrega a los clientes.

Uso sin argumentos: menú. También por comandos:

  generador-de-claves.py crear-llaves
  generador-de-claves.py emitir --cliente "Ferretería Toty" --instalacion ABCD-EFGH \\
        --plan profesional --modulos whatsapp --bodegas 5   (perpetua; para una con vencimiento agrega --meses 12 o --vence AAAA-MM-DD)
  generador-de-claves.py listar
  generador-de-claves.py verificar ABCDE-FGHIJ-...

La llave PRIVADA queda en herramientas/llaves/privada.pem: es lo más valioso. Quien la tenga puede emitir claves.
Guárdala con copia en un lugar seguro y nunca la subas al repositorio ni la incluyas en un zip de cliente.
"""
import argparse
import csv
import os
import sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
try:
    from app import licencia  # dentro del proyecto
except ImportError:
    import licencia  # copia suelta junto a este archivo

PRIVATE = os.path.join(HERE, "llaves", "privada.pem")
LOG = os.path.join(HERE, "claves-emitidas.csv")
APP_PUBLIC = os.path.join(ROOT, "app", "llave_publica.pem")
PUBLIC = APP_PUBLIC if os.path.isdir(os.path.dirname(APP_PUBLIC)) else os.path.join(HERE, "llave_publica.pem")


def fail(msg):
    print(f"\nERROR: {msg}")
    sys.exit(1)


def crear_llaves(force=False):
    if os.path.exists(PRIVATE) and not force:
        fail("Ya existe una llave privada. Si la cambias, TODAS las claves emitidas dejan de servir. Usa --forzar solo si estás seguro.")
    os.makedirs(os.path.dirname(PRIVATE), exist_ok=True)
    private_pem, public_pem = licencia.new_private_key_pem()
    with open(PRIVATE, "wb") as handle:
        handle.write(private_pem)
    try:
        os.chmod(PRIVATE, 0o600)
    except OSError:
        pass
    with open(PUBLIC, "wb") as handle:
        handle.write(public_pem)
    embedded = os.path.join(os.path.dirname(PUBLIC), "llave_embebida.py")  # copia dentro del código: borrar el .pem no apaga los candados
    with open(embedded, "w", encoding="utf-8", newline="\n") as handle:
        handle.write('"""Llave pública de licencias incluida en el propio código (la escribe herramientas/generador-de-claves.py crear-llaves).\n\n'
                     'Así, borrar llave_publica.pem no apaga los candados. Vacía = sin licencias (desarrollo)."""\n'
                     'PUBLIC_PEM = """' + public_pem.decode() + '"""\n')
    print(f"Llave pública embebida: {embedded}  → también súbela al repositorio.")
    print(f"Llave PRIVADA: {PRIVATE}\n  → GUÁRDALA con copia segura. No la compartas ni la subas al repositorio.")
    print(f"Llave PÚBLICA: {PUBLIC}\n  → Debe ir dentro del sistema que entregas (app/llave_publica.pem). Súbela al repositorio.")


def _private():
    if not os.path.exists(PRIVATE):
        fail("Todavía no hay llaves. Ejecuta primero: crear-llaves")
    with open(PRIVATE, "rb") as handle:
        return handle.read()


def resolver_modulos(plan, extras):
    """Módulos de un paquete (basico, profesional, empresarial, todo) más los extras sueltos; acepta los nombres anteriores."""
    plan = licencia.ALIASES.get((plan or "").strip().lower(), (plan or "").strip().lower())
    if plan and plan not in licencia.PLANS:
        fail(f"Paquete desconocido: {plan}. Los válidos son: {', '.join(licencia.PLANS)}")
    names = list(licencia.PLANS[plan]) if plan and plan != "todo" else []
    for raw in extras:
        name = licencia.ALIASES.get(raw.strip().lower(), raw.strip().lower())
        if name:
            names.append(name)
    if plan == "todo" or "todo" in names:
        return ["todo"]
    return list(dict.fromkeys(names))


def emitir(cliente, instalacion, modulos, limites, vence):
    modulos = [licencia.ALIASES.get(m, m) for m in modulos]
    unknown = [m for m in modulos if m not in licencia.MODULES and m != "todo"]
    if unknown:
        fail(f"Módulos desconocidos: {', '.join(unknown)}. Los válidos son: {', '.join(licencia.MODULES)} (o el paquete «todo»)")
    try:
        licencia.install_bytes(instalacion)
    except licencia.LicenseError as exc:
        fail(str(exc))
    key_id = os.urandom(4)
    payload = licencia.pack(key_id, instalacion, date.today(), vence, modulos, limites)
    key = licencia.sign(_private(), payload)
    pub = None
    if os.path.exists(PUBLIC):
        from ecdsa import VerifyingKey
        pub = VerifyingKey.from_pem(open(PUBLIC, "rb").read())
        licencia.read_key(key, pub)  # comprobación de ida y vuelta: la clave emitida se valida con la llave pública
    new = not os.path.exists(LOG)
    with open(LOG, "a", newline="", encoding="utf-8-sig") as handle:
        w = csv.writer(handle)
        if new:
            w.writerow(["fecha", "cliente", "instalacion", "id_clave", "modulos", "bodegas", "tiendas", "usuarios", "cajas", "vence", "clave"])
        w.writerow([date.today().isoformat(), cliente, instalacion.upper(), key_id.hex().upper(), ",".join(modulos), limites.get("bodegas", 0),
                    limites.get("tiendas", 0), limites.get("usuarios", 0), limites.get("cajas", 0), vence.isoformat() if vence else "", key])
    print(f"\nClave para {cliente} (instalación {instalacion.upper()}):\n\n{key}\n")
    print(f"Paquete: {licencia.PLAN_LABELS[licencia.plan_of(modulos, 'todo' in modulos)]}")
    print(f"Módulos: {'TODOS (los de hoy y los futuros)' if 'todo' in modulos else ', '.join(modulos) or 'ninguno (Básico)'} · vence: {vence.strftime('%d/%m/%Y') if vence else 'sin vencimiento'} · id {key_id.hex().upper()}")
    print(f"Registrada en {LOG}")


def listar():
    if not os.path.exists(LOG):
        print("Todavía no has emitido claves.")
        return
    with open(LOG, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            print(f"{row['fecha']}  {row['id_clave']}  {row['cliente']:<28} {row['instalacion']}  {row['modulos']}  vence: {row['vence'] or '—'}")


def verificar(key):
    if not os.path.exists(PUBLIC):
        fail("No encuentro la llave pública.")
    from ecdsa import VerifyingKey
    try:
        info = licencia.read_key(key, VerifyingKey.from_pem(open(PUBLIC, "rb").read()))
    except licencia.LicenseError as exc:
        fail(str(exc))
    print(f"Clave AUTÉNTICA · id {info['key_id']} · instalación {info['install']} · emitida {info['issued']} · vence {info['expires'] or 'nunca'}")
    print(f"Paquete: {licencia.PLAN_LABELS[licencia.plan_of(info['modules'], info['all'])]} · módulos: " + ("TODOS (presentes y futuros)" if info["all"] else ", ".join(info["modules"]) or "ninguno"))
    print(f"Límites (0 = sin límite): {info['limits']}")


def ask(text, default=""):
    value = input(f"{text}{f' [{default}]' if default else ''}: ").strip()
    return value or default


def parse_date(text):
    return datetime.strptime(text, "%Y-%m-%d").date()


def add_months(d, n):
    month = d.month - 1 + n
    year, month = d.year + month // 12, month % 12 + 1
    return date(year, month, min(d.day, [31, 29 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]))


def menu():
    while True:
        print("\n=== Generador de claves de Comandia ===\n 1) Crear las llaves (una sola vez)\n 2) Emitir una clave\n 3) Ver claves emitidas\n 4) Verificar una clave\n 0) Salir")
        choice = ask("Elige")
        if choice == "1":
            crear_llaves()
        elif choice == "2":
            cliente = ask("Cliente (nombre)")
            instalacion = ask("Código de instalación que te envió el cliente (ABCD-EFGH)")
            opciones = list(licencia.PLAN_LABELS)  # basico, profesional, empresarial, todo
            for n, name in enumerate(opciones, 1):
                print(f"  {n}) {licencia.PLAN_LABELS[name]:<14} " + ("todos los módulos, presentes y futuros" if name == "todo" else ", ".join(licencia.PLANS[name]) or "solo lo incluido: facturación, inventario, clientes, POS, reportes SAR (sin módulos de pago)"))
            print(f"  {len(opciones) + 1}) Personalizado    elegir módulos sueltos")
            eleccion = ask("Paquete (número)", "2")
            plan = opciones[int(eleccion) - 1] if eleccion.isdigit() and 1 <= int(eleccion) <= len(opciones) else ""
            extras = ""
            if not plan or plan != "todo":
                print("Módulos disponibles:", ", ".join(licencia.MODULES))
                extras = ask("Módulos extra, separados por coma (vacío = ninguno)", "")
            modulos = resolver_modulos(plan, [m for m in extras.split(",") if m.strip()])
            limites = {"bodegas": int(ask("Máximo de bodegas (0 = sin límite)", "0")), "tiendas": int(ask("Máximo de tiendas (0 = sin límite)", "0")),
                       "usuarios": int(ask("Máximo de usuarios (0 = sin límite)", "0")), "cajas": int(ask("Máximo de cajas (0 = sin límite)", "0"))}
            meses = int(ask("Meses de vigencia (0 = perpetua, sin vencimiento)", "0"))
            emitir(cliente, instalacion, modulos, limites, add_months(date.today(), meses) if meses else None)
        elif choice == "3":
            listar()
        elif choice == "4":
            verificar(ask("Clave"))
        elif choice == "0":
            return


def main():
    if len(sys.argv) == 1:
        return menu()
    ap = argparse.ArgumentParser(description="Generador de claves de Comandia")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("crear-llaves"); c.add_argument("--forzar", action="store_true")
    e = sub.add_parser("emitir")
    e.add_argument("--cliente", required=True); e.add_argument("--instalacion", required=True)
    e.add_argument("--plan", default="", help="paquete: basico, profesional, empresarial o todo (basico = sin módulos de pago; todo = todos, presentes y futuros)")
    e.add_argument("--modulos", default="", help="módulos sueltos, separados por coma (se suman al paquete): " + ", ".join(licencia.MODULES))
    for name in ("bodegas", "tiendas", "usuarios", "cajas"):
        e.add_argument(f"--{name}", type=int, default=0, help="0 = sin límite")
    g = e.add_mutually_exclusive_group()
    g.add_argument("--vence", help="AAAA-MM-DD"); g.add_argument("--meses", type=int); g.add_argument("--sin-vencimiento", action="store_true")
    sub.add_parser("listar")
    v = sub.add_parser("verificar"); v.add_argument("clave")
    a = ap.parse_args()
    if a.cmd == "crear-llaves":
        crear_llaves(a.forzar)
    elif a.cmd == "emitir":
        modulos = resolver_modulos(a.plan, a.modulos.split(","))
        if not modulos and not a.plan:
            fail("Indica --plan (basico, profesional, empresarial o todo) y/o --modulos")
        vence = None if a.sin_vencimiento else parse_date(a.vence) if a.vence else add_months(date.today(), a.meses) if a.meses else None  # sin fecha = perpetua
        emitir(a.cliente, a.instalacion, modulos, {"bodegas": a.bodegas, "tiendas": a.tiendas, "usuarios": a.usuarios, "cajas": a.cajas}, vence)
    elif a.cmd == "listar":
        listar()
    else:
        verificar(a.clave)


if __name__ == "__main__":
    main()
