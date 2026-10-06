"""Pruebas de la v2.8: limpiar la base para instalar en un cliente nuevo."""
import os

from test_api import ids, invoice, line, make_user, product

RESET = "/api/admin/reset"


def reset(client, auth, mode="todo", password="comandia123", confirm="LIMPIAR", backup=False):
    return client.post(RESET, json={"mode": mode, "password": password, "confirm": confirm, "backup": backup}, headers=auth)


def test_solo_master_y_con_clave(client, auth, login):
    adm = make_user(client, auth, login, "Administrador")
    assert reset(client, adm, password="clave123").status_code == 403
    assert client.get("/api/admin/reset-check", headers=adm).status_code == 403
    r = reset(client, auth, password="mala")
    assert r.status_code == 400 and "clave" in r.json()["detail"]
    r = reset(client, auth, confirm="si")
    assert r.status_code == 400 and "LIMPIAR" in r.json()["detail"]
    assert reset(client, auth, mode="otro").status_code == 400
    assert client.get("/api/documents", headers=auth).json()  # no se borró nada


def test_limpiar_todo_deja_la_base_en_blanco(client, auth, login):
    make_user(client, auth, login, "Cajero")
    check = client.get("/api/admin/reset-check", headers=auth).json()
    assert check["allowed"] and check["counts"]["productos"] > 0
    r = reset(client, auth)
    assert r.status_code == 200, r.text
    assert client.get("/api/documents", headers=auth).json() == []
    assert client.get("/api/products", headers=auth).json() == []
    assert [c["name"] for c in client.get("/api/clients", headers=auth).json()] == ["Consumidor final"]
    assert [w["name"] for w in client.get("/api/warehouses", headers=auth).json()] == ["Bodega principal"]
    assert [u["email"] for u in client.get("/api/users", headers=auth).json()] == ["luis@miempresa.hn"]
    s = client.get("/api/settings", headers=auth).json()
    assert s["cai"] == [] and s["series"] == []
    assert client.get("/api/banks", headers=auth).json()["banks"] == []
    audit = client.get("/api/audit", headers=auth).json()["rows"]
    assert [a["action"] for a in audit] == ["Limpió la base de datos"]
    # el mismo Master sigue entrando
    assert client.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": "comandia123"}).status_code == 200


def test_despues_de_limpiar_se_puede_trabajar(client, auth):
    from datetime import timedelta

    from app.main import today_local
    reset(client, auth)
    cai = {"cai": "REAL01-REAL02-REAL03-REAL04-REAL05-01", "doc_type": "01", "range_from": 1, "range_to": 100,
           "limit_date": (today_local() + timedelta(days=200)).isoformat()}
    assert client.post("/api/cai", json=cai, headers=auth).status_code == 200
    dep = client.post("/api/departments", json={"name": "General"}, headers=auth)
    assert dep.status_code == 200, dep.text
    dep_id = client.get("/api/departments", headers=auth).json()["departments"][0]["id"]
    assert client.post("/api/categories", json={"name": "Varios", "department_id": dep_id}, headers=auth).status_code == 200
    cat_id = client.get("/api/departments", headers=auth).json()["categories"][0]["id"]
    assert client.post("/api/products", json={"sku": "P-1", "name": "Producto", "department_id": dep_id, "category_id": cat_id, "price": 50}, headers=auth).status_code == 200
    p = product(client, auth, "P-1")
    wh = client.get("/api/warehouses", headers=auth).json()[0]
    client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": wh["id"], "qty": 10, "concept": "Inventario inicial"}, headers=auth)
    cf = client.get("/api/clients", headers=auth).json()[0]
    f = client.post("/api/documents", json={"kind": "factura", "client_id": cf["id"], "warehouse_id": wh["id"], "items": [line(p, 1)]}, headers=auth)
    assert f.status_code == 200, f.text
    assert f.json()["number"] == "001-001-01-00000001"
    # ya hay una factura con CAI real: no se puede volver a limpiar
    r = reset(client, auth)
    assert r.status_code == 400 and "CAI real" in r.json()["detail"]
    assert client.get("/api/admin/reset-check", headers=auth).json()["allowed"] is False


def test_limpiar_solo_movimientos_conserva_catalogo(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    invoice(client, auth, [line(p, 2)])
    products_before = len(client.get("/api/products", headers=auth).json())
    clients_before = len(client.get("/api/clients", headers=auth).json())
    assert reset(client, auth, mode="movimientos").status_code == 200
    assert client.get("/api/documents", headers=auth).json() == []
    assert len(client.get("/api/products", headers=auth).json()) == products_before
    assert len(client.get("/api/clients", headers=auth).json()) == clients_before
    assert product(client, auth, "CEM-050")["stock"] == 0
    banks = client.get("/api/banks", headers=auth).json()
    assert banks["banks"] and all(b["balance"] == 0 for b in banks["banks"]) and banks["moves"] == []
    assert client.get("/api/settings", headers=auth).json()["cai"]  # el CAI se conserva
    assert i["wh"]["id"] in [w["id"] for w in client.get("/api/warehouses", headers=auth).json()]


def test_limpiar_con_respaldo(client, auth, tmp_path, monkeypatch):
    monkeypatch.setenv("COMANDIA_BACKUP_DIR", str(tmp_path))
    r = reset(client, auth, backup=True)
    if os.environ.get("TEST_DATABASE_URL", "").startswith("mysql"):
        assert r.status_code in (200, 500)  # depende de que exista mysqldump en el equipo
        return
    assert r.status_code == 200, r.text
    saved = r.json()["backup"]
    assert saved and os.path.exists(saved) and os.path.getsize(saved) > 0
    assert "respaldo" in client.get("/api/audit", headers=auth).json()["rows"][0]["detail"]
