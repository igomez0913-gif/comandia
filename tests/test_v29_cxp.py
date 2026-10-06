"""Pruebas de la v2.9: cuentas por pagar a proveedores."""
from datetime import timedelta

from app.main import today_local
from test_api import ids, make_user, product


def purchase(client, auth, terms="30 días", **extra):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    sup = client.get("/api/suppliers", headers=auth).json()[0]
    body = {"supplier_id": sup["id"], "warehouse_id": i["wh"]["id"], "payment_terms": terms, "supplier_invoice": "000-001-01-00001234",
            "items": [{"product_id": p["id"], "presentation_id": p["presentations"][0]["id"], "qty": 10, "unit_cost": 100}], **extra}
    r = client.post("/api/purchases", json=body, headers=auth)
    assert r.status_code == 200, r.text
    return client.get(f"/api/purchases/{r.json()['id']}", headers=auth).json()


def test_compra_a_credito_queda_por_pagar(client, auth):
    p = purchase(client, auth)
    assert p["credit"] and p["total"] == 1150 and p["balance"] == 1150 and p["pay_status"] == "Pendiente"
    assert p["due_date"] == (today_local() + timedelta(days=30)).isoformat() and p["supplier_invoice"] == "000-001-01-00001234"
    data = client.get("/api/payables", headers=auth).json()
    assert data["total"] == 1150 and data["rows"][0]["number"] == p["number"] and data["by_supplier"][0]["balance"] == 1150


def test_compra_de_contado_no_queda_por_pagar(client, auth):
    bank = client.get("/api/banks", headers=auth).json()["banks"][0]
    p = purchase(client, auth, terms="Contado", pay_bank_id=bank["id"])
    assert not p["credit"] and p["balance"] == 0 and p["pay_status"] == "Pagada"
    after = next(b for b in client.get("/api/banks", headers=auth).json()["banks"] if b["id"] == bank["id"])
    assert round(bank["balance"] - after["balance"], 2) == 1150
    assert client.get("/api/payables", headers=auth).json()["rows"] == []
    assert client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 1}, headers=auth).status_code == 400
    # a crédito no se paga al registrar
    i = ids(client, auth)
    r = client.post("/api/purchases", json={"supplier_id": 1, "warehouse_id": i["wh"]["id"], "payment_terms": "30 días", "pay_bank_id": bank["id"], "total": 10}, headers=auth)
    assert r.status_code == 400


def test_abonos_al_proveedor_y_banco(client, auth):
    p = purchase(client, auth)
    bank = client.get("/api/banks", headers=auth).json()["banks"][0]
    r = client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 500, "method": "Transferencia", "bank_id": bank["id"], "note": "TRF 889"}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["balance"] == 650 and r.json()["pay_status"] == "Parcial" and r.json()["payments"][0]["note"] == "TRF 889"
    moves = client.get(f"/api/banks?bank_id={bank['id']}", headers=auth).json()["moves"]
    assert moves[0]["kind"] == "egreso" and moves[0]["amount"] == 500 and p["number"] in moves[0]["concept"]
    assert client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 651}, headers=auth).status_code == 400
    assert client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 10, "method": "Retención ISV"}, headers=auth).status_code == 400
    r = client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 650, "method": "Cheque", "note": "CHQ 1002"}, headers=auth)
    assert r.json()["pay_status"] == "Pagada" and r.json()["balance"] == 0
    assert client.get("/api/payables", headers=auth).json()["total"] == 0
    # con pagos ya no se anula
    r = client.post(f"/api/purchases/{p['id']}/void", headers=auth)
    assert r.status_code == 400 and "pagos" in r.json()["detail"]
    assert client.get("/api/audit", headers=auth).json()["rows"][0]["action"] == "Pagó a proveedor"


def test_banco_sin_saldo_no_paga(client, auth):
    p = purchase(client, auth)
    caja_chica = next(b for b in client.get("/api/banks", headers=auth).json()["banks"] if b["balance"] < 1150)
    r = client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 1150, "bank_id": caja_chica["id"]}, headers=auth)
    assert r.status_code == 400 and "Saldo insuficiente" in r.json()["detail"]
    assert client.get(f"/api/purchases/{p['id']}", headers=auth).json()["balance"] == 1150  # no quedó a medias


def test_vencidas_y_reporte(client, auth):
    vencida = purchase(client, auth, terms="15 días", due_date=(today_local() - timedelta(days=5)).isoformat())
    purchase(client, auth, terms="45 días")
    data = client.get("/api/payables", headers=auth).json()
    row = next(r for r in data["rows"] if r["id"] == vencida["id"])
    assert row["pay_status"] == "Vencida" and row["days_late"] == 5 and data["overdue"] == 1150
    csv = client.get("/api/reports/cxp.csv", headers=auth).content.decode("utf-8-sig")
    assert "Factura proveedor" in csv.splitlines()[0] and vencida["number"] in csv and "Vencida" in csv


def test_permisos_y_limpieza(client, auth, login):
    p = purchase(client, auth)
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/payables", headers=caja).status_code == 403
    assert client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 1}, headers=caja).status_code == 403
    cont = make_user(client, auth, login, "Contador")
    assert client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 100}, headers=cont).status_code == 200
    r = client.post("/api/admin/reset", json={"mode": "movimientos", "password": "comandia123", "confirm": "LIMPIAR", "backup": False}, headers=auth)
    assert r.status_code == 200, r.text
    assert client.get("/api/payables", headers=auth).json()["rows"] == []
