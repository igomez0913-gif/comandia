"""Pruebas de la v2.9: módulo Multi-tienda (tiendas, CAI por establecimiento, usuarios limitados a su tienda)."""
from datetime import date, timedelta

from app import licencia
from test_api import ids, invoice, line, product
from test_v29_licencia import end_trial, install_id, issue, keys  # noqa: F401


def new_store(client, auth, code="002", name="Sucursal Norte"):
    return client.post("/api/stores", json={"code": code, "name": name, "address": "Col. Norte"}, headers=auth)


def add_cai(client, auth, establishment):
    body = {"cai": "C3D4E5-F6A7B8-990011-CCDDEE-FF0033", "doc_type": "01", "establishment": establishment, "emission_point": "001", "range_from": 1, "range_to": 500,
            "limit_date": (date.today() + timedelta(days=200)).isoformat()}
    r = client.post("/api/cai", json=body, headers=auth)
    assert r.status_code == 200, r.text


def test_cada_tienda_usa_el_cai_de_su_establecimiento(client, auth):
    stores = client.get("/api/stores", headers=auth).json()
    assert len(stores) == 1 and stores[0]["main"] and stores[0]["code"] == "001"
    sid = new_store(client, auth).json()["id"]
    assert new_store(client, auth).status_code == 400  # código repetido
    assert client.post("/api/stores", json={"code": "ab", "name": "X"}, headers=auth).status_code == 400
    whs = client.get("/api/warehouses", headers=auth).json()
    assert client.put(f"/api/warehouses/{whs[1]['id']}", json={"code": whs[1]["code"], "name": whs[1]["name"], "address": "", "store_id": sid}, headers=auth).status_code == 200
    assert next(w for w in client.get("/api/warehouses", headers=auth).json() if w["id"] == whs[1]["id"])["store"] == "Sucursal Norte"
    p = product(client, auth, "CEM-050")
    i = ids(client, auth)
    # con dos tiendas y sin CAI 002, la sucursal no puede facturar con el CAI de la principal
    r = invoice(client, auth, [line(p, 1)], warehouse_id=whs[1]["id"])
    assert r.status_code == 400 and "tienda 002" in r.json()["detail"]
    add_cai(client, auth, "002")
    main = invoice(client, auth, [line(p, 1)])
    branch = invoice(client, auth, [line(p, 1)], warehouse_id=whs[1]["id"])
    assert main.status_code == 200 and main.json()["number"].startswith("001-")
    assert branch.status_code == 200 and branch.json()["number"].startswith("002-") and branch.json()["store_id"] == sid
    only = client.get(f"/api/documents?kind=factura&store_id={sid}", headers=auth).json()
    assert [d["number"] for d in only] == [branch.json()["number"]]
    mine = client.get("/api/stores", headers=auth).json()
    assert next(s for s in mine if s["id"] == sid)["sales_month"] > 0 and next(s for s in mine if s["main"])["warehouses"] >= 2


def test_usuario_de_una_tienda_solo_ve_y_vende_en_la_suya(client, auth, login):
    sid = new_store(client, auth).json()["id"]
    whs = client.get("/api/warehouses", headers=auth).json()
    client.put(f"/api/warehouses/{whs[1]['id']}", json={"code": whs[1]["code"], "name": whs[1]["name"], "address": "", "store_id": sid}, headers=auth)
    add_cai(client, auth, "002")
    r = client.post("/api/users", json={"name": "Caja Norte", "email": "norte@miempresa.hn", "password": "clave123", "role": "Cajero", "store_id": sid}, headers=auth)
    assert r.status_code == 200, r.text
    caja = login(client, "norte@miempresa.hn", "clave123")
    assert [w["id"] for w in client.get("/api/warehouses", headers=caja).json()] == [whs[1]["id"]]
    assert [s["id"] for s in client.get("/api/stores", headers=caja).json()] == [sid]
    p = product(client, auth, "CEM-050")
    c = ids(client, auth)["con_rtn"]
    body = {"kind": "factura", "client_id": c["id"], "items": [line(p, 1)]}
    denied = client.post("/api/documents", json={**body, "warehouse_id": whs[0]["id"]}, headers=caja)
    assert denied.status_code == 403 and "su tienda" in denied.json()["detail"]
    ok = client.post("/api/documents", json={**body, "warehouse_id": whs[1]["id"]}, headers=caja)
    assert ok.status_code == 200 and ok.json()["number"].startswith("002-")
    invoice(client, auth, [line(p, 1)])  # una venta de la principal que la caja del norte no debe ver
    seen = client.get("/api/documents?kind=factura", headers=caja).json()
    assert seen and all(d["store_id"] == sid for d in seen)


