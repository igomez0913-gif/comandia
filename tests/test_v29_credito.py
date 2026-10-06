"""Pruebas de la v2.9: límite de crédito y bloqueo por facturas vencidas, con autorización por PIN."""
from datetime import timedelta

from test_api import ids, line, make_user, product


def new_client(client, auth, **extra):
    body = {"name": "Constructora Prueba Crédito", "rtn": "08011999000111", **extra}
    r = client.post("/api/clients", json=body, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def sell(client, h, cid, items, terms="30 días", **extra):
    i = ids(client, h)
    return client.post("/api/documents", json={"kind": "factura", "client_id": cid, "warehouse_id": i["wh"]["id"], "items": items, "payment_terms": terms, **extra}, headers=h)


def test_limite_de_credito_y_autorizacion(client, auth, login):
    p = product(client, auth, "CEM-050")  # 245 + ISV = 281.75 por saco
    cid = new_client(client, auth, credit_limit=600)
    row = next(c for c in client.get("/api/clients", headers=auth).json() if c["id"] == cid)
    assert row["credit_limit"] == 600 and row["available"] == 600 and row["balance"] == 0
    caja = make_user(client, auth, login, "Cajero")
    assert sell(client, caja, cid, [line(p, 2)]).status_code == 200  # 563.50 dentro del límite
    r = sell(client, caja, cid, [line(p, 1)])  # pasaría a 845.25
    assert r.status_code == 403 and "límite" in r.json()["detail"]
    assert sell(client, caja, cid, [line(p, 1)], terms="Contado").status_code == 200  # de contado no hay límite
    sup = make_user(client, auth, login, "Supervisor", "Sara Supervisora")
    client.post("/api/me/pin", json={"password": "clave123", "pin": "5555"}, headers=sup)
    ok = sell(client, caja, cid, [line(p, 1)], auth_pin="5555")
    assert ok.status_code == 200 and ok.json()["credit_auth"] == "Sara Supervisora"
    # quien tiene el permiso «credito» vende sin PIN, pero queda en la bitácora
    assert sell(client, sup, cid, [line(p, 1)]).status_code == 200
    actions = [a["action"] for a in client.get("/api/audit", headers=auth).json()["rows"]]
    assert "Crédito autorizado" in actions and "Vendió al crédito con excepción" in actions
    row = next(c for c in client.get("/api/clients", headers=auth).json() if c["id"] == cid)
    assert row["balance"] > 600 and row["available"] == 0


def test_bloqueo_por_facturas_vencidas(client, auth, login):
    from app.main import Document, SessionLocal, today_local
    p = product(client, auth, "CEM-050")
    cid = new_client(client, auth)
    f = sell(client, auth, cid, [line(p, 1)]).json()
    db = SessionLocal()
    d = db.get(Document, f["id"])
    d.due_date = today_local() - timedelta(days=3)
    db.commit()
    db.close()
    row = next(c for c in client.get("/api/clients", headers=auth).json() if c["id"] == cid)
    assert row["overdue"] == f["total"] and row["overdue_count"] == 1
    vend = make_user(client, auth, login, "Vendedor")
    r = sell(client, vend, cid, [line(p, 1)])
    assert r.status_code == 403 and "vencidos" in r.json()["detail"]
    # PIN equivocado: no queda ninguna factura a medias y se registra el intento
    before = len(client.get("/api/documents", headers=auth).json())
    assert sell(client, vend, cid, [line(p, 1)], auth_pin="0000").status_code == 403
    assert len(client.get("/api/documents", headers=auth).json()) == before
    # sin bloqueo por mora, se le puede vender al crédito
    body = {"name": "Constructora Prueba Crédito", "rtn": "08011999000111", "block_overdue": False}
    assert client.put(f"/api/clients/{cid}", json=body, headers=auth).status_code == 200
    assert sell(client, vend, cid, [line(p, 1)]).status_code == 200


def test_solo_credito_cambia_el_limite(client, auth, login):
    cid = new_client(client, auth, credit_limit=1000)
    caja = make_user(client, auth, login, "Cajero")
    client.put(f"/api/clients/{cid}", json={"name": "Otro nombre", "rtn": "08011999000111", "credit_limit": 999999, "block_overdue": False}, headers=caja)
    row = next(c for c in client.get("/api/clients", headers=auth).json() if c["id"] == cid)
    assert row["name"] == "Otro nombre" and row["credit_limit"] == 1000 and row["block_overdue"] is True
