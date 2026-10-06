"""Pruebas de la v2.9: devoluciones a proveedores y conteo físico de inventario."""
from test_api import ids, invoice, line, make_user, product, stock


def purchase(client, auth, terms="30 días", qty=10, **extra):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    sup = client.get("/api/suppliers", headers=auth).json()[0]
    body = {"supplier_id": sup["id"], "warehouse_id": i["wh"]["id"], "payment_terms": terms,
            "items": [{"product_id": p["id"], "presentation_id": p["presentations"][0]["id"], "qty": qty, "unit_cost": 100}], **extra}
    r = client.post("/api/purchases", json=body, headers=auth)
    assert r.status_code == 200, r.text
    return client.get(f"/api/purchases/{r.json()['id']}", headers=auth).json()


# ───────────────────────── devoluciones a proveedor ─────────────────────────
def test_devolucion_baja_saldo_y_existencias(client, auth):
    i = ids(client, auth)
    p = purchase(client, auth)  # 10 sacos × 100 + ISV = 1 150
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    item = p["items"][0]
    r = client.post(f"/api/purchases/{p['id']}/returns", json={"items": [{"purchase_item_id": item["id"], "qty": 3}], "credit_note": "NC-0007", "notes": "Sacos rotos"}, headers=auth)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["returned"] == 345 and d["balance"] == 805 and d["returns"][0]["credit_note"] == "NC-0007"
    assert d["returnable"][str(item["id"])] == 7
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) == before - 3
    r = client.post(f"/api/purchases/{p['id']}/returns", json={"items": [{"purchase_item_id": item["id"], "qty": 8}]}, headers=auth)
    assert r.status_code == 400 and "solo se pueden devolver 7" in r.json()["detail"]
    libro = client.get("/api/reports/libro-compras.csv?period=all", headers=auth).content.decode("utf-8-sig")
    assert "devolución de " + p["number"] in libro and "-345.00" in libro
    assert client.post(f"/api/purchases/{p['id']}/void", headers=auth).status_code == 400  # con devoluciones no se anula
    moves = client.get(f"/api/stock/moves?product_id={item['product_id']}", headers=auth).json()
    assert any("Devolución a proveedor" in m["concept"] and m["qty"] == -3 for m in moves)


def test_devolucion_de_contado_con_reembolso(client, auth):
    p = purchase(client, auth, terms="Contado")
    bank = client.get("/api/banks", headers=auth).json()["banks"][0]
    r = client.post(f"/api/purchases/{p['id']}/returns", json={"items": [{"purchase_item_id": p["items"][0]["id"], "qty": 2}], "refund_bank_id": bank["id"]}, headers=auth)
    assert r.status_code == 200, r.text
    after = next(b for b in client.get("/api/banks", headers=auth).json()["banks"] if b["id"] == bank["id"])
    assert round(after["balance"] - bank["balance"], 2) == 230


def test_devolucion_no_supera_lo_que_se_debe(client, auth):
    p = purchase(client, auth)
    client.post(f"/api/purchases/{p['id']}/payments", json={"amount": 1000}, headers=auth)  # queda debiendo 150
    r = client.post(f"/api/purchases/{p['id']}/returns", json={"items": [{"purchase_item_id": p["items"][0]["id"], "qty": 5}]}, headers=auth)
    assert r.status_code == 400 and "supera el saldo" in r.json()["detail"]
    pend = purchase(client, auth, status="Pendiente")
    r = client.post(f"/api/purchases/{pend['id']}/returns", json={"items": [{"purchase_item_id": pend["items"][0]["id"], "qty": 1}]}, headers=auth)
    assert r.status_code == 400 and "recibidas" in r.json()["detail"]


# ───────────────────────── conteo físico ─────────────────────────
def test_conteo_fisico_ajusta_y_valoriza(client, auth):
    i = ids(client, auth)
    wh = i["wh"]["id"]
    r = client.post("/api/counts", json={"warehouse_id": wh}, headers=auth)
    assert r.status_code == 200, r.text
    c = r.json()
    assert c["status"] == "Abierto" and c["products"] > 5 and c["number"].startswith("CF-")
    assert client.post("/api/counts", json={"warehouse_id": wh}, headers=auth).status_code == 400  # uno abierto por bodega
    cem = next(l for l in c["lines"] if l["sku"] == "CEM-050")
    tal = next(l for l in c["lines"] if l["sku"] == "TAL-012")
    r = client.put(f"/api/counts/{c['id']}/lines", json={"lines": [{"line_id": cem["id"], "counted": cem["expected"] - 2}, {"line_id": tal["id"], "counted": tal["expected"] + 1}]}, headers=auth)
    data = r.json()
    assert data["counted"] == 2 and next(l for l in data["lines"] if l["sku"] == "CEM-050")["diff"] == -2
    r = client.post(f"/api/counts/{c['id']}/apply", headers=auth)
    assert r.status_code == 200, r.text
    done = r.json()
    assert done["status"] == "Aplicado" and done["shortage"] == 370 and done["surplus"] == 890  # 2 × 185 y 1 × 890
    assert stock(client, auth, "CEM-050", wh) == cem["expected"] - 2 and stock(client, auth, "TAL-012", wh) == tal["expected"] + 1
    assert client.post(f"/api/counts/{c['id']}/apply", headers=auth).status_code == 400
    assert "Aplicó conteo físico" == client.get("/api/audit", headers=auth).json()["rows"][0]["action"]
    csv = client.get(f"/api/counts/{c['id']}/csv", headers=auth).content.decode("utf-8-sig")
    assert "Valor diferencia" in csv.splitlines()[0] and "-370.00" in csv


def test_conteo_usa_la_existencia_al_aplicar(client, auth):
    """Si se vende durante el conteo, el ajuste se calcula contra la existencia del momento de aplicar."""
    i = ids(client, auth)
    wh = i["wh"]["id"]
    c = client.post("/api/counts", json={"warehouse_id": wh}, headers=auth).json()
    cem = next(l for l in c["lines"] if l["sku"] == "CEM-050")
    invoice(client, auth, [line(product(client, auth, "CEM-050"), 5)])  # se venden 5 mientras se cuenta
    client.put(f"/api/counts/{c['id']}/lines", json={"lines": [{"line_id": cem["id"], "counted": cem["expected"] - 5}]}, headers=auth)
    done = client.post(f"/api/counts/{c['id']}/apply", headers=auth).json()
    assert next(l for l in done["lines"] if l["sku"] == "CEM-050")["diff"] == 0


def test_conteo_por_categoria_cancelar_y_permisos(client, auth, login):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    c = client.post("/api/counts", json={"warehouse_id": i["wh2"]["id"], "category_id": p["category_id"]}, headers=auth).json()
    assert all(l["sku"] in {"CEM-050", "VAR-038", "CLV-200"} for l in c["lines"])
    assert client.post(f"/api/counts/{c['id']}/apply", headers=auth).status_code == 400  # nada contado
    assert client.post(f"/api/counts/{c['id']}/cancel", headers=auth).json()["status"] == "Cancelado"
    bod = make_user(client, auth, login, "Bodeguero")
    c2 = client.post("/api/counts", json={"warehouse_id": i["wh2"]["id"]}, headers=bod).json()
    assert c2["shortage"] is None and c2["lines"][0]["cost"] is None  # el bodeguero no ve costos
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/counts", headers=caja).status_code == 403
