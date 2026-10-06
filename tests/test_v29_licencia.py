"""Pruebas de la v2.9: activación de módulos por clave firmada (WhatsApp directo y multi-bodega) y generador de claves."""
import importlib.util
import os
from datetime import date, timedelta

import pytest

from app import licencia
from test_api import ids, invoice, line, make_user, product


@pytest.fixture()
def keys(monkeypatch):
    """Par de llaves de prueba: la app valida con la pública y el «desarrollador» firma con la privada."""
    from ecdsa import VerifyingKey
    private_pem, public_pem = licencia.new_private_key_pem()
    monkeypatch.setattr(licencia, "public_key", lambda: VerifyingKey.from_pem(public_pem))
    return private_pem


def issue(private_pem, install, modules=("whatsapp", "multi_warehouse"), expires=date.today() + timedelta(days=365), **limits):
    payload = licencia.pack(os.urandom(4), install, date.today(), expires, modules, limits)
    return licencia.sign(private_pem, payload)


def end_trial(client):
    from app.main import Company, SessionLocal
    db = SessionLocal()
    c = db.query(Company).first()
    c.trial_start = date.today() - timedelta(days=licencia.TRIAL_DAYS + 5)
    db.commit()
    db.close()


def install_id(client, auth):
    return client.get("/api/license", headers=auth).json()["install_id"]


# ───────── la clave en sí ─────────
def test_clave_firmada_ida_y_vuelta_y_manipulaciones(keys):
    inst = licencia.new_install_id()
    key = issue(keys, inst, bodegas=5)
    assert len(key.replace("-", "")) == 135
    info = licencia.read_key(key)
    assert info["modules"] == ["whatsapp", "multi_warehouse"] and info["limits"]["bodegas"] == 5 and info["expires"] > date.today()
    assert licencia.read_key(key.lower().replace("-", " "))["key_id"] == info["key_id"]  # tolera minúsculas, espacios y guiones
    chars = list(key)
    pos = next(i for i, ch in enumerate(chars) if ch != "-")
    chars[pos] = "A" if chars[pos] != "A" else "B"
    for bad, msg in (("".join(chars), "no es auténtica"), (key[:-6], "incompleta"), ("ABC$%", "caracteres")):
        with pytest.raises(licencia.LicenseError, match=msg):
            licencia.read_key(bad)
    other_private, _ = licencia.new_private_key_pem()  # firmada por otra persona: no vale
    with pytest.raises(licencia.LicenseError, match="no es auténtica"):
        licencia.read_key(issue(other_private, inst))


def test_prueba_de_30_dias_y_vencimiento(keys):
    inst, today = licencia.new_install_id(), date.today()
    trial = licencia.evaluate(inst, "", today, today)
    assert trial["trial"]["active"] and all(trial["active"].values()) and trial["warehouses_allowed"] is None
    over = licencia.evaluate(inst, "", today - timedelta(days=31), today)
    assert not over["trial"]["active"] and over["active"]["whatsapp"] is False and over["active"]["multi_warehouse"] is False
    assert over["active"]["turnos_caja"] is True and over["active"]["reports"] is False and over["warehouses_allowed"] == 1  # lo incluido sigue abierto; lo adicional se bloquea
    ok = licencia.evaluate(inst, issue(keys, inst, bodegas=4), today - timedelta(days=60), today)
    assert ok["active"]["whatsapp"] and ok["warehouses_allowed"] == 4 and ok["valid"]
    unlimited = licencia.evaluate(inst, issue(keys, inst), today - timedelta(days=60), today)
    assert unlimited["warehouses_allowed"] is None
    old = licencia.evaluate(inst, issue(keys, inst, expires=today - timedelta(days=2)), today - timedelta(days=60), today)
    assert old["valid"] is False and "venció" in old["reason"] and old["active"]["whatsapp"] is False
    other = licencia.evaluate(inst, issue(keys, licencia.new_install_id()), today - timedelta(days=60), today)
    assert other["valid"] is False and "otra instalación" in other["reason"]


