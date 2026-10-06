"""Pruebas de la v2.9: clientes exonerados (Orden de Compra Exenta) y retenciones de ISV."""
from test_api import ids, line, make_user, product


def exonerated_client(client, auth, **extra):
    body = {"name": "Hospital Escuela", "rtn": "08019000123450", "exonerated": True, "exo_registry": "RE-2026-00155", "sag_registry": "SAG-778", **extra}
    r = client.post("/api/clients", json=body, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def doc(client, auth, cid, items, kind="factura", **extra):
    i = ids(client, auth)
    return client.post("/api/documents", json={"kind": kind, "client_id": cid, "warehouse_id": i["wh"]["id"], "items": items, **extra}, headers=auth)


def test_cliente_exonerado_necesita_constancia(client, auth):
    r = client.post("/api/clients", json={"name": "Sin constancia", "exonerated": True}, headers=auth)
    assert r.status_code == 400 and "constancia" in r.json()["detail"]
    cid = exonerated_client(client, auth)
    c = next(x for x in client.get("/api/clients", headers=auth).json() if x["id"] == cid)
    assert c["exonerated"] and c["exo_registry"] == "RE-2026-00155" and c["sag_registry"] == "SAG-778"


def test_factura_exonerada_sin_isv_y_con_orden_de_compra(client, auth):
    cid = exonerated_client(client, auth)
    p = product(client, auth, "CEM-050")
    r = doc(client, auth, cid, [line(p, 2)])
    assert r.status_code == 400 and "Orden de Compra Exenta" in r.json()["detail"]
    r = doc(client, auth, cid, [line(p, 2)], oce_number="OCE-2026-0042")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["exonerado"] == 490 and d["gravado_15"] == 0 and d["tax"] == 0 and d["total"] == 490
    assert (d["oce_number"], d["exo_registry"], d["sag_registry"]) == ("OCE-2026-0042", "RE-2026-00155", "SAG-778")
    assert d["items"][0]["tax_treatment"] == "exonerado"
    libro = client.get("/api/reports/libro-ventas.csv?period=all", headers=auth).content.decode("utf-8-sig")
    assert "Orden de compra exenta" in libro.splitlines()[0]
    assert "OCE-2026-0042" in next(l for l in libro.splitlines() if d["number"] in l)


def test_cotizacion_exonerada_pide_la_orden_al_facturar(client, auth):
    cid = exonerated_client(client, auth)
    p = product(client, auth, "CEM-050")
    q = doc(client, auth, cid, [line(p, 1)], kind="cotizacion").json()  # la cotización no la exige
    assert q["exonerado"] == 245 and q["tax"] == 0
    r = client.post(f"/api/documents/{q['id']}/invoice", headers=auth)
    assert r.status_code == 400 and "Orden de Compra Exenta" in r.json()["detail"]
    r = client.post(f"/api/documents/{q['id']}/invoice?oce_number=OCE-77", headers=auth)
    assert r.status_code == 200 and r.json()["oce_number"] == "OCE-77"


def test_nota_de_credito_conserva_la_exoneracion(client, auth):
    cid = exonerated_client(client, auth)
    p = product(client, auth, "CEM-050")
    f = doc(client, auth, cid, [line(p, 2)], oce_number="OCE-1").json()
    n = doc(client, auth, cid, [line(p, 1)], kind="nota", ref_document_id=f["id"])
    assert n.status_code == 200, n.text
    assert n.json()["oce_number"] == "OCE-1" and n.json()["tax"] == 0


def test_punto_de_venta_con_cliente_exonerado(client, auth):
    cid = exonerated_client(client, auth)
    p = product(client, auth, "CEM-050")
    i = ids(client, auth)
    body = {"client_id": cid, "warehouse_id": i["wh"]["id"], "items": [line(p, 1)], "payments": [{"method": "Efectivo", "amount": 245}]}
    assert client.post("/api/pos/sale", json=body, headers=auth).status_code == 400
    r = client.post("/api/pos/sale", json={**body, "oce_number": "OCE-9"}, headers=auth)
    assert r.status_code == 200 and r.json()["total"] == 245


def test_retencion_de_isv(client, auth, login):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    f = doc(client, auth, i["con_rtn"]["id"], [line(p, 4)]).json()  # 980 + 147 ISV = 1127
    r = client.post(f"/api/documents/{f['id']}/payments", json={"amount": 18.38, "method": "Retención ISV"}, headers=auth)
    assert r.status_code == 400 and "comprobante" in r.json()["detail"]
    bank = client.get("/api/banks", headers=auth).json()["banks"][0]
    r = client.post(f"/api/documents/{f['id']}/payments", json={"amount": 18.38, "method": "Retención ISV", "note": "CR-001", "bank_id": bank["id"]}, headers=auth)
    assert r.status_code == 400
    r = client.post(f"/api/documents/{f['id']}/payments", json={"amount": 18.38, "method": "Retención ISV", "note": "CR-001"}, headers=auth)
    assert r.status_code == 200 and r.json()["balance"] == round(1127 - 18.38, 2)
    r = client.post(f"/api/documents/{f['id']}/payments", json={"amount": round(1127 - 18.38, 2), "method": "Transferencia"}, headers=auth)
    assert r.json()["status"] == "Pagada"
    assert client.post(f"/api/documents/{f['id']}/payments", json={"amount": 1, "method": "Bitcoin"}, headers=auth).status_code == 400
    corte = client.get("/api/cash/close", headers=auth).json()
    assert corte["withheld"] == 18.38
    assert all(u["total"] != 1127 for u in corte["by_user"])  # la retención no cuenta como dinero cobrado
    csv = client.get("/api/reports/retenciones.csv?period=all", headers=auth).content.decode("utf-8-sig")
    assert "CR-001" in csv and "18.38" in csv and f["number"] in csv
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/reports/retenciones.csv", headers=caja).status_code == 403
