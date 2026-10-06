"""Pruebas de la v2.9: descuentos y rebajas por línea en facturas, cotizaciones y notas de crédito."""
from test_api import invoice, line, make_user, product


def test_descuento_rebaja_la_linea_antes_del_isv(client, auth):
    p = product(client, auth, "CEM-050")  # 245.00 gravado 15 %
    item = {**line(p, 4), "discount": 80}  # 980 − 80 = 900
    r = invoice(client, auth, [item])
    assert r.status_code == 200, r.text
    f = r.json()
    assert f["items"][0]["discount"] == 80 and f["items"][0]["total"] == 900
    assert f["discount"] == 80 and f["gravado_15"] == 900 and f["isv_15"] == 135 and f["total"] == 1035
    pdf = client.get(f"/api/documents/{f['id']}/pdf", headers=auth)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")


def test_descuento_no_puede_pasar_del_importe(client, auth):
    p = product(client, auth, "CEM-050")
    r = invoice(client, auth, [{**line(p, 1), "discount": 300}])
    assert r.status_code == 400 and "mayor que el importe" in r.json()["detail"]
    assert invoice(client, auth, [{**line(p, 1), "discount": -5}]).status_code == 422


def test_cajero_y_vendedor_necesitan_pin_de_supervisor(client, auth, login):
    p = product(client, auth, "CEM-050")
    sup = make_user(client, auth, login, "Supervisor", "Sara Supervisora")
    # el supervisor define su PIN con su clave
    assert client.post("/api/me/pin", json={"password": "mala", "pin": "4321"}, headers=sup).status_code == 400
    assert client.post("/api/me/pin", json={"password": "clave123", "pin": "12a4"}, headers=sup).status_code == 400
    assert client.post("/api/me/pin", json={"password": "clave123", "pin": "4321"}, headers=sup).json()["has_pin"] is True
    assert client.get("/api/me", headers=sup).json()["has_pin"] is True
    # otro autorizador no puede repetir el mismo PIN
    assert client.post("/api/me/pin", json={"password": "comandia123", "pin": "4321"}, headers=auth).status_code == 400
    for role in ("Cajero", "Vendedor"):
        h = make_user(client, auth, login, role)
        assert client.post("/api/me/pin", json={"password": "clave123", "pin": "1111"}, headers=h).status_code == 403
        r = invoice(client, h, [{**line(p, 1), "discount": 10}])
        assert r.status_code == 403 and "PIN" in r.json()["detail"], role
        r = invoice(client, h, [{**line(p, 1), "discount": 10}], auth_pin="0000")
        assert r.status_code == 403 and "no es correcto" in r.json()["detail"], role
        r = invoice(client, h, [{**line(p, 1), "discount": 10}], auth_pin="4321")
        assert r.status_code == 200, r.text
        assert r.json()["discount"] == 10 and r.json()["discount_auth"] == "Sara Supervisora"
        assert invoice(client, h, [line(p, 1)]).status_code == 200  # sin descuento no pide nada
    log = client.get("/api/audit", headers=auth).json()["rows"]
    assert any(x["action"] == "Descuento autorizado" and "Sara Supervisora" in x["detail"] for x in log)
    assert any(x["action"] == "PIN de autorización incorrecto" for x in log)
    # quien tiene el permiso no necesita PIN y no queda «autorizado por»
    r = invoice(client, sup, [{**line(p, 1), "discount": 10}])
    assert r.status_code == 200 and r.json()["discount_auth"] == ""


def test_pin_bloquea_tras_5_intentos_y_sirve_en_punto_de_venta(client, auth, login):
    p = product(client, auth, "CEM-050")
    client.post("/api/me/pin", json={"password": "comandia123", "pin": "987654"}, headers=auth)
    caja = make_user(client, auth, login, "Cajero")
    from test_api import ids
    i = ids(client, auth)
    sale = {"client_id": i["final"]["id"], "warehouse_id": i["wh"]["id"], "items": [{**line(p, 2), "discount": 40}]}
    total = round(450 * 1.15, 2)
    ok = client.post("/api/pos/sale", json={**sale, "payments": [{"method": "Efectivo", "amount": total}], "auth_pin": "987654"}, headers=caja)
    assert ok.status_code == 200, ok.text
    for _ in range(5):
        assert client.post("/api/pos/sale", json={**sale, "payments": [{"method": "Efectivo", "amount": total}], "auth_pin": "111111"}, headers=caja).status_code == 403
    blocked = client.post("/api/pos/sale", json={**sale, "payments": [{"method": "Efectivo", "amount": total}], "auth_pin": "987654"}, headers=caja)
    assert blocked.status_code == 429
    # quitar el PIN
    assert client.post("/api/me/pin", json={"password": "comandia123", "pin": ""}, headers=auth).json()["has_pin"] is False


def test_cotizacion_con_descuento_pasa_a_la_factura(client, auth):
    p = product(client, auth, "CEM-050")
    q = invoice(client, auth, [{**line(p, 2), "discount": 40}], kind="cotizacion").json()
    f = client.post(f"/api/documents/{q['id']}/invoice", headers=auth).json()
    assert f["discount"] == 40 and f["items"][0]["total"] == 450 and f["total"] == q["total"]


def test_nota_de_credito_repite_el_descuento_de_la_factura(client, auth, login):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [{**line(p, 4), "discount": 80}]).json()  # neto 900 + ISV = 1 035
    # la nota de 1 unidad lleva su parte del descuento (20); quien solo tiene «anular» también puede emitirla
    n = invoice(client, auth, [{**line(p, 1), "discount": 20}], kind="nota", ref_document_id=f["id"])
    assert n.status_code == 200, n.text
    assert n.json()["total"] == round(225 * 1.15, 2)
    inv = client.get(f"/api/documents/{f['id']}", headers=auth).json()["document"]
    assert inv["balance"] == round(1035 - 258.75, 2)
