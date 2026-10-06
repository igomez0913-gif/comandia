"""Segunda ronda de seguridad: claves cifradas, licencia más difícil de evadir, bloqueo de ingreso, inactividad y copia de respaldos."""
import os
from datetime import date, timedelta

from fastapi.testclient import TestClient

from app import licencia, secretos
from test_v29_licencia import end_trial, install_id, issue, keys  # noqa: F401


def test_claves_guardadas_van_cifradas_y_no_se_devuelven(client, auth):
    from app import main
    from app.main import Company, SessionLocal
    r = client.put("/api/settings/email", json={"host": "smtp.gmail.com", "port": 587, "user": "a@b.hn", "password": "clave-de-app-123", "from_email": "a@b.hn", "security": "starttls"}, headers=auth)
    assert r.status_code == 200 and r.json()["has_password"] is True and "clave-de-app-123" not in r.text
    assert client.put("/api/settings/whatsapp", json={"url": "http://127.0.0.1:8002", "key": "mi-api-key"}, headers=auth).json()["has_key"] is True
    db = SessionLocal()
    c = db.query(Company).first()
    assert c.smtp_password.startswith("enc1:") and "clave-de-app-123" not in c.smtp_password and c.wa_key.startswith("enc1:") and "mi-api-key" not in c.wa_key
    assert main.smtp_config(c)["password"] == "clave-de-app-123" and main.wa_config(c)["key"] == "mi-api-key"  # el sistema sí las usa
    # lo que ya estaba sin cifrar (versiones anteriores) se cifra al iniciar
    c.smtp_password, c.wa_key = "vieja-en-texto", "otra-vieja"
    db.commit()
    main.encrypt_stored_secrets(db)
    db.refresh(c)
    assert c.smtp_password.startswith("enc1:") and main.smtp_config(c)["password"] == "vieja-en-texto" and main.wa_config(c)["key"] == "otra-vieja"
    # con otro .secret (base copiada a otro equipo) no se pueden leer: quedan vacías y piden volver a escribirlas
    assert secretos.decrypt(c.smtp_password, "otro-secreto") == "" and secretos.decrypt("sin-cifrar", "x") == "sin-cifrar"
    db.close()
    assert client.put("/api/settings/email", json={"host": "h", "port": 587, "password": "x" * 65}, headers=auth).status_code == 422  # el largo máximo asegura que cabe cifrada


def test_la_llave_publica_tambien_va_dentro_del_codigo(monkeypatch, keys, tmp_path):
    from app import llave_embebida
    from ecdsa import SigningKey
    pem = SigningKey.generate(curve=__import__("ecdsa").NIST256p).get_verifying_key().to_pem().decode()
    monkeypatch.undo()  # sin la llave de prueba del fixture
    monkeypatch.setattr(licencia, "PUBLIC_KEY_FILE", str(tmp_path / "no-existe.pem"))
    monkeypatch.setattr(llave_embebida, "PUBLIC_PEM", "")
    assert licencia.public_key() is None
    monkeypatch.setattr(llave_embebida, "PUBLIC_PEM", pem)
    assert licencia.public_key() is not None  # borrar llave_publica.pem ya no apaga los candados


def test_la_prueba_no_se_reinicia_ni_se_adelanta_editando_la_base(client, auth, keys):
    from app import main
    from app.main import Company, SessionLocal
    main.write_mark(date.today() - timedelta(days=40))  # el equipo ya había empezado hace 40 días
    assert client.get("/api/license", headers=auth).json()["trial"]["active"] is False  # base nueva: no vuelve a empezar la prueba
    db = SessionLocal()
    db.query(Company).first().trial_start = date.today()  # intento de renovar la prueba editando la base
    db.commit()
    db.close()
    assert client.get("/api/license", headers=auth).json()["trial"]["active"] is False
    assert main.read_mark() == date.today() - timedelta(days=40)
    # una marca alterada (firma que no coincide) se ignora
    with open(main.MARK_FILE, "w") as handle:
        handle.write(f"{date.today().isoformat()}|firma-falsa\n")
    assert main.read_mark() is None


