"""Pruebas de la v2.9: punto de venta (factura de contado y cobro en una sola operación)."""
from test_api import ids, line, make_user, product, stock

POS = "/api/pos/sale"


def sale(client, auth, items, payments, client_key="con_rtn", **extra):
    i = ids(client, auth)
    body = {"client_id": i[client_key]["id"], "warehouse_id": i["wh"]["id"], "items": items, "payments": payments, **extra}
    return client.post(POS, json=body, headers=auth)


def test_venta_en_efectivo_con_vuelto(client, auth, login):
    caja = make_user(client, auth, login, "Cajero", "Carla Caja")
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    r = sale(client, caja, [line(p, 2)], [{"method": "Efectivo", "amount": 563.50}], received=600)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["total"] == 563.5 and d["status"] == "Pagada" and d["balance"] == 0 and d["change"] == 36.5
    assert d["user"] == "Carla Caja" and d["payments"][0]["user"] == "Carla Caja"
    assert "Recibido L 600.00 · cambio L 36.50" in d["payments"][0]["note"]
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) == before - 2
    corte = client.get("/api/cash/close", headers=caja).json()
    assert corte["collected"] == 563.5 and corte["cash"] == 563.5
    assert client.get("/api/audit", headers=auth).json()["rows"][0]["action"] == "Venta de mostrador"


def test_pago_mixto_y_deposito_a_banco(client, auth):
    p = product(client, auth, "CEM-050")
    bank = client.get("/api/banks", headers=auth).json()["banks"][0]
    r = sale(client, auth, [line(p, 2)], [{"method": "Efectivo", "amount": 300}, {"method": "Tarjeta", "amount": 263.5, "bank_id": bank["id"], "note": "POS 1234"}], received=300)
    assert r.status_code == 200, r.text
    d = r.json()
    assert [x["method"] for x in d["payments"]] == ["Efectivo", "Tarjeta"] and d["change"] == 0 and d["status"] == "Pagada"
    after = next(b for b in client.get("/api/banks", headers=auth).json()["banks"] if b["id"] == bank["id"])
    assert round(after["balance"] - bank["balance"], 2) == 263.5


def test_si_los_pagos_no_cuadran_no_se_emite_nada(client, auth):
    p = product(client, auth, "CEM-050")
    n_before = len(client.get("/api/documents?kind=factura", headers=auth).json())
    r = sale(client, auth, [line(p, 2)], [{"method": "Efectivo", "amount": 500}])
    assert r.status_code == 400 and "Falta L 63.50" in r.json()["detail"]
    r = sale(client, auth, [line(p, 2)], [{"method": "Efectivo", "amount": 563.50}], received=500)
    assert r.status_code == 400 and "no alcanza" in r.json()["detail"]
    assert len(client.get("/api/documents?kind=factura", headers=auth).json()) == n_before
    # el correlativo no se gastó: la siguiente venta toma el número que tocaba
    ok = sale(client, auth, [line(p, 1)], [{"method": "Tarjeta", "amount": 281.75}]).json()
    assert ok["number"] == "001-001-01-00002459"


def test_quien_puede_usar_el_punto_de_venta(client, auth, login):
    p = product(client, auth, "CEM-050")
    pay = [{"method": "Efectivo", "amount": 281.75}]
    vend = make_user(client, auth, login, "Vendedor")
    r = sale(client, vend, [line(p, 1)], pay)
    assert r.status_code == 403 and "cobrar" in r.json()["detail"]
    bod = make_user(client, auth, login, "Bodeguero")
    assert sale(client, bod, [line(p, 1)], pay).status_code == 403
    caja = make_user(client, auth, login, "Cajero")
    assert sale(client, caja, [line(p, 1, price=1)], [{"method": "Efectivo", "amount": 1.15}]).status_code == 403  # precio libre
    assert sale(client, auth, [line(p, 1)], [{"method": "Bitcoin", "amount": 281.75}]).status_code == 400


