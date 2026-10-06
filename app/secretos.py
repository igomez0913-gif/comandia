"""Cifrado de claves guardadas en la base de datos (clave del correo).

Se cifran con una llave derivada del `.secret` de este equipo, que NO está en la base ni en los respaldos: quien se lleve la base de
datos o un respaldo no puede leerlas. Si se restaura en otro equipo hay que copiar también el archivo `.secret` (o volver a escribirlas).
Los valores cifrados empiezan con `enc1:`; lo que se guardó antes sin cifrar se reconoce y se cifra al iniciar.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

PREFIX = "enc1:"
MAX_PLAIN = 64  # con este largo el valor cifrado cabe en las columnas de 200 caracteres


def _fernet(secret: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("comandia-campos|" + secret).encode()).digest()))


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)


def encrypt(plain: str, secret: str) -> str:
    if not plain or is_encrypted(plain):
        return plain or ""
    return PREFIX + _fernet(secret).encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt(value: str, secret: str) -> str:
    """Texto original. Un valor viejo sin cifrar se devuelve tal cual; si no se puede descifrar (otro `.secret`) devuelve vacío."""
    if not value:
        return ""
    if not is_encrypted(value):
        return value
    try:
        return _fernet(secret).decrypt(value[len(PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ""
