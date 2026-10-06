"""Pruebas de la v2.9: PDF de documentos y envío por correo (con un servidor SMTP simulado)."""
import pytest

from test_api import ids, invoice, line, make_user, product

SMTP_OK = {"host": "smtp.miempresa.hn", "port": 587, "user": "ventas@miempresa.hn", "password": "clave-app", "from_email": "ventas@miempresa.hn", "security": "starttls"}


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.calls = host, port, []

    def ehlo(self):
        pass

    def starttls(self, context=None):
        self.calls.append("starttls")

    def login(self, user, password):
        if password != "clave-app":
            import smtplib
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        self.calls.append("login")

    def send_message(self, msg, to_addrs=None):
        FakeSMTP.sent.append({"msg": msg, "to": to_addrs, "server": (self.host, self.port), "calls": list(self.calls)})

    def quit(self):
        pass


@pytest.fixture()
def smtp(monkeypatch):
    import smtplib
    FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def test_pdf_de_factura_y_cotizacion(client, auth):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 2)]).json()
    r = client.get(f"/api/documents/{f['id']}/pdf", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert f["number"] in r.headers["content-disposition"]
    q = invoice(client, auth, [line(p, 1)], kind="cotizacion").json()
    assert client.get(f"/api/documents/{q['id']}/pdf", headers=auth).content.startswith(b"%PDF")
    assert client.get("/api/documents/99999/pdf", headers=auth).status_code == 404


def test_pdf_con_textos_raros_y_muchas_lineas(client, auth):
    from app.pdf import document_pdf
    p = product(client, auth, "CEM-050")
    d = client.get(f"/api/documents/{invoice(client, auth, [line(p, 1)]).json()['id']}", headers=auth).json()
    doc = d["document"]
    doc["items"] = [{**doc["items"][0], "description": "Línea “especial” — con ñ, ¿signos? y emoji 🙂 " * 3}] * 60  # obliga a varias páginas
    doc["notes"] = "Nota — con guion largo"
    pdf = document_pdf(doc, d["company"])
    import re
    assert pdf.startswith(b"%PDF") and len(re.findall(rb"/Type\s*/Page[^s]", pdf)) >= 2


def test_configurar_correo_no_devuelve_la_clave(client, auth, login):
    r = client.put("/api/settings/email", json=SMTP_OK, headers=auth)
    assert r.status_code == 200 and r.json()["has_password"] is True and "password" not in r.json()
    # sin «password» se conserva la guardada
    r = client.put("/api/settings/email", json={k: v for k, v in SMTP_OK.items() if k != "password"}, headers=auth)
    assert r.json()["has_password"] is True
    assert client.put("/api/settings/email", json={**SMTP_OK, "security": "magia"}, headers=auth).status_code == 400
    assert client.put("/api/settings/email", json={**SMTP_OK, "from_email": "no-es-correo"}, headers=auth).status_code == 400
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/settings/email", headers=caja).status_code == 403


def test_enviar_factura_por_correo(client, auth, smtp):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 2)], payment_terms="30 días").json()
    r = client.post(f"/api/documents/{f['id']}/email", json={"to": "compras@elroble.hn"}, headers=auth)
    assert r.status_code == 400 and "Configuración" in r.json()["detail"]  # todavía sin SMTP
    client.put("/api/settings/email", json=SMTP_OK, headers=auth)
    r = client.post(f"/api/documents/{f['id']}/email", json={"to": "compras@elroble.hn; pagos@elroble.hn", "cc": "luis@miempresa.hn", "message": "Gracias por su compra."}, headers=auth)
    assert r.status_code == 200, r.text
    sent = smtp.sent[-1]
    msg = sent["msg"]
    assert sent["to"] == ["compras@elroble.hn", "pagos@elroble.hn", "luis@miempresa.hn"] and sent["calls"] == ["starttls", "login"]
    assert msg["Subject"] == f"Factura {f['number']} · Mi empresa" and msg["Reply-To"] == "ventas@miempresa.hn"
    body = msg.get_body(preferencelist=("plain",)).get_content()
    assert "L 563.50" in body and "Saldo pendiente" in body and "Gracias por su compra." in body
    att = [a for a in msg.iter_attachments()]
    assert att[0].get_filename() == f"{f['number']}.pdf" and att[0].get_content().startswith(b"%PDF")
    assert client.get("/api/audit", headers=auth).json()["rows"][0]["action"] == "Envió documento por correo"


def test_errores_de_correo_entendibles(client, auth, smtp, login):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 1)]).json()
    client.put("/api/settings/email", json={**SMTP_OK, "password": "mala"}, headers=auth)
    r = client.post(f"/api/documents/{f['id']}/email", json={"to": "a@b.hn"}, headers=auth)
    assert r.status_code == 502 and "contraseña de aplicación" in r.json()["detail"]
    r = client.post(f"/api/documents/{f['id']}/email", json={"to": "no es correo"}, headers=auth)
    assert r.status_code == 400 and "Correo no válido" in r.json()["detail"]
    client.put("/api/settings/email", json=SMTP_OK, headers=auth)
    assert client.post("/api/settings/email/test", json={"to": "luis@miempresa.hn"}, headers=auth).status_code == 200
    assert "prueba" in smtp.sent[-1]["msg"]["Subject"].lower()
    bod = make_user(client, auth, login, "Bodeguero")
    assert client.post(f"/api/documents/{f['id']}/email", json={"to": "a@b.hn"}, headers=bod).status_code == 403


def test_branding_publico_sin_sesion(client, auth):
    """La pantalla de ingreso obtiene nombre y logo sin iniciar sesión, y nada más."""
    r = client.get("/api/public/branding")
    assert r.status_code == 200
    assert set(r.json()) == {"name", "logo"}
    assert r.json()["name"]
