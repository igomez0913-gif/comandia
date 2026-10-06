"""Licencias de Comandia: activación de módulos con una clave firmada.

La clave la emite el desarrollador con una llave PRIVADA (herramientas/generador-de-claves.py, que no se entrega a los
clientes). El sistema solo trae la llave PÚBLICA (app/llave_publica.pem), así que puede comprobar que una clave es
auténtica pero no fabricarla, y todo se valida sin internet.

La clave lleva: el código de instalación del cliente (solo sirve en esa instalación), la fecha de emisión y de
vencimiento, los módulos activos y los límites (bodegas, usuarios, cajas; el byte de tiendas queda reservado). Son 84 bytes (20 de datos y 64 de
firma ECDSA P-256) escritos en base32 y agrupados de a 5: `ABCDE-FGHIJ-...`.

Planes: Básico (sin clave), Profesional, Empresarial y Todo; cada clave lleva la lista de módulos y los límites (ver PLANS).
Reglas (son obligaciones fiscales, por eso NUNCA se bloquea la facturación, el respaldo manual, los reportes del SAR ni el acceso a los datos):
- Sin llave pública en la instalación no se aplica ningún candado (todo abierto).
- Los primeros 30 días desde la primera ejecución todo está activo (prueba).
- Después, cada módulo necesita una clave válida y vigente; lo que ya existe se conserva, solo no se puede agregar más.
"""
import base64
import hashlib
import os
import re
import secrets
import struct
from datetime import date, timedelta
from typing import Optional

from ecdsa import BadSignatureError, NIST256p, SigningKey, VerifyingKey

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_KEY_FILE = os.environ.get("COMANDIA_LLAVE_PUBLICA") or os.path.join(BASE_DIR, "app", "llave_publica.pem")

TRIAL_DAYS = 30
VERSION = 1
EPOCH = date(2024, 1, 1)
FORMAT = ">B4s5sHHHBBBB"  # versión, id de la clave, instalación, emisión, vencimiento, módulos, bodegas, tiendas, usuarios, cajas
PAYLOAD_SIZE = struct.calcsize(FORMAT)  # 20
SIGNATURE_SIZE = 64
UNLIMITED = 0  # en los límites, 0 = sin límite

# El orden es el de los bits de la clave: no se reordena, solo se agregan al final (hasta 15; el bit 16 es «todo»).
MODULES = ["multi_warehouse", "offline", "importar_excel", "turnos_caja", "reports", "advanced_credit",
           "reabastecimiento", "docs_fiscales", "etiquetas", "backup", "api", "email", "compras"]
ALL_BIT = 15  # «todo»: cada módulo de hoy y los que se agreguen en el futuro
MODULE_LABELS = {
    "multi_warehouse": "Multi-bodega y traslados entre bodegas",
    "offline": "Modo sin conexión con sincronización",
    "importar_excel": "Importar productos desde Excel",
    "turnos_caja": "Turnos de caja",
    "reports": "Reportes avanzados: rentabilidad y ventas por rango de fechas",
    "advanced_credit": "Gestión avanzada de crédito y cobranza",
    "reabastecimiento": "Reabastecimiento sugerido y órdenes de compra",
    "docs_fiscales": "Notas de débito",
    "etiquetas": "Etiquetas y códigos de barras",
    "backup": "Respaldos automáticos programados y copia secundaria",
    "api": "API REST para integraciones (llaves de acceso de lectura)",
    "email": "Envío de facturas y documentos por correo",
    "compras": "Compras completas: órdenes, recepción, cuentas por pagar y devoluciones",
}
MODULE_NAMES = {  # nombre corto, para los avisos
    "multi_warehouse": "Multi-bodega", "offline": "Modo sin conexión", "importar_excel": "Importar desde Excel",
    "turnos_caja": "Turnos de caja", "reports": "Reportes avanzados", "advanced_credit": "Crédito avanzado", "reabastecimiento": "Reabastecimiento",
    "docs_fiscales": "Notas de débito", "etiquetas": "Etiquetas y códigos de barras", "backup": "Respaldos automáticos", "api": "API REST",
    "email": "Correo electrónico", "compras": "Compras",
}
# Módulos con candado. Los demás vienen incluidos en toda instalación (turnos y cierre de caja, facturación, inventario, clientes,
# punto de venta, usuarios, reportes SAR y registro de compras recibidas de contado), por eso no se bloquean.
ENFORCED = set(MODULES) - {"turnos_caja"}
INCLUDED = {"turnos_caja"}
# Paquetes: cada uno agrega a lo anterior. «basico» no necesita clave.
PLAN_BASE = ["multi_warehouse", "reports", "backup", "api", "importar_excel", "etiquetas"]
PLANS = {
    "basico": [],
    "profesional": PLAN_BASE,
    "empresarial": PLAN_BASE + ["email", "offline", "compras", "advanced_credit", "reabastecimiento", "docs_fiscales"],
    "todo": list(MODULES),
}
PLAN_LABELS = {"basico": "Básico", "profesional": "Profesional", "empresarial": "Empresarial", "todo": "Todo incluido"}
ALIASES = {"multi_bodega": "multi_warehouse", "ventas_offline": "offline", "rentabilidad": "reports", "credito": "advanced_credit", "reportes": "reports",
           "respaldos": "backup", "correo": "email", "all": "todo"}  # nombres anteriores o alternos que el generador acepta


