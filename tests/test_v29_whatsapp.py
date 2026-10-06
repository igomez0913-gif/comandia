"""Pruebas de la v2.9: envío por WhatsApp con la API de OpenWA (servidor simulado con el mismo formato)."""
import base64
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from test_api import invoice, line, make_user, product

KEY = "clave-openwa"


class FakeOpenWA(BaseHTTPRequestHandler):
    """Dos sabores: «v5» (OpenWA 5: rutas /api/..., cuerpo plano, respuesta con data) y «v4» (EASY API: POST /método con args)."""
    calls = []
    flavor = "v5"
    state = "CONNECTED"
    ready = True
    fail_send = False

    def log_message(self, *a):
        pass

    def _reply(self, code, payload):
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _handle(self, method, body):
        if (self.headers.get("api_key") or self.headers.get("X-API-Key")) != KEY:
            return self._reply(401, {"error": "Unauthorized", "details": "Invalid or missing API key"})
        v5 = FakeOpenWA.flavor == "v5"
        routes = {"/api/session/getConnectionState": "getConnectionState", "/api/messages/sendText": "sendText", "/api/messages/sendFile": "sendFile"} if v5 \
            else {"/getConnectionState": "getConnectionState", "/sendText": "sendText", "/sendFile": "sendFile"}
        name = routes.get(self.path)
        if name is None:
            return self._reply(404, {"error": "Not Found"})
        if v5 and not FakeOpenWA.ready:
            return self._reply(503, {"error": "API not available until the session is truly ready", "status": 503})
        args = body if v5 else body.get("args", {})
        FakeOpenWA.calls.append((name, args))
        key = "data" if v5 else "response"
        if name == "getConnectionState":
            return self._reply(200, {"success": True, key: FakeOpenWA.state})
        if FakeOpenWA.fail_send:
            return self._reply(500, {"success": False, "error": {"name": "ERROR", "message": "Number not registered on WhatsApp"}} if not v5
                               else {"error": "Send failed", "details": "Number not registered on WhatsApp"})
        return self._reply(200, {"success": True, key: "true_50498389988@c.us_ABC"})

    def do_GET(self):
        self._handle("GET", {})

    def do_POST(self):
        self._handle("POST", json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}"))