def test_bloqueo_de_ingreso_por_correo_desde_cada_computadora(client):
    import asyncio

    import httpx

    from app.main import app

    async def login(ip, password):
        transport = httpx.ASGITransport(app=app, client=(ip, 5000))
        async with httpx.AsyncClient(transport=transport, base_url="http://servidor") as c:
            return (await c.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": password})).status_code

    async def scenario():
        bad = [await login("10.0.0.99", "mala") for _ in range(5)]
        return bad, await login("10.0.0.99", "comandia123"), await login("10.0.0.5", "comandia123")

    bad, attacker_after, owner = asyncio.run(scenario())
    assert bad == [401] * 5
    assert attacker_after == 429  # el atacante queda frenado aunque ahora acierte
    assert owner == 200  # el dueño del correo entra desde su propia PC


def test_cierre_por_inactividad_configurable(client, auth):
    base = {"name": "X", "rtn": "08019999123456"}
    assert client.get("/api/settings", headers=auth).json()["idle_minutes"] == 30
    assert client.put("/api/settings", json={**base, "idle_minutes": 10}, headers=auth).status_code == 200
    assert client.get("/api/settings", headers=auth).json()["idle_minutes"] == 10
    assert client.put("/api/settings", json=base, headers=auth).status_code == 200 and client.get("/api/settings", headers=auth).json()["idle_minutes"] == 10
    assert client.put("/api/settings", json={**base, "idle_minutes": 0}, headers=auth).status_code == 200 and client.get("/api/settings", headers=auth).json()["idle_minutes"] == 0
    assert client.put("/api/settings", json={**base, "idle_minutes": 5000}, headers=auth).status_code == 422


def test_respaldo_con_copia_secundaria(client, auth, tmp_path):
    copy = str(tmp_path / "copia")
    folder = client.get("/api/backups", headers=auth).json()["settings"]["effective_folder"]
    same = client.put("/api/backups/settings", json={"enabled": True, "hour": 12, "keep": 5, "folder": "", "copy_folder": folder}, headers=auth)
    assert same.status_code == 400 and "otra carpeta" in same.json()["detail"]
    ok = client.put("/api/backups/settings", json={"enabled": True, "hour": 12, "keep": 5, "folder": "", "copy_folder": copy}, headers=auth)
    assert ok.status_code == 200 and ok.json()["settings"]["copy_folder"] == copy
    made = client.post("/api/backups", headers=auth)
    assert made.status_code == 200
    assert made.json()["name"] in os.listdir(copy)  # el mismo respaldo quedó también en la otra carpeta
    actions = [a["detail"] for a in client.get("/api/audit", headers=auth).json()["rows"] if a["action"] == "Respaldo manual"]
    assert any("copia en" in d for d in actions)


def test_un_error_no_previsto_queda_en_el_registro_y_el_usuario_ve_un_aviso(client, auth):
    from app.main import app
    from app.logger import LOGS_DIR

    def boom():
        raise RuntimeError("fallo-de-prueba-xyz")

    app.add_api_route("/api/_prueba_error", boom, methods=["GET"])
    try:
        quiet = TestClient(app, raise_server_exceptions=False)
        r = quiet.get("/api/_prueba_error")
    finally:
        app.router.routes.pop()
    assert r.status_code == 500 and "error inesperado" in r.json()["detail"] and "fallo-de-prueba" not in r.text  # el usuario no ve texto técnico
    import logging
    for h in logging.getLogger().handlers:
        h.flush()
    text = open(os.path.join(LOGS_DIR, "error.log"), encoding="utf-8").read()
    assert "fallo-de-prueba-xyz" in text and "Traceback" in text  # soporte sí ve el detalle completo
    assert os.path.exists(os.path.join(LOGS_DIR, "comandia.log"))