def plan_of(modules, all_flag: bool = False) -> str:
    """Nombre del paquete más alto que cubre los módulos de la clave (para mostrarlo; lo que vale son los módulos)."""
    have = set(modules or [])
    if all_flag or set(MODULES) <= have:
        return "todo"
    for name in ("empresarial", "profesional"):
        if set(PLANS[name]) <= have:
            return name
    return "basico"


ALPHABET_FIX = str.maketrans({"0": "O", "1": "I", "8": "B", "9": "G"})


class LicenseError(Exception):
    """Clave inválida; el mensaje se le puede mostrar al usuario."""


def public_key() -> Optional[VerifyingKey]:
    """Llave pública: el archivo (o la variable de entorno) y, si falta, la que lleva el código (`llave_embebida.py`)."""
    try:
        with open(PUBLIC_KEY_FILE, "rb") as handle:
            return VerifyingKey.from_pem(handle.read())
    except (OSError, ValueError):
        pass
    try:
        from app import llave_embebida
        return VerifyingKey.from_pem(llave_embebida.PUBLIC_PEM.encode()) if llave_embebida.PUBLIC_PEM.strip() else None
    except (ImportError, ValueError):
        return None


# ───────── código de instalación ─────────
def new_install_id() -> str:
    """40 bits al azar en base32: «ABCD-EFGH». Se guarda una vez en la base de datos."""
    raw = base64.b32encode(secrets.token_bytes(5)).decode()
    return f"{raw[:4]}-{raw[4:]}"


def install_bytes(install_id: str) -> bytes:
    clean = re.sub(r"[^A-Za-z2-7]", "", (install_id or "").translate(ALPHABET_FIX).upper())
    if len(clean) != 8:
        raise LicenseError("El código de instalación debe tener 8 letras y números (por ejemplo ABCD-EFGH)")
    return base64.b32decode(clean)


# ───────── empaquetar y firmar (el desarrollador firma; la app solo lee y comprueba) ─────────
def pack(key_id: bytes, install_id: str, issued: date, expires: Optional[date], modules, limits: dict) -> bytes:
    wanted = {ALIASES.get(m, m) for m in modules}
    mask = sum(1 << i for i, m in enumerate(MODULES) if m in wanted)
    if "todo" in wanted:
        mask = (1 << ALL_BIT) | sum(1 << i for i in range(len(MODULES)))  # «todo» incluye lo que se agregue más adelante
    days = lambda d: 0 if d is None else (d - EPOCH).days  # noqa: E731
    return struct.pack(FORMAT, VERSION, key_id, install_bytes(install_id), days(issued), days(expires), mask,
                       limits.get("bodegas", UNLIMITED), limits.get("tiendas", UNLIMITED), limits.get("usuarios", UNLIMITED), limits.get("cajas", UNLIMITED))


def sign(private_pem: bytes, payload: bytes) -> str:
    sk = SigningKey.from_pem(private_pem)
    signature = sk.sign_deterministic(payload, hashfunc=hashlib.sha256)  # 64 bytes crudos (r y s)
    return format_key(payload + signature)


def format_key(raw: bytes) -> str:
    text = base64.b32encode(raw).decode().rstrip("=")
    return "-".join(text[i:i + 5] for i in range(0, len(text), 5))


def parse_key(text: str) -> bytes:
    clean = re.sub(r"[\s\-]", "", (text or "")).translate(ALPHABET_FIX).upper()
    if not re.fullmatch(r"[A-Z2-7]+", clean or ""):
        raise LicenseError("La clave tiene caracteres que no son válidos. Cópiala completa tal como te la enviaron.")
    clean += "=" * (-len(clean) % 8)
    try:
        raw = base64.b32decode(clean)
    except ValueError as exc:
        raise LicenseError("La clave está incompleta o dañada. Cópiala completa.") from exc
    if len(raw) != PAYLOAD_SIZE + SIGNATURE_SIZE:
        raise LicenseError("La clave está incompleta o tiene de más. Cópiala completa tal como te la enviaron.")
    return raw