def test_precio_del_cliente_y_consumidor_final(client, auth):
    p = product(client, auth, "CEM-050")
    clients = client.get("/api/clients", headers=auth).json()
    mayorista = next(c for c in clients if c["price_level"] == 2)
    i = ids(client, auth)
    r = client.post(POS, json={"client_id": mayorista["id"], "warehouse_id": i["wh"]["id"], "items": [line(p, 1)],
                               "payments": [{"method": "Efectivo", "amount": 267.66}]}, headers=auth)
    assert r.status_code == 200 and r.json()["items"][0]["price"] == 232.75
    # consumidor final sin RTN, por cualquier monto
    r = sale(client, auth, [line(p, 1)], [{"method": "Efectivo", "amount": 281.75}], client_key="final")
    assert r.status_code == 200, r.text


def test_nombre_y_rtn_solo_para_esta_factura(client, auth):
    """Un comprador que no es cliente frecuente pide factura con su nombre y RTN: va a «Consumidor final»."""
    p = product(client, auth, "CEM-050")
    n_clients = len(client.get("/api/clients", headers=auth).json())
    r = sale(client, auth, [line(p, 2)], [{"method": "Efectivo", "amount": 563.50}], client_key="final",
             buyer_name="Ferretería La Esquina", buyer_rtn="0801-1990-12345 6")
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["client"], d["rtn"], d["client_account"]) == ("Ferretería La Esquina", "08011990123456", "Consumidor final")
    assert len(client.get("/api/clients", headers=auth).json()) == n_clients  # no se creó un cliente nuevo
    libro = client.get("/api/reports/libro-ventas.csv?period=all", headers=auth).content.decode("utf-8-sig")
    row = next(l for l in libro.splitlines() if d["number"] in l)
    assert "Ferretería La Esquina" in row and "08011990123456" in row
    pdf = client.get(f"/api/documents/{d['id']}/pdf", headers=auth)
    assert pdf.status_code == 200
    # la nota de crédito sale a nombre del mismo comprador
    i = ids(client, auth)
    n = client.post("/api/documents", json={"kind": "nota", "client_id": i["final"]["id"], "warehouse_id": i["wh"]["id"], "ref_document_id": d["id"],
                                            "items": [line(p, 1)]}, headers=auth).json()
    assert (n["client"], n["rtn"]) == ("Ferretería La Esquina", "08011990123456")


def test_validaciones_del_nombre_y_rtn(client, auth):
    p = product(client, auth, "CEM-050")
    pay = [{"method": "Efectivo", "amount": 281.75}]
    r = sale(client, auth, [line(p, 1)], pay, client_key="final", buyer_rtn="08011990123456")
    assert r.status_code == 400 and "nombre" in r.json()["detail"]
    r = sale(client, auth, [line(p, 1)], pay, client_key="final", buyer_name="Juan", buyer_rtn="123")
    assert r.status_code == 400 and "RTN" in r.json()["detail"]
    r = sale(client, auth, [line(p, 1)], pay, client_key="con_rtn", buyer_name="Otro", buyer_rtn="08011990123456")
    assert r.status_code == 400 and "Consumidor final" in r.json()["detail"]
    # solo el nombre, sin RTN, también se permite
    r = sale(client, auth, [line(p, 1)], pay, client_key="final", buyer_name="María López")
    assert r.status_code == 200 and r.json()["client"] == "María López" and r.json()["rtn"] == ""


def test_cotizacion_con_nombre_se_factura_igual(client, auth):
    p = product(client, auth, "CEM-050")
    i = ids(client, auth)
    q = client.post("/api/documents", json={"kind": "cotizacion", "client_id": i["final"]["id"], "warehouse_id": i["wh"]["id"], "items": [line(p, 1)],
                                            "buyer_name": "Constructora Nueva", "buyer_rtn": "08019000999991"}, headers=auth).json()
    f = client.post(f"/api/documents/{q['id']}/invoice", headers=auth).json()
    assert (f["client"], f["rtn"]) == ("Constructora Nueva", "08019000999991")
