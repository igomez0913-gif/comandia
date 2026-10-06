"""Pruebas de la v2.7: cuatro precios por producto y presentación, y precio por cliente."""
from test_api import ids, invoice, line, make_user, product


def client_named(client, auth, name):
    return next(c for c in client.get("/api/clients", headers=auth).json() if c["name"] == name)


def product_body(p, **changes):
    body = {k: p[k] for k in ("sku", "name", "department_id", "category_id", "base_unit", "cost", "price", "price_2", "price_3", "price_4", "min_stock", "tax_treatment")}
    body["presentations"] = [{k: x[k] for k in ("id", "name", "unit", "factor", "barcode", "price", "price_2", "price_3", "price_4")} for x in p["presentations"]]
    body.update(changes)
    return body


def test_producto_trae_cuatro_precios(client, auth):
    p = product(client, auth, "CEM-050")
    saco = p["presentations"][0]
    assert (saco["price"], saco["price_2"], saco["price_3"], saco["price_4"]) == (245, 232.75, 220.5, 0)
    assert saco["prices"] == [245, 232.75, 220.5, 245]  # el precio 4 sin definir usa el precio 1
    assert p["prices"][0] == p["price"]


def test_factura_usa_el_precio_del_cliente(client, auth):
    p = product(client, auth, "CEM-050")
    mayorista = client_named(client, auth, "Contratista Los Pinos")
    assert mayorista["price_level"] == 2
    i = ids(client, auth)
    body = {"kind": "factura", "client_id": mayorista["id"], "warehouse_id": i["wh"]["id"], "items": [line(p, 2)]}
    d = client.post("/api/documents", json=body, headers=auth).json()
    assert d["items"][0]["price"] == 232.75 and d["price_level"] == 2
    # se puede pedir otro nivel para un documento puntual
    d = client.post("/api/documents", json={**body, "price_level": 3}, headers=auth).json()
    assert d["items"][0]["price"] == 220.5 and d["price_level"] == 3
    # un nivel sin precio definido cae al precio 1
    d = client.post("/api/documents", json={**body, "price_level": 4}, headers=auth).json()
    assert d["items"][0]["price"] == 245


def test_nivel_de_precio_invalido(client, auth):
    p = product(client, auth, "CEM-050")
    assert invoice(client, auth, [line(p)], price_level=5).status_code == 422


def test_cajero_elige_entre_los_cuatro_precios_pero_no_uno_libre(client, auth, login):
    caja = make_user(client, auth, login, "Cajero")
    p = product(client, auth, "CEM-050")
    assert invoice(client, caja, [line(p, 1, price=220.5)]).status_code == 200  # precio 3
    r = invoice(client, caja, [line(p, 1, price=200)])
    assert r.status_code == 403 and "L 220.50" in r.json()["detail"] and "L 245.00" in r.json()["detail"]
    # el supervisor sí escribe un precio libre
    sup = make_user(client, auth, login, "Supervisor")
    assert invoice(client, sup, [line(p, 1, price=200)]).status_code == 200


def test_editar_cuatro_precios_queda_en_bitacora(client, auth):
    p = product(client, auth, "CEM-050")
    body = product_body(p, price_4=210)
    body["presentations"][1]["price_2"] = 9000
    assert client.put(f"/api/products/{p['id']}", json=body, headers=auth).status_code == 200
    p = product(client, auth, "CEM-050")
    assert p["price_4"] == 210 and p["presentations"][1]["price_2"] == 9000
    detail = next(r for r in client.get("/api/audit", headers=auth).json()["rows"] if r["action"] == "Editó producto")["detail"]
    assert "precio 4 L 0.00 → L 210.00" in detail and "Tarima 40 sacos precio 2 L 8,930.00 → L 9,000.00" in detail


def test_producto_nuevo_sin_presentaciones_copia_los_cuatro_precios(client, auth):
    p = product(client, auth, "CEM-050")
    body = {"sku": "NEW-001", "name": "Producto nuevo", "department_id": p["department_id"], "category_id": p["category_id"],
            "price": 100, "price_2": 90, "price_3": 80, "price_4": 70}
    assert client.post("/api/products", json=body, headers=auth).status_code == 200
    assert product(client, auth, "NEW-001")["presentations"][0]["prices"] == [100, 90, 80, 70]


def test_precio_del_cliente_se_guarda_y_audita(client, auth):
    c = client_named(client, auth, "Taller Mecánico Central")
    body = {k: c[k] for k in ("name", "rtn", "email", "phone", "address")}
    assert client.put(f"/api/clients/{c['id']}", json={**body, "price_level": 4}, headers=auth).status_code == 200
    assert client_named(client, auth, "Taller Mecánico Central")["price_level"] == 4
    assert any(r["action"] == "Cambió precio del cliente" for r in client.get("/api/audit", headers=auth).json()["rows"])
    assert client.put(f"/api/clients/{c['id']}", json={**body, "price_level": 0}, headers=auth).status_code == 422


def test_nombres_de_los_precios(client, auth):
    s = client.get("/api/settings", headers=auth).json()
    assert s["price_names"] == ["Público", "Mayorista", "Distribuidor", "Especial"]
    base = {k: s[k] for k in ("name", "legal_name", "rtn", "address", "phone", "email", "currency")}
    assert client.put("/api/settings", json={**base, "price_names": ["Detalle", "Mayoreo", "Contratista", "VIP"]}, headers=auth).status_code == 200
    assert client.get("/api/settings", headers=auth).json()["price_names"] == ["Detalle", "Mayoreo", "Contratista", "VIP"]
    assert client.put("/api/settings", json={**base, "price_names": ["A", "", "C", "D"]}, headers=auth).status_code == 400
    assert client.put("/api/settings", json={**base, "price_names": ["A", "a", "C", "D"]}, headers=auth).status_code == 400
    # sin price_names no se tocan
    assert client.put("/api/settings", json=base, headers=auth).status_code == 200
    assert client.get("/api/settings", headers=auth).json()["price_names"][3] == "VIP"
    inv = client.get("/api/reports/inventario.csv", headers=auth).content.decode("utf-8-sig").splitlines()[0]
    assert "Precio Detalle" in inv and "Precio VIP" in inv


def test_cotizacion_mayorista_se_factura_al_mismo_precio(client, auth):
    p = product(client, auth, "CEM-050")
    mayorista = client_named(client, auth, "Contratista Los Pinos")
    i = ids(client, auth)
    q = client.post("/api/documents", json={"kind": "cotizacion", "client_id": mayorista["id"], "warehouse_id": i["wh"]["id"], "items": [line(p, 1)]}, headers=auth).json()
    f = client.post(f"/api/documents/{q['id']}/invoice", headers=auth).json()
    assert f["items"][0]["price"] == 232.75 and f["price_level"] == 2