def test_limite_y_modulo_de_tiendas(client, auth, keys):
    end_trial(client)
    blocked = new_store(client, auth)
    assert blocked.status_code == 403 and "Multi-tienda" in blocked.json()["detail"]
    inst = install_id(client, auth)
    key = issue(keys, inst, modules=("multi_tienda",), tiendas=2)
    assert client.post("/api/license", json={"key": key}, headers=auth).json()["stores_allowed"] == 2
    assert new_store(client, auth).status_code == 200
    third = new_store(client, auth, "003", "Otra")
    assert third.status_code == 403 and "2 tienda" in third.json()["detail"]
    # sin el módulo, las ventas siguen sin pedir tienda ni CAI por establecimiento
    p = product(client, auth, "CEM-050")
    assert invoice(client, auth, [line(p, 1)]).status_code == 200


def test_reportes_y_cierre_de_caja_por_tienda(client, auth):
    sid = new_store(client, auth).json()["id"]
    whs = client.get("/api/warehouses", headers=auth).json()
    client.put(f"/api/warehouses/{whs[1]['id']}", json={"code": whs[1]["code"], "name": whs[1]["name"], "address": "", "store_id": sid}, headers=auth)
    add_cai(client, auth, "002")
    p = product(client, auth, "CEM-050")
    invoice(client, auth, [line(p, 1)])
    invoice(client, auth, [line(p, 3)], warehouse_id=whs[1]["id"])
    total = client.get("/api/reports?period=all", headers=auth).json()["libro_ventas"]["total"]
    norte = client.get(f"/api/reports?period=all&store_id={sid}", headers=auth).json()["libro_ventas"]["total"]
    principal = client.get("/api/stores", headers=auth).json()[0]["id"]
    sede = client.get(f"/api/reports?period=all&store_id={principal}", headers=auth).json()["libro_ventas"]["total"]
    assert 0 < norte < total and abs(norte + sede - total) < 0.01
    csv_norte = client.get(f"/api/reports/libro-ventas.csv?period=all&store_id={sid}", headers=auth).text
    assert "002-001-01-" in csv_norte and "001-001-01-00" not in csv_norte.split("\n", 1)[1]
    close = client.get(f"/api/cash/close?store_id={sid}", headers=auth).json()
    all_close = client.get("/api/cash/close", headers=auth).json()
    assert 0 < close["sales"]["invoiced"] < all_close["sales"]["invoiced"]  # el cuadre de la tienda solo suma lo suyo


def test_punto_de_venta_se_puede_ocultar(client, auth):
    base = {"name": "X", "rtn": "08019999123456"}
    assert client.get("/api/settings", headers=auth).json()["pos_enabled"] is True
    assert client.put("/api/settings", json={**base, "pos_enabled": False}, headers=auth).status_code == 200
    assert client.get("/api/settings", headers=auth).json()["pos_enabled"] is False
    assert client.put("/api/settings", json=base, headers=auth).status_code == 200  # sin el campo, no cambia
    assert client.get("/api/settings", headers=auth).json()["pos_enabled"] is False
    assert client.put("/api/settings", json={**base, "pos_enabled": True}, headers=auth).status_code == 200
    assert client.get("/api/settings", headers=auth).json()["pos_enabled"] is True


def test_turnos_de_caja_por_tienda(client, auth, login):
    sid = new_store(client, auth).json()["id"]
    main = client.get("/api/stores", headers=auth).json()[0]["id"]
    r = client.post("/api/shifts/open", json={"caja": "Caja 1", "opening": 100, "store_id": sid}, headers=auth)
    assert r.status_code == 200 and r.json()["store_id"] == sid and r.json()["store"] == "Sucursal Norte"
    # el mismo nombre de caja se puede usar en otra tienda, pero un usuario no abre dos turnos a la vez
    cajero = client.post("/api/users", json={"name": "Caja Principal", "email": "cp@miempresa.hn", "password": "clave123", "role": "Cajero", "store_id": main}, headers=auth)
    assert cajero.status_code == 200
    h = login(client, "cp@miempresa.hn", "clave123")
    ok = client.post("/api/shifts/open", json={"caja": "Caja 1", "opening": 50, "store_id": sid}, headers=h)  # intenta abrir en la otra tienda: se ignora, abre en la suya
    assert ok.status_code == 200 and ok.json()["store_id"] == main
    norte = client.get(f"/api/shifts?store_id={sid}", headers=auth).json()["rows"]
    assert [x["store_id"] for x in norte] == [sid]
    assert len(client.get("/api/shifts", headers=auth).json()["rows"]) == 2
    assert [x["store_id"] for x in client.get("/api/shifts", headers=h).json()["rows"]] == [main]
    # la misma caja en la misma tienda sigue ocupada
    other = client.post("/api/users", json={"name": "Otra Caja", "email": "oc@miempresa.hn", "password": "clave123", "role": "Cajero", "store_id": main}, headers=auth)
    busy = client.post("/api/shifts/open", json={"caja": "caja 1", "opening": 0}, headers=login(client, "oc@miempresa.hn", "clave123"))
    assert busy.status_code == 400 and "ya tiene un turno abierto" in busy.json()["detail"]
