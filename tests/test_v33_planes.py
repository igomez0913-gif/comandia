"""Licenciamiento por planes: Básico (sin clave), Profesional, Empresarial y Todo. Cada módulo se prueba abierto y cerrado."""
import os
from datetime import date, timedelta

import pytest

from app import licencia
from test_api import ids, invoice, line, make_user, product
from test_v29_credito import new_client, sell
from test_v29_licencia import end_trial, install_id, issue, keys  # noqa: F401

PRO = list(licencia.PLANS["profesional"])
EMP = list(licencia.PLANS["empresarial"])


def activate(client, auth, keys, modules, **limits):
    end_trial(client)
    key = issue(keys, install_id(client, auth), modules=modules, **limits)
    r = client.post("/api/license", json={"key": key}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def blocked(r):
    return r.status_code == 403 and "no está activado" in r.json()["detail"]


def purchase_body(client, auth, **extra):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    sup = client.get("/api/suppliers", headers=auth).json()[0]["id"]
    return {"supplier_id": sup, "warehouse_id": i["wh"]["id"], "items": [{"product_id": p["id"], "qty": 2, "unit_cost": 100}], **extra}


# ───────── los paquetes ─────────
def test_los_paquetes_cubren_los_modulos_del_esquema():
    assert set(licencia.PLANS["profesional"]) == {"multi_warehouse", "reports", "backup", "api", "importar_excel", "etiquetas"}
    assert {"email", "offline", "compras", "advanced_credit"} <= set(licencia.PLANS["empresarial"]) and set(PRO) <= set(EMP)
    assert licencia.PLANS["basico"] == [] and set(licencia.PLANS["todo"]) == set(licencia.MODULES) and len(licencia.MODULES) <= licencia.ALL_BIT
    assert [licencia.plan_of(licencia.PLANS[p]) for p in ("basico", "profesional", "empresarial", "todo")] == ["basico", "profesional", "empresarial", "todo"]
    assert licencia.plan_of(["email"]) == "basico" and licencia.plan_of(PRO + ["email"]) == "profesional"  # un extra suelto no sube el paquete


def test_la_clave_todo_incluye_los_modulos_futuros(keys, monkeypatch):
    inst, today = licencia.new_install_id(), date.today()
    all_key = issue(keys, inst, modules=("todo",))
    pro_key = issue(keys, inst, modules=tuple(PRO))
    assert licencia.read_key(all_key)["all"] is True and set(licencia.read_key(all_key)["modules"]) == set(licencia.MODULES)
    monkeypatch.setattr(licencia, "MODULES", licencia.MODULES + ["modulo_futuro"])
    monkeypatch.setattr(licencia, "ENFORCED", licencia.ENFORCED | {"modulo_futuro"})
    old = today - timedelta(days=60)
    assert licencia.evaluate(inst, all_key, old, today)["active"]["modulo_futuro"] is True  # «todo» ya lo trae
    assert licencia.evaluate(inst, pro_key, old, today)["active"]["modulo_futuro"] is False  # un paquete no
    info = licencia.evaluate(inst, all_key, old, today)
    assert info["plan"] == "todo" and info["plan_label"] == "Todo incluido"


@pytest.mark.parametrize("plan", ["profesional", "empresarial", "todo"])
def test_el_plan_activa_exactamente_sus_modulos(client, auth, keys, plan):
    mods = ("todo",) if plan == "todo" else tuple(licencia.PLANS[plan])
    lic = activate(client, auth, keys, mods)
    assert lic["plan"] == plan and lic["plan_label"] == licencia.PLAN_LABELS[plan]
    expected = set(licencia.MODULES) if plan == "todo" else set(licencia.PLANS[plan]) | licencia.INCLUDED
    assert {m["id"] for m in lic["module_list"] if m["active"]} == expected


# ───────── Básico: sin clave, después de la prueba ─────────
def test_basico_lo_esencial_funciona_y_lo_adicional_se_bloquea(client, auth, keys, login):
    end_trial(client)
    p = product(client, auth, "CEM-050")
    lic = client.get("/api/license", headers=auth).json()
    assert lic["plan"] == "basico" and lic["plan_label"] == "Básico"
    # ✅ incluido: facturar, cotizar, punto de venta, clientes, productos, usuarios, reportes SAR, respaldo manual, turnos y compra de contado recibida
    assert invoice(client, auth, [line(p, 1)]).status_code == 200
    assert invoice(client, auth, [line(p, 1)], kind="cotizacion").status_code == 200
    assert client.post("/api/clients", json={"name": "Cliente Nuevo", "rtn": ""}, headers=auth).status_code == 200
    assert client.get("/api/reports?period=all", headers=auth).status_code == 200
    for csv in ("libro-ventas", "libro-compras", "retenciones", "inventario", "cxc"):
        assert client.get(f"/api/reports/{csv}.csv?period=all", headers=auth).status_code == 200, csv  # obligaciones del SAR: nunca se bloquean
    assert client.post("/api/backups", headers=auth).status_code == 200  # respaldar ahora siempre
    assert client.post("/api/shifts/open", json={"caja": "Caja 1", "opening": 0}, headers=auth).status_code == 200
    assert client.post("/api/purchases", json=purchase_body(client, auth, status="Recibida", payment_terms="Contado"), headers=auth).status_code == 200
    caja = make_user(client, auth, login, "Cajero")
    # 🔐 con candado
    for r in (client.get("/api/reports/ventas-detallado?start=2026-01-01&end=2026-01-31", headers=auth), client.get("/api/reports/profit?period=all", headers=auth),
              client.put("/api/backups/settings", json={"enabled": True, "hour": 12, "keep": 5, "folder": "", "copy_folder": ""}, headers=auth),
              client.put("/api/settings/email", json={"host": "h", "port": 587}, headers=auth), client.post("/api/settings/email/test", json={"to": "a@b.hn"}, headers=auth),
              client.get("/api/labels/products", headers=auth),
              client.get("/api/replenishment", headers=auth), client.post("/api/api-keys", json={"name": "ERP"}, headers=auth),
              client.get("/api/payables", headers=auth), client.get("/api/reports/cxp.csv", headers=auth),
              client.post("/api/purchases", json=purchase_body(client, auth, status="Pendiente"), headers=auth),
              client.post("/api/purchases", json=purchase_body(client, auth, status="Recibida", payment_terms="30 días"), headers=auth)):
        assert blocked(r), r.request.url
    doc = invoice(client, auth, [line(p, 1)]).json()
    assert blocked(client.post(f"/api/documents/{doc['id']}/email", json={"to": "a@b.hn"}, headers=auth))
    assert client.get("/api/dashboard/insights", headers=auth).json()["margin"] is None  # el margen es de reportes avanzados
    # el crédito avanzado (límite y bloqueo por mora) no se aplica, pero vender al crédito sí se puede
    cid = new_client(client, auth, credit_limit=100)
    # un cajero que pasa del límite…
    assert sell(client, caja, cid, [line(p, 3)]).status_code == 200  # …no se frena: el crédito avanzado es de otro plan


def test_basico_limita_a_una_bodega_y_no_traslada(client, auth, keys):
    end_trial(client)
    assert blocked(client.post("/api/warehouses", json={"code": "X1", "name": "Otra", "address": ""}, headers=auth)) or client.post("/api/warehouses", json={"code": "X1", "name": "Otra", "address": ""}, headers=auth).status_code == 403
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    r = client.post("/api/stock/transfer", json={"product_id": p["id"], "from_warehouse_id": i["wh"]["id"], "to_warehouse_id": i["wh2"]["id"], "qty": 1}, headers=auth)
    assert blocked(r)


# ───────── Profesional y Empresarial ─────────
def test_profesional_abre_lo_suyo_y_deja_cerrado_lo_empresarial(client, auth, keys, tmp_path):
    activate(client, auth, keys, tuple(PRO), bodegas=0)
    today = date.today().isoformat()
    assert client.get(f"/api/reports/ventas-detallado?start={today}&end={today}", headers=auth).status_code == 200
    assert client.get("/api/reports/profit?period=all", headers=auth).status_code == 200
    ok = client.put("/api/backups/settings", json={"enabled": True, "hour": 12, "keep": 5, "folder": "", "copy_folder": str(tmp_path / "copia")}, headers=auth)
    assert ok.status_code == 200 and ok.json()["settings"]["available"] is True
    assert client.get("/api/labels/products", headers=auth).status_code == 200
    assert client.post("/api/warehouses", json={"code": "X1", "name": "Otra", "address": ""}, headers=auth).status_code == 200
    assert client.post("/api/api-keys", json={"name": "ERP"}, headers=auth).status_code == 200
    for r in (client.put("/api/settings/email", json={"host": "h", "port": 587}, headers=auth),
              client.get("/api/payables", headers=auth), client.get("/api/replenishment", headers=auth),
              client.post("/api/purchases", json=purchase_body(client, auth, status="Pendiente"), headers=auth)):
        assert blocked(r), r.request.url


def test_empresarial_abre_compras_correo_y_credito_avanzado(client, auth, keys, login):
    activate(client, auth, keys, tuple(EMP))
    p = product(client, auth, "CEM-050")
    order = client.post("/api/purchases", json=purchase_body(client, auth, status="Pendiente"), headers=auth)
    assert order.status_code == 200
    assert client.post(f"/api/purchases/{order.json()['id']}/receive", headers=auth).status_code == 200
    credit = client.post("/api/purchases", json=purchase_body(client, auth, status="Recibida", payment_terms="30 días"), headers=auth).json()
    assert client.get("/api/payables", headers=auth).json()["total"] > 0
    assert client.post(f"/api/purchases/{credit['id']}/payments", json={"amount": 10, "method": "Efectivo"}, headers=auth).status_code == 200
    assert client.put("/api/settings/email", json={"host": "smtp.x.hn", "port": 587, "password": "abc"}, headers=auth).json()["available"] is True
    assert client.get("/api/replenishment", headers=auth).status_code == 200
    # crédito avanzado: ahora sí hay límite
    cid = new_client(client, auth, credit_limit=100)
    caja = make_user(client, auth, login, "Cajero")
    assert sell(client, caja, cid, [line(p, 3)]).status_code == 403  # un cajero necesita el PIN de un supervisor


# ───────── API REST de lectura ─────────
def test_api_con_llaves_de_solo_lectura(client, auth, keys):
    activate(client, auth, keys, tuple(PRO))
    created = client.post("/api/api-keys", json={"name": "Tienda en línea"}, headers=auth).json()
    raw = created["key"]
    assert raw.startswith("vk_") and created["prefix"] == raw[:9] and created["active"]
    listed = client.get("/api/api-keys", headers=auth).json()
    assert listed["available"] and "key" not in listed["keys"][0] and "key_hash" not in listed["keys"][0]  # la llave no se vuelve a mostrar
    h = {"X-API-Key": raw}
    assert client.get("/api/v1/ping", headers=h).json()["llave"] == "Tienda en línea"
    prods = client.get("/api/v1/products?q=CEM&limit=5", headers=h).json()
    assert prods["total"] >= 1 and "cost" not in prods["items"][0] and prods["items"][0]["prices"]  # sin costos
    assert client.get("/api/v1/stock", headers=h).json()["items"][0]["cantidad"] is not None
    assert client.get("/api/v1/clients", headers=h).json()["total"] >= 1
    p = product(client, auth, "CEM-050")
    inv = invoice(client, auth, [line(p, 1)]).json()
    docs = client.get("/api/v1/documents?kind=factura&limit=3", headers=h).json()
    assert docs["items"][0]["numero"] == inv["number"] and docs["items"][0]["total"] == inv["total"]
    assert client.get(f"/api/v1/documents/{inv['id']}", headers=h).json()["lineas"][0]["cantidad"] == 1
    assert client.get("/api/v1/documents?desde=mal", headers=h).status_code == 400
    assert client.get("/api/v1/documents?limit=99999", headers=h).json()["limit"] == 500
    # solo lectura y solo con llave
    assert client.get("/api/v1/products").status_code == 401 and client.get("/api/v1/products", headers=auth).status_code == 401
    assert client.get("/api/v1/products", headers={"X-API-Key": "vk_falsa"}).status_code == 401
    assert client.post("/api/v1/products", headers=h, json={}).status_code in (404, 405)
    assert client.get("/api/products", headers=h).status_code == 401  # la llave no sirve en el resto del sistema
    # revocar
    assert client.delete(f"/api/api-keys/{created['id']}", headers=auth).status_code == 200
    assert client.get("/api/v1/ping", headers=h).status_code == 401
    audit = [a["action"] for a in client.get("/api/audit", headers=auth).json()["rows"]]
    assert "Creó llave de API" in audit and "Revocó llave de API" in audit


def test_api_limite_de_peticiones_y_modulo_vencido(client, auth, keys):
    from app import main
    main.API_RATE.clear()
    activate(client, auth, keys, tuple(PRO))
    raw = client.post("/api/api-keys", json={"name": "ERP"}, headers=auth).json()["key"]
    h = {"X-API-Key": raw}
    codes = [client.get("/api/v1/ping", headers=h).status_code for _ in range(122)]
    assert codes.count(200) == 120 and codes[-1] == 429
    main.API_RATE.clear()
    # sin el módulo (la clave de Básico no lo trae) la llave deja de servir aunque exista
    from app.main import Company, SessionLocal
    db = SessionLocal()
    db.query(Company).first().license_key = ""
    db.commit()
    db.close()
    assert blocked(client.get("/api/v1/ping", headers=h))
    assert blocked(client.post("/api/api-keys", json={"name": "otra"}, headers=auth))


# ───────── límites de la clave y generador ─────────
def test_limite_de_usuarios_de_la_clave(client, auth, keys, login):
    activate(client, auth, keys, tuple(PRO), usuarios=2)
    lic = client.get("/api/license", headers=auth).json()
    assert lic["users_allowed"] == 2
    ok = client.post("/api/users", json={"name": "Segundo Usuario", "email": "u2@miempresa.hn", "password": "Clave-segura-1", "role": "Cajero"}, headers=auth)
    assert ok.status_code == 200
    third = client.post("/api/users", json={"name": "Tercer Usuario", "email": "u3@miempresa.hn", "password": "Clave-segura-1", "role": "Cajero"}, headers=auth)
    assert third.status_code == 403 and "2 usuario" in third.json()["detail"]
    # desactivar a alguien libera un lugar; reactivarlo cuando ya no hay lugar, no
    uid = ok.json()["id"]
    assert client.put(f"/api/users/{uid}", json={"name": "Segundo Usuario", "email": "u2@miempresa.hn", "role": "Cajero", "active": False}, headers=auth).status_code == 200
    assert client.post("/api/users", json={"name": "Tercer Usuario", "email": "u3@miempresa.hn", "password": "Clave-segura-1", "role": "Cajero"}, headers=auth).status_code == 200
    back = client.put(f"/api/users/{uid}", json={"name": "Segundo Usuario", "email": "u2@miempresa.hn", "role": "Cajero", "active": True}, headers=auth)
    assert back.status_code == 403


def test_generador_con_paquetes(tmp_path, keys, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "herramientas", "generador-de-claves.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert gen.resolver_modulos("profesional", []) == PRO
    assert gen.resolver_modulos("profesional", ["email", "rentabilidad"]) == PRO + ["email"]  # nombres anteriores aceptados, sin repetir lo que el paquete ya trae
    assert gen.resolver_modulos("", ["multi_bodega", "ventas_offline"]) == ["multi_warehouse", "offline"]
    assert gen.resolver_modulos("todo", []) == ["todo"] and gen.resolver_modulos("all", ["x"]) == ["todo"]
    with pytest.raises(SystemExit):
        gen.resolver_modulos("platino", [])
    inst = licencia.new_install_id()
    payload = licencia.pack(os.urandom(4), inst, date.today(), None, gen.resolver_modulos("empresarial", []), {})
    info = licencia.read_key(licencia.sign(keys, payload))
    assert set(info["modules"]) == set(EMP) and info["all"] is False and licencia.plan_of(info["modules"], info["all"]) == "empresarial"
    info_all = licencia.read_key(licencia.sign(keys, licencia.pack(os.urandom(4), inst, date.today(), None, ["todo"], {})))
    assert info_all["all"] and licencia.plan_of(info_all["modules"], info_all["all"]) == "todo"


def test_los_respaldos_programados_y_la_copia_secundaria_son_del_modulo(client, auth, keys, tmp_path):
    from app.main import Company, SessionLocal
    copy = str(tmp_path / "copia")
    db = SessionLocal()
    db.query(Company).first().backup_copy_dir = copy
    db.commit()
    db.close()
    end_trial(client)
    made = client.post("/api/backups", headers=auth).json()  # Básico: el respaldo manual funciona, pero sin copia secundaria
    assert not os.path.exists(copy) or made["name"] not in os.listdir(copy)
    activate(client, auth, keys, tuple(PRO))
    made2 = client.post("/api/backups", headers=auth).json()
    assert made2["name"] in os.listdir(copy)


def test_alerta_de_respaldo_y_pantallas_del_plan(client, auth, keys, monkeypatch, tmp_path):
    monkeypatch.setenv("COMANDIA_BACKUP_DIR", str(tmp_path / "respaldos-vacios"))  # una carpeta sin respaldos de otras pruebas
    titles = [a["title"] for a in client.get("/api/dashboard/insights", headers=auth).json()["alerts"]]
    assert "Aún no hay respaldos" in titles  # un negocio sin respaldo se entera desde el inicio
    assert client.post("/api/backups", headers=auth).status_code == 200
    titles = [a["title"] for a in client.get("/api/dashboard/insights", headers=auth).json()["alerts"]]
    assert "Aún no hay respaldos" not in titles and "Sin respaldo reciente" not in titles
    page = client.get("/static/app.js").text
    for needle in ("applyPlanUi", "plan-badge", "apiHtml", 'modOn("compras")', 'modOn("advanced_credit")', 'modOn("email")', 'modOn("multi_warehouse")'):
        assert needle in page


def test_clave_basica_termina_la_prueba_y_deja_solo_lo_incluido(keys):
    """Una clave Básica (sin módulos) es válida: aunque la prueba siga corriendo, manda la clave y los módulos de pago quedan cerrados."""
    from datetime import date
    inst = licencia.new_install_id()
    key = issue(keys, inst, modules=())
    state = licencia.evaluate(inst, key, date.today(), date.today())  # prueba recién empezada
    assert state["valid"] and state["plan"] == "basico" and state["plan_label"] == "Básico" and not state["trial"]["active"]
    assert state["active"]["turnos_caja"] and not state["active"]["compras"]
    sin_clave = licencia.evaluate(inst, "", date.today(), date.today())  # sin clave y en prueba: todo abierto
    assert sin_clave["trial"]["active"] and sin_clave["active"]["compras"]
