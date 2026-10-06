"""Envío por WhatsApp con OpenWA (@open-wa/wa-automate) por HTTP.

OpenWA corre aparte (Node.js): se inicia con un puerto y una clave y se vincula escaneando un QR con el WhatsApp de la
empresa. Comandia le habla por HTTP y reconoce solo la versión: primero prueba la API de OpenWA 5
(`/api/messages/sendText`, `/api/messages/sendFile`, `/api/session/getConnectionState`) y, si no existe, la de las versiones
3 y 4 (`POST /{método}` con `{"args": ...}`). La clave va en los encabezados `X-API-Key` y `api_key`.

Solo usa la librería estándar. La dirección y la clave las configura el administrador en Configuración › WhatsApp.
"""
import base64
import json
import re
import socket
import urllib.error
import urllib.request
from urllib.parse import urlparse

TIMEOUT = 45


class WhatsAppError(Exception):
    """Error con un mensaje que se le puede mostrar tal cual al usuario."""


def clean_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise WhatsAppError("La dirección de OpenWA debe empezar con http:// o https:// (por ejemplo http://localhost:8002)")
    return url


def chat_id(phone: str, default_country: str = "504") -> str:
    """«9838-9988», «+504 9838 9988» o «50498389988» → «50498389988@c.us» (8 dígitos = Honduras)."""
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 8:
        digits = default_country + digits
    if not 10 <= len(digits) <= 15:
        raise WhatsAppError("Revisa el celular del cliente: escribe el número con 8 dígitos (Honduras) o con código de país")
    return f"{digits}@c.us"


# OpenWA 5 (actual): rutas REST con cuerpo plano y respuesta {"success": true, "data": ...}.
# OpenWA 3/4 (EASY API): POST /{método} con {"args": {...}} y respuesta {"success": true, "response": ...}.
V5_ROUTES = {
    "getConnectionState": ("GET", "/api/session/getConnectionState"),
    "sendText": ("POST", "/api/messages/sendText"),
    "sendFile": ("POST", "/api/messages/sendFile"),
}
NOT_READY = ("OpenWA todavía no está listo: espera a que termine de iniciar y vincula WhatsApp escaneando el código QR "
             "(en la ventana de OpenWA o en su panel, http://localhost:8002/dashboard/).")


def _request(url: str, http_method: str, payload, key: str, timeout: int):
    """Una petición HTTP. Devuelve (código, JSON o None). Lanza WhatsAppError si no hay conexión."""
    headers = {"Content-Type": "application/json"}
    if key:
        headers["api_key"] = key    # versiones 3 y 4 de OpenWA
        headers["X-API-Key"] = key  # versión 5
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=http_method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as res:
            raw, status = res.read(), res.status
    except urllib.error.HTTPError as exc:
        raw, status = exc.read(), exc.code
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        if isinstance(reason, socket.timeout) or isinstance(exc, socket.timeout):
            raise WhatsAppError("OpenWA no respondió a tiempo. Revisa que esté iniciado y que WhatsApp esté vinculado.") from exc
        where = url.split("/api/", 1)[0] if "/api/" in url else url.rsplit("/", 1)[0]
        raise WhatsAppError(f"No se pudo conectar con OpenWA en {where} ({reason}). Revisa que esté iniciado y la dirección.") from exc
    try:
        return status, json.loads(raw.decode("utf-8", "replace"))
    except ValueError:
        return status, None


def _error_text(data, status: int) -> str:
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            err = err.get("message") or err.get("name")
        detail = data.get("details") or data.get("message")
        if err and detail and detail != err:
            return f"{err}: {detail}"
        return str(err or detail or f"HTTP {status}")
    return f"HTTP {status}"


def _call(cfg: dict, method: str, args: dict, timeout: int = TIMEOUT):
    base = clean_url(cfg.get("url", ""))
    if not base:
        raise WhatsAppError("Falta configurar OpenWA en Configuración › WhatsApp")
    key = cfg.get("key") or ""
    http_method, path = V5_ROUTES.get(method, ("POST", f"/{method}"))
    status, data = _request(base + path, http_method, args if http_method == "POST" else None, key, timeout)
    legacy = False
    if status == 404 and method in V5_ROUTES:  # no existe la ruta de la versión 5: se prueba la de las versiones 3 y 4
        legacy = True
        status, data = _request(f"{base}/{method}", "POST", {"args": args}, key, timeout)
    if status in (401, 403):
        raise WhatsAppError("OpenWA rechazó la clave (api_key). Revisa la clave en Configuración › WhatsApp.")
    if status == 503 and not legacy:
        raise WhatsAppError(NOT_READY)
    if data is None:
        raise WhatsAppError(f"OpenWA respondió algo inesperado (HTTP {status}). Revisa la dirección: debe ser la del servidor de OpenWA.")
    if not isinstance(data, dict) or not data.get("success"):
        raise WhatsAppError(f"OpenWA no pudo enviarlo: {_error_text(data, status)}")
    return data.get("response") if legacy or "data" not in data else data.get("data")


def connection_state(cfg: dict) -> str:
    """«CONNECTED» cuando WhatsApp está vinculado y listo."""
    return str(_call(cfg, "getConnectionState", {}, timeout=15))


def send_text(cfg: dict, phone: str, text: str):
    return _call(cfg, "sendText", {"to": chat_id(phone), "content": text})


def send_pdf(cfg: dict, phone: str, filename: str, pdf: bytes, caption: str = ""):
    """El PDF viaja en base64 dentro de la petición; el mensaje va como pie del archivo."""
    data_url = "data:application/pdf;base64," + base64.b64encode(pdf).decode("ascii")
    return _call(cfg, "sendFile", {"to": chat_id(phone), "file": data_url, "filename": filename, "caption": caption})