def test_sin_llave_publica_todo_abierto(client, auth, monkeypatch):
    # Comandia entrega su llave pública embebida; aquí se simula el entorno de desarrollo sin ninguna llave.
    monkeypatch.setattr(licencia, "public_key", lambda: None)
    lic = client.get("/api/license", headers=auth).json()
    assert lic["configured"] is False and all(m["active"] for m in lic["module_list"])


# ───────── candados en el sistema ─────────
def test_whatsapp_y_bodegas_se_bloquean_al_terminar_la_prueba_y_se_activan_con_la_clave(client, auth, login, keys):
    lic = client.get("/api/license", headers=auth).json()
    assert lic["configured"] and lic["trial"]["active"] and lic["trial"]["days_left"] == licencia.TRIAL_DAYS and len(lic["install_id"]) == 9
    # en la prueba todo funciona
    assert client.post("/api/warehouses", json={"code": "T1", "name": "Tienda 1", "address": ""}, headers=auth).status_code == 200
    end_trial(client)
    wh = client.get("/api/warehouses", headers=auth).json()
    blocked = client.post("/api/warehouses", json={"code": "T2", "name": "Otra", "address": ""}, headers=auth)
    assert blocked.status_code == 403 and "Multi-bodega" in blocked.json()["detail"]
    lic = client.get("/api/license", headers=auth).json()
    assert lic["warehouses_allowed"] == 1  # sin Multi-bodega el límite es 1; las que ya existen se conservan pero no se agregan más
    for call in (lambda: client.put("/api/settings/whatsapp", json={"url": "http://127.0.0.1:8002"}, headers=auth),
                 lambda: client.post("/api/settings/whatsapp/test", json={}, headers=auth)):
        r = call()
        assert r.status_code == 403 and "WhatsApp" in r.json()["detail"]
    assert client.get("/api/whatsapp/status", headers=auth).json() == {"configured": False}
    # activar la clave
    inst = install_id(client, auth)
    assert client.post("/api/license", json={"key": issue(keys, licencia.new_install_id())}, headers=auth).status_code == 400  # de otra instalación
    other_private, _ = licencia.new_private_key_pem()
    assert client.post("/api/license", json={"key": issue(other_private, inst)}, headers=auth).status_code == 400  # falsificada
    caja = make_user(client, auth, login, "Cajero")
    key = issue(keys, inst, bodegas=len(wh) + 2)
    assert client.post("/api/license", json={"key": key}, headers=caja).status_code == 403  # solo quien configura
    r = client.post("/api/license", json={"key": key}, headers=auth)
    assert r.status_code == 200 and r.json()["valid"] and r.json()["warehouses_allowed"] == len(wh) + 2
    assert client.put("/api/settings/whatsapp", json={"url": "http://127.0.0.1:8002"}, headers=auth).status_code == 200
    assert client.get("/api/whatsapp/status", headers=auth).json() == {"configured": True}
    assert client.post("/api/warehouses", json={"code": "T2", "name": "Otra", "address": ""}, headers=auth).status_code == 200
    assert client.post("/api/warehouses", json={"code": "T3", "name": "Otra 2", "address": ""}, headers=auth).status_code == 200
    third = client.post("/api/warehouses", json={"code": "T4", "name": "Otra 3", "address": ""}, headers=auth)
    assert third.status_code == 403 and f"{len(wh) + 2} bodega" in third.json()["detail"]
    actions = [a["action"] for a in client.get("/api/audit", headers=auth).json()["rows"]]
    assert "Activó licencia" in actions


def test_facturar_nunca_se_bloquea(client, auth, keys):
    end_trial(client)
    p = product(client, auth, "CEM-050")
    assert invoice(client, auth, [line(p, 1)]).status_code == 200  # sin clave y sin prueba se sigue facturando
    assert client.get("/api/products", headers=auth).status_code == 200


def test_atrasar_el_reloj_no_alarga_la_prueba(client, auth, keys, monkeypatch):
    p = product(client, auth, "CEM-050")
    invoice(client, auth, [line(p, 1)])  # una factura de hoy deja constancia de la fecha real
    from app import main as m
    from app.main import Company, SessionLocal
    db = SessionLocal()
    db.query(Company).first().trial_start = date.today() - timedelta(days=40)
    db.commit()
    db.close()
    monkeypatch.setattr(m, "today_local", lambda: date.today() - timedelta(days=30))  # reloj atrasado un mes
    assert client.get("/api/license", headers=auth).json()["trial"]["active"] is False