def read_key(text: str, key: Optional[VerifyingKey] = None) -> dict:
    """Comprueba la firma y devuelve lo que dice la clave (sin mirar vigencia ni instalación)."""
    key = key or public_key()
    if key is None:
        raise LicenseError("Esta instalación no tiene llave pública: no se pueden validar claves.")
    raw = parse_key(text)
    payload, signature = raw[:PAYLOAD_SIZE], raw[PAYLOAD_SIZE:]
    try:
        key.verify(signature, payload, hashfunc=hashlib.sha256)
    except (BadSignatureError, ValueError):
        raise LicenseError("La clave no es auténtica (no fue emitida para Comandia o está alterada).") from None
    version, key_id, install, issued, expires, mask, bodegas, tiendas, usuarios, cajas = struct.unpack(FORMAT, payload)
    if version != VERSION:
        raise LicenseError("Esta clave es de otra versión de Comandia. Actualiza el sistema o pide una clave nueva.")
    return {
        "key_id": key_id.hex().upper(),
        "install": base64.b32encode(install).decode(),
        "issued": EPOCH + timedelta(days=issued),
        "expires": EPOCH + timedelta(days=expires) if expires else None,
        "all": bool(mask & (1 << ALL_BIT)),
        "modules": [m for i, m in enumerate(MODULES) if mask & (1 << i) or mask & (1 << ALL_BIT)],
        "limits": {"bodegas": bodegas, "tiendas": tiendas, "usuarios": usuarios, "cajas": cajas},
    }


def new_private_key_pem() -> tuple:
    """Par de llaves nuevo: (privada PEM, pública PEM). Solo lo usa el generador."""
    sk = SigningKey.generate(curve=NIST256p)
    return sk.to_pem(), sk.get_verifying_key().to_pem()


# ───────── estado de la licencia ─────────
def evaluate(install_id: str, key_text: str, trial_start: Optional[date], today: date, key: Optional[VerifyingKey] = None) -> dict:
    """Qué módulos y límites están activos hoy. No toca la base de datos."""
    key = key or public_key()
    out = {"configured": key is not None, "install_id": install_id or "", "key_id": "", "licensed": False, "valid": False, "reason": "",
           "expires": None, "days_left": None, "modules": [], "all": False, "limits": {"bodegas": UNLIMITED, "tiendas": UNLIMITED, "usuarios": UNLIMITED, "cajas": UNLIMITED}}
    trial_end = (trial_start + timedelta(days=TRIAL_DAYS)) if trial_start else None
    trial_left = (trial_end - today).days if trial_end else 0
    if key is not None and (key_text or "").strip():
        try:
            info = read_key(key_text, key)
            if info["install"] != base64.b32encode(install_bytes(install_id)).decode():
                raise LicenseError("Esta clave es de otra instalación. Pide una clave con TU código de instalación.")
            out.update(key_id=info["key_id"], licensed=True, modules=info["modules"], limits=info["limits"], all=info["all"],
                       expires=info["expires"].isoformat() if info["expires"] else None)
            if info["expires"] is not None:
                out["days_left"] = (info["expires"] - today).days
                if out["days_left"] < 0:
                    out["reason"] = f"La clave venció el {info['expires'].strftime('%d/%m/%Y')}. Pide la renovación."
                    out["modules"] = []
                    out["all"] = False
                    out["licensed"] = False
            if out["licensed"]:
                out["valid"] = True
        except LicenseError as exc:
            out["reason"] = str(exc)
    # Una clave válida (incluso la Básica) da por terminada la prueba: manda lo que dice la clave.
    out["trial"] = {"active": key is not None and trial_left > 0 and not out["valid"], "days_left": max(trial_left, 0), "ends": trial_end.isoformat() if trial_end else None}
    out["active"] = {m: True for m in MODULES} if (key is None or out["trial"]["active"]) else {m: (out["all"] or m in out["modules"] or m not in ENFORCED) for m in MODULES}
    out["plan"] = "todo" if key is None else ("prueba" if out["trial"]["active"] else plan_of(out["modules"], out["all"]))
    out["plan_label"] = "Sin candados" if key is None else ("Prueba · todo activo" if out["trial"]["active"] else PLAN_LABELS[out["plan"]])
    users_limit = out["limits"]["usuarios"]
    out["users_allowed"] = None if (key is None or out["trial"]["active"] or not out["licensed"] or users_limit == UNLIMITED) else users_limit
    unlimited = key is None or out["trial"]["active"]
    lim = out["limits"]["bodegas"]
    out["warehouses_allowed"] = None if unlimited or (out["active"]["multi_warehouse"] and lim == UNLIMITED) else (lim if out["active"]["multi_warehouse"] else 1)
    return out