@pytest.fixture(params=["v5", "v4"])
def openwa(request):
    FakeOpenWA.calls, FakeOpenWA.state, FakeOpenWA.fail_send, FakeOpenWA.ready, FakeOpenWA.flavor = [], "CONNECTED", False, True, request.param
    server = HTTPServer(("127.0.0.1", 0), FakeOpenWA)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def configure(client, auth, url, key=KEY):
    r = client.put("/api/settings/whatsapp", json={"url": url, "key": key}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def test_chat_id_normaliza_celulares():
    from app.whatsapp import WhatsAppError, chat_id
    assert chat_id("9838-9988") == "50498389988@c.us"
    assert chat_id("+504 9838 9988") == "50498389988@c.us"
    assert chat_id("00504 98389988") == "50498389988@c.us"
    assert chat_id("52 55 1234 5678") == "525512345678@c.us"
    for bad in ("", "123", "abc"):
        with pytest.raises(WhatsAppError):
            chat_id(bad)


def test_configuracion_no_devuelve_la_clave(client, auth, openwa):
    assert client.get("/api/whatsapp/status", headers=auth).json() == {"configured": False}
    out = configure(client, auth, openwa + "/")
    assert out == {"url": openwa, "has_key": True, "configured": True}
    assert "key" not in client.get("/api/settings/whatsapp", headers=auth).json()
    # sin «key» se conserva la guardada
    assert client.put("/api/settings/whatsapp", json={"url": openwa}, headers=auth).json()["has_key"] is True
    assert client.put("/api/settings/whatsapp", json={"url": "localhost:8002"}, headers=auth).status_code == 400
    assert client.get("/api/whatsapp/status", headers=auth).json() == {"configured": True}


def test_probar_conexion_y_mensaje_de_prueba(client, auth, openwa):
    configure(client, auth, openwa)
    r = client.post("/api/settings/whatsapp/test", json={"phone": "9838-9988"}, headers=auth)
    assert r.status_code == 200 and r.json() == {"ok": True, "state": "CONNECTED", "sent": True}
    assert [m for m, _ in FakeOpenWA.calls] == ["getConnectionState", "sendText"]
    assert FakeOpenWA.calls[1][1]["to"] == "50498389988@c.us"
    FakeOpenWA.state = "UNPAIRED"
    r = client.post("/api/settings/whatsapp/test", json={}, headers=auth)
    assert r.status_code == 502 and "no está vinculado" in r.json()["detail"]
    configure(client, auth, openwa, key="otra-clave")
    r = client.post("/api/settings/whatsapp/test", json={}, headers=auth)
    assert r.status_code == 502 and "rechazó la clave" in r.json()["detail"]
    configure(client, auth, "http://127.0.0.1:9")
    assert "No se pudo conectar" in client.post("/api/settings/whatsapp/test", json={}, headers=auth).json()["detail"]


def test_openwa_5_todavia_sin_vincular(client, auth, openwa):
    """OpenWA 5 responde 503 hasta que WhatsApp está vinculado (QR escaneado): el aviso lo explica."""
    if FakeOpenWA.flavor != "v5":
        pytest.skip("solo aplica a OpenWA 5")
    configure(client, auth, openwa)
    FakeOpenWA.ready = False
    r = client.post("/api/settings/whatsapp/test", json={}, headers=auth)
    assert r.status_code == 502 and "código QR" in r.json()["detail"]


def test_enviar_factura_en_pdf_y_recordatorio_en_texto(client, auth, openwa):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 2)]).json()
    # sin configurar
    r = client.post(f"/api/documents/{f['id']}/whatsapp", json={"phone": "98389988", "message": "Hola"}, headers=auth)
    assert r.status_code == 400 and "Configuración" in r.json()["detail"]
    configure(client, auth, openwa)
    r = client.post(f"/api/documents/{f['id']}/whatsapp", json={"phone": "9838-9988", "message": "Su factura, gracias"}, headers=auth)
    assert r.status_code == 200, r.text
    method, args = FakeOpenWA.calls[-1]
    assert method == "sendFile" and args["to"] == "50498389988@c.us" and args["filename"] == f"{f['number']}.pdf" and args["caption"] == "Su factura, gracias"
    header, b64 = args["file"].split(",", 1)
    assert header == "data:application/pdf;base64" and base64.b64decode(b64).startswith(b"%PDF")
    r = client.post(f"/api/documents/{f['id']}/whatsapp", json={"phone": "98389988", "message": "Recordatorio", "attach": False}, headers=auth)
    assert r.status_code == 200 and FakeOpenWA.calls[-1][0] == "sendText" and FakeOpenWA.calls[-1][1]["content"] == "Recordatorio"
    actions = [a["action"] for a in client.get("/api/audit", headers=auth).json()["rows"]]
    assert "Envió por WhatsApp" in actions and "Recordatorio de cobro por WhatsApp" in actions


def test_errores_de_envio_y_permisos(client, auth, login, openwa):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 1)]).json()
    configure(client, auth, openwa)
    FakeOpenWA.fail_send = True
    r = client.post(f"/api/documents/{f['id']}/whatsapp", json={"phone": "98389988", "message": "x"}, headers=auth)
    assert r.status_code == 502 and "Number not registered" in r.json()["detail"]
    assert client.post(f"/api/documents/{f['id']}/whatsapp", json={"phone": "12", "message": "x"}, headers=auth).status_code == 502
    assert client.post("/api/documents/99999/whatsapp", json={"phone": "98389988", "message": "x"}, headers=auth).status_code == 404
    caja = make_user(client, auth, login, "Cajero")
    assert client.put("/api/settings/whatsapp", json={"url": openwa}, headers=caja).status_code == 403
    FakeOpenWA.fail_send = False
    assert client.post(f"/api/documents/{f['id']}/whatsapp", json={"phone": "98389988", "message": "x"}, headers=caja).status_code == 200
    bod = make_user(client, auth, login, "Bodeguero")
    assert client.post(f"/api/documents/{f['id']}/whatsapp", json={"phone": "98389988", "message": "x"}, headers=bod).status_code == 403