def test_alertas_de_prueba_y_vencimiento(client, auth, keys):
    from app.main import Company, SessionLocal
    db = SessionLocal()
    db.query(Company).first()
    c = db.query(Company).first()
    client.get("/api/license", headers=auth)
    c = db.query(Company).first()
    c.trial_start = date.today() - timedelta(days=licencia.TRIAL_DAYS - 3)
    db.commit()
    db.close()
    titles = [a["title"] for a in client.get("/api/dashboard/insights", headers=auth).json()["alerts"]]
    assert any("prueba termina" in t for t in titles)
    end_trial(client)
    inst = install_id(client, auth)
    client.post("/api/license", json={"key": issue(keys, inst, expires=date.today() + timedelta(days=10))}, headers=auth)
    titles = [a["title"] for a in client.get("/api/dashboard/insights", headers=auth).json()["alerts"]]
    assert any("licencia vence" in t for t in titles)


# ───────── el generador ─────────
def test_generador_de_claves(tmp_path, capsys, keys):
    spec = importlib.util.spec_from_file_location("generador", os.path.join(os.path.dirname(__file__), "..", "herramientas", "generador-de-claves.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.PRIVATE, gen.PUBLIC, gen.LOG = str(tmp_path / "llaves" / "privada.pem"), str(tmp_path / "publica.pem"), str(tmp_path / "emitidas.csv")
    gen.crear_llaves()
    with pytest.raises(SystemExit):
        gen.crear_llaves()  # no pisa las llaves existentes
    inst = licencia.new_install_id()
    gen.emitir("Ferretería Prueba", inst, ["whatsapp", "multi_warehouse"], {"bodegas": 3}, date.today() + timedelta(days=30))
    out = capsys.readouterr().out
    key = next(line for line in out.splitlines() if line.count("-") > 20)
    from ecdsa import VerifyingKey
    pub = VerifyingKey.from_pem(open(gen.PUBLIC, "rb").read())
    info = licencia.read_key(key, pub)
    assert info["modules"] == ["whatsapp", "multi_warehouse"] and info["limits"]["bodegas"] == 3
    assert "Ferretería Prueba" in open(gen.LOG, encoding="utf-8-sig").read()
    with pytest.raises(SystemExit):
        gen.emitir("X", "ZZZ", ["whatsapp"], {}, None)  # código de instalación inválido
    with pytest.raises(SystemExit):
        gen.emitir("X", inst, ["inexistente"], {}, None)


def test_modulos_adicionales_importar_excel_rentabilidad_y_ventas_sin_conexion(client, auth, keys):
    end_trial(client)
    for call in (lambda: client.get("/api/products/import/template", headers=auth),
                 lambda: client.post("/api/products/import", files={"file": ("p.csv", b"sku,nombre\nX1,Prueba\n")}, headers=auth),
                 lambda: client.get("/api/reports/profit?period=all", headers=auth),
                 lambda: client.get("/api/reports/rentabilidad.csv?period=all", headers=auth)):
        r = call()
        assert r.status_code == 403 and "no está activado" in r.json()["detail"]
    assert client.get("/api/dashboard/insights", headers=auth).json()["margin"] is None  # el margen es parte de Rentabilidad
    # las reglas fiscales y el cobro no se bloquean: una venta sin conexión ya hecha siempre se puede sincronizar
    p = product(client, auth, "CEM-050")
    from test_v29_offline import sale
    assert sale(client, auth, p, 1, offline_id="OFF-TEST-1").status_code == 200
    mods = {m["id"]: m for m in client.get("/api/license", headers=auth).json()["module_list"]}
    assert mods["turnos_caja"]["included"] and mods["advanced_credit"]["enforced"] and mods["reports"]["enforced"]
    inst = install_id(client, auth)
    key = issue(keys, inst, modules=("importar_excel", "reports"))
    assert client.post("/api/license", json={"key": key}, headers=auth).status_code == 200
    assert client.get("/api/reports/profit?period=all", headers=auth).status_code == 200
    assert client.get("/api/products/import/template", headers=auth).status_code == 200
