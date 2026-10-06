"""Pruebas de la v2.9: cuadre del cierre de caja (fondo, contado, sobrante y faltante) y datos del talonario en la factura."""
from datetime import date, timedelta

from test_api import invoice, line, make_user, product


def test_cuadre_por_forma_de_pago_con_fondo_sobrante_y_faltante(client, auth, login):
    caja = make_user(client, auth, login, "Cajero", "Carla Caja")
    p = product(client, auth, "CEM-050")
    f = invoice(client, caja, [line(p, 2)]).json()
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 300, "method": "Efectivo"}, headers=caja)
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 100, "method": "Tarjeta"}, headers=caja)
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 50, "method": "Transferencia"}, headers=caja)

    # fondo de 500: en la gaveta deberían estar 800; hay 790 (faltan 10). Datáfono 100 (cuadra) y banco 60 (sobran 10).
    r = client.post("/api/cash/close/record", json={"opening": 500, "counted": {"Efectivo": 790, "Tarjeta": 100, "Transferencia": 60}, "note": "vuelto"}, headers=caja)
    assert r.status_code == 200, r.text
    lines = {x["method"]: x for x in r.json()["lines"]}
    assert lines["Efectivo"]["expected"] == 800 and lines["Efectivo"]["difference"] == -10
    assert lines["Tarjeta"]["difference"] == 0 and lines["Transferencia"]["difference"] == 10
    assert r.json()["difference"] == 0 and r.json()["result"] == "cuadra"

    r = client.post("/api/cash/close/record", json={"counted": {"Efectivo": 280}}, headers=caja)
    assert r.json()["difference"] == -20 and r.json()["result"] == "faltan L 20.00"
    log = [x for x in client.get("/api/audit", headers=auth).json()["rows"] if x["action"] == "Registró cierre de caja"]
    assert len(log) == 2 and "Carla Caja" in log[-1]["detail"] and "faltan L 10.00" in log[-1]["detail"] and "vuelto" in log[-1]["detail"]

    assert client.post("/api/cash/close/record", json={"counted": {}}, headers=caja).status_code == 400
    assert client.post("/api/cash/close/record", json={"counted": {"Efectivo": -1}}, headers=caja).status_code == 400
    assert client.get("/api/cash/close", headers=caja).json()["company"]["name"]


def test_factura_trae_fecha_de_recepcion_del_cai_y_direccion(client, auth):
    s = client.get("/api/settings", headers=auth).json()
    cai = next(c for c in s["cai"] if c["doc_type"] == "01" and c["active"])
    assert client.post(f"/api/cai/{cai['id']}/received", json={"received_date": "2026-07-22"}, headers=auth).status_code == 200
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 1)]).json()
    d = client.get(f"/api/documents/{f['id']}", headers=auth).json()["document"]
    assert d["cai"] == cai["cai"] and d["cai_received"] == "2026-07-22"
    assert "client_address" in d
    pdf = client.get(f"/api/documents/{f['id']}/pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    # un CAI nuevo puede traer la fecha de recepción desde el inicio
    r = client.post("/api/cai", json={"cai": "ABCDEF-123456-ABCDEF-123456-ABCDEF-12", "doc_type": "06", "range_from": 1, "range_to": 10,
                                      "limit_date": (date.today() + timedelta(days=90)).isoformat(), "received_date": "2026-07-01"}, headers=auth)
    assert r.status_code == 200
    row = next(c for c in client.get("/api/settings", headers=auth).json()["cai"] if c["id"] == r.json()["id"])
    assert row["received_date"] == "2026-07-01"
