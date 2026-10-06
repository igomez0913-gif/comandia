"""Pruebas de la v2.9: rentabilidad por producto, categoría y vendedor."""
from test_api import invoice, line, make_user, product


def report(client, auth):
    r = client.get("/api/reports/profit?period=all", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def row(data, group, start):
    return next(g for g in data[group] if g["name"].startswith(start))


def test_margen_con_el_costo_del_momento_de_la_venta(client, auth):
    base = product(client, auth, "CEM-050")
    body = {"sku": "RENT-1", "name": "Producto de prueba", "department_id": base["department_id"], "category_id": base["category_id"],
            "base_unit": "und", "cost": 60, "price": 100}
    assert client.post("/api/products", json=body, headers=auth).status_code == 200
    p = product(client, auth, "RENT-1")
    wh = client.get("/api/warehouses", headers=auth).json()[0]
    client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": wh["id"], "qty": 50, "concept": "Inventario inicial"}, headers=auth)
    invoice(client, auth, [line(p, 4)])
    cem = row(report(client, auth), "by_product", "RENT-1")
    assert (cem["sales"], cem["cost"], cem["margin"], cem["margin_pct"], cem["qty"], cem["unit"]) == (400, 240, 160, 40.0, 4, "und")
    # sube el costo: la venta ya hecha conserva su margen
    upd = {**body, "cost": 90, "presentations": [{k: x[k] for k in ("id", "name", "unit", "factor", "barcode", "price", "price_2", "price_3", "price_4")} for x in p["presentations"]]}
    assert client.put(f"/api/products/{p['id']}", json=upd, headers=auth).status_code == 200
    assert row(report(client, auth), "by_product", "RENT-1")["cost"] == 240
    invoice(client, auth, [line(p, 1)])  # la venta nueva usa el costo nuevo
    assert row(report(client, auth), "by_product", "RENT-1")["cost"] == 330


def test_presentaciones_y_notas_de_credito(client, auth):
    p = product(client, auth, "CEM-050")
    before = report(client, auth)
    f = invoice(client, auth, [line(p, 1, presentation=1)]).json()  # 1 tarima = 40 sacos
    client.post("/api/documents", json={"kind": "nota", "client_id": f["client_id"], "warehouse_id": f["warehouse_id"], "ref_document_id": f["id"],
                                        "items": [{"product_id": p["id"], "presentation_id": p["presentations"][0]["id"], "qty": 10}]}, headers=auth)
    after = report(client, auth)
    assert round(after["sales"] - before["sales"], 2) == round(9400 - 2450, 2)
    assert round(after["cost"] - before["cost"], 2) == round(40 * 185 - 10 * 185, 2)
    assert round(row(after, "by_product", "CEM-050")["qty"] - next((g["qty"] for g in before["by_product"] if g["name"].startswith("CEM-050")), 0), 2) == 30


def test_por_vendedor_y_categoria(client, auth, login):
    caja = make_user(client, auth, login, "Cajero", "Carla Caja")
    p = product(client, auth, "CEM-050")
    invoice(client, caja, [line(p, 2)])
    data = report(client, auth)
    carla = row(data, "by_seller", "Carla Caja")
    assert carla["sales"] == 490 and carla["margin"] == 120 and carla["documents"] == 1 and carla["margin_pct"] == 24.5
    assert any(g["name"] == "Construcción / Cemento y acero" for g in data["by_category"])
    assert data["top_qty"] and data["margin"] == round(data["sales"] - data["cost"], 2)


def test_ventas_anteriores_usan_costo_actual_y_se_avisa(client, auth):
    from app.main import DocumentItem, SessionLocal
    db = SessionLocal()
    try:
        db.query(DocumentItem).update({DocumentItem.cost: None})  # como las ventas de antes de la v2.9
        db.commit()
    finally:
        db.close()
    data = report(client, auth)
    assert data["estimated_lines"] > 0


def test_permisos_y_csv(client, auth, login):
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/reports/profit", headers=caja).status_code == 403
    csv = client.get("/api/reports/rentabilidad.csv?period=all", headers=auth)
    assert csv.status_code == 200 and "Margen %" in csv.content.decode("utf-8-sig").splitlines()[0]
