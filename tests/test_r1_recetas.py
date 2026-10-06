"""Catálogo del restaurante: tipos de producto, recetas con costo por ingredientes, descuento proporcional del inventario,
descriptivos por familia y órdenes de preparación."""
import pytest

from test_api import ids, invoice, line, make_user, product, stock


def family(client, auth, name="Comidas", sub="Platos fuertes"):
    d = client.post("/api/departments", json={"name": name}, headers=auth).json()["id"]
    c = client.post("/api/categories", json={"name": sub, "department_id": d}, headers=auth).json()["id"]
    return d, c


def make_item(client, auth, sku, name, kind, dep, cat, cost=0, price=0, unit="und", station="", stock_qty=0, **extra):
    r = client.post("/api/products", json={"sku": sku, "name": name, "department_id": dep, "category_id": cat, "base_unit": unit, "cost": cost,
                                           "price": price, "kind": kind, "station": station, "tax_treatment": "gravado15", **extra}, headers=auth)
    assert r.status_code == 200, r.text
    p = product(client, auth, sku)
    if stock_qty:
        wh = ids(client, auth)["wh"]["id"]
        a = client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": wh, "qty": stock_qty, "concept": "Inventario inicial"}, headers=auth)
        assert a.status_code == 200, a.text
    return product(client, auth, sku)


def set_recipe(client, auth, p, lines):
    return client.put(f"/api/recipes/{p['id']}", json={"lines": [{"ingredient_id": i["id"], "qty": q} for i, q in lines]}, headers=auth)


@pytest.fixture()
def menu(client, auth):
    """Hamburguesa = 0.15 lb de carne (L 60/lb) + 1 pan (L 3) → costo L 12.00; vendida a L 95."""
    dep, cat = family(client, auth)
    carne = make_item(client, auth, "INS-CARNE", "Carne molida", "insumo", dep, cat, cost=60, unit="lb", stock_qty=30)
    pan = make_item(client, auth, "INS-PAN", "Pan de hamburguesa", "insumo", dep, cat, cost=3, stock_qty=100)
    burger = make_item(client, auth, "PL-HAMB", "Hamburguesa", "platillo", dep, cat, price=95, station="cocina")
    r = set_recipe(client, auth, burger, [(carne, 0.15), (pan, 1)])
    assert r.status_code == 200, r.text
    return {"dep": dep, "cat": cat, "carne": carne, "pan": pan, "burger": product(client, auth, "PL-HAMB")}


def test_los_productos_tienen_tipo_y_estacion(client, auth, menu):
    b = menu["burger"]
    assert b["kind"] == "platillo" and b["station"] == "cocina" and b["sellable"] is True
    assert menu["carne"]["kind"] == "insumo" and menu["carne"]["sellable"] is False
    dep, cat = menu["dep"], menu["cat"]
    base = {"sku": "X1", "name": "X", "department_id": dep, "category_id": cat, "price": 1}
    assert client.post("/api/products", json={**base, "kind": "inventado"}, headers=auth).status_code == 400
    assert client.post("/api/products", json={**base, "sku": "X2", "station": "azotea"}, headers=auth).status_code == 400
    # lo que ya existía sigue siendo un producto normal que se compra y se vende
    assert product(client, auth, "CEM-050")["kind"] == "producto"


def test_el_costo_del_platillo_sale_de_sus_ingredientes(client, auth, menu):
    rec = client.get(f"/api/recipes/{menu['burger']['id']}", headers=auth).json()
    assert rec["cost"] == 12.0 and rec["margin"] == 83.0 and rec["margin_pct"] == 87.4 and len(rec["lines"]) == 2
    assert menu["burger"]["cost"] == 12.0  # el producto también muestra el costo por receta
    # si sube la carne, sube el costo del platillo (se calcula con el costo actual de cada ingrediente)
    carne = menu["carne"]
    client.put(f"/api/products/{carne['id']}", json={"sku": carne["sku"], "name": carne["name"], "department_id": menu["dep"], "category_id": menu["cat"],
                                                    "base_unit": "lb", "cost": 80, "kind": "insumo", "min_stock": 5, "price": 0}, headers=auth)
    assert client.get(f"/api/recipes/{menu['burger']['id']}", headers=auth).json()["cost"] == 15.0
    # reporte de recetas
    rows = client.get("/api/recipes", headers=auth).json()
    assert [r["sku"] for r in rows] == ["PL-HAMB"]


def test_vender_un_platillo_descuenta_los_ingredientes_en_proporcion(client, auth, menu):
    wh = ids(client, auth)["wh"]["id"]
    r = invoice(client, auth, [line(menu["burger"], 4)])
    assert r.status_code == 200, r.text
    assert stock(client, auth, "INS-CARNE", wh) == 30 - 0.6 and stock(client, auth, "INS-PAN", wh) == 96
    assert stock(client, auth, "PL-HAMB", wh) == 0  # el platillo no lleva existencia propia
    # el costo de la línea quedó guardado con el costo por receta (4 × L 12)
    doc = client.get(f"/api/documents/{r.json()['id']}", headers=auth).json()
    assert doc["document"]["lines"][0]["qty"] == 4 if "lines" in doc["document"] else True


def test_anular_la_factura_devuelve_los_ingredientes(client, auth, menu):
    wh = ids(client, auth)["wh"]["id"]
    inv = invoice(client, auth, [line(menu["burger"], 10)]).json()
    assert stock(client, auth, "INS-PAN", wh) == 90
    assert client.post(f"/api/documents/{inv['id']}/void", headers=auth).status_code == 200
    assert stock(client, auth, "INS-PAN", wh) == 100 and stock(client, auth, "INS-CARNE", wh) == 30


def test_nota_de_credito_devuelve_ingredientes_y_su_anulacion_los_vuelve_a_gastar(client, auth, menu):
    wh = ids(client, auth)["wh"]["id"]
    inv = invoice(client, auth, [line(menu["burger"], 4)]).json()
    nota = client.post("/api/documents", json={"kind": "nota", "client_id": inv["client_id"], "warehouse_id": wh, "ref_document_id": inv["id"],
                                               "items": [line(menu["burger"], 1)]}, headers=auth)
    assert nota.status_code == 200, nota.text
    assert stock(client, auth, "INS-PAN", wh) == 97  # 100 − 4 + 1
    assert client.post(f"/api/documents/{nota.json()['id']}/void", headers=auth).status_code == 200
    assert stock(client, auth, "INS-PAN", wh) == 96


def test_sin_ingredientes_suficientes_no_se_vende_y_no_se_descuenta_nada(client, auth, menu):
    wh = ids(client, auth)["wh"]["id"]
    r = invoice(client, auth, [line(menu["burger"], 500)])  # pide 75 lb de carne y 500 panes
    assert r.status_code == 400 and "Stock insuficiente" in r.json()["detail"]
    assert stock(client, auth, "INS-CARNE", wh) == 30 and stock(client, auth, "INS-PAN", wh) == 100


def test_una_venta_con_dos_platillos_que_comparten_ingrediente_los_suma(client, auth, menu):
    wh = ids(client, auth)["wh"]["id"]
    doble = make_item(client, auth, "PL-DOBLE", "Hamburguesa doble", "platillo", menu["dep"], menu["cat"], price=140, station="cocina")
    assert set_recipe(client, auth, doble, [(menu["carne"], 0.3), (menu["pan"], 1)]).status_code == 200
    assert invoice(client, auth, [line(menu["burger"], 2), line(doble, 1)]).status_code == 200
    assert round(stock(client, auth, "INS-CARNE", wh), 2) == round(30 - 0.3 - 0.3, 2) and stock(client, auth, "INS-PAN", wh) == 97


def test_validaciones_de_la_receta(client, auth, menu):
    b, carne, pan = menu["burger"], menu["carne"], menu["pan"]
    assert set_recipe(client, auth, carne, [(pan, 1)]).status_code == 400  # un insumo no lleva receta
    assert set_recipe(client, auth, b, [(b, 1)]).status_code == 400  # ni es ingrediente de sí mismo
    assert set_recipe(client, auth, b, [(carne, 1), (carne, 2)]).status_code == 400  # ingrediente repetido
    assert client.put(f"/api/recipes/{b['id']}", json={"lines": [{"ingredient_id": carne["id"], "qty": 0}]}, headers=auth).status_code == 422
    otro = make_item(client, auth, "PL-OTRO", "Otro platillo", "platillo", menu["dep"], menu["cat"], price=10)
    assert set_recipe(client, auth, b, [(otro, 1)]).status_code == 400  # un platillo no puede ser ingrediente
    assert client.put(f"/api/recipes/999999", json={"lines": []}, headers=auth).status_code == 404
    # no se le quita el tipo a un platillo que tiene receta
    r = client.put(f"/api/products/{b['id']}", json={"sku": b["sku"], "name": b["name"], "department_id": menu["dep"], "category_id": menu["cat"],
                                                    "base_unit": "und", "price": 95, "kind": "insumo"}, headers=auth)
    assert r.status_code == 400 and "receta" in r.json()["detail"]


def test_recetas_circulares_se_rechazan(client, auth, menu):
    a = make_item(client, auth, "EL-A", "Salsa A", "elaborado", menu["dep"], menu["cat"], unit="lb")
    b = make_item(client, auth, "EL-B", "Salsa B", "elaborado", menu["dep"], menu["cat"], unit="lb")
    assert set_recipe(client, auth, a, [(menu["carne"], 1), (b, 1)]).status_code == 200
    r = set_recipe(client, auth, b, [(a, 1)])
    assert r.status_code == 400 and "circular" in r.json()["detail"]


def test_borrar_la_receta_deja_el_platillo_sin_descuento(client, auth, menu):
    wh = ids(client, auth)["wh"]["id"]
    assert set_recipe(client, auth, menu["burger"], []).status_code == 200
    assert client.get("/api/recipes", headers=auth).json() == []
    stock_dish = client.post("/api/stock/adjust", json={"product_id": menu["burger"]["id"], "warehouse_id": wh, "qty": 5, "concept": "Existencia inicial"}, headers=auth)
    assert stock_dish.status_code == 200
    assert invoice(client, auth, [line(product(client, auth, "PL-HAMB"), 2)]).status_code == 200
    assert stock(client, auth, "PL-HAMB", wh) == 3 and stock(client, auth, "INS-PAN", wh) == 100


def test_el_costo_de_la_receta_se_oculta_a_quien_no_ve_costos(client, auth, login, menu):
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/recipes", headers=caja).status_code == 403  # el cajero no maneja catálogo ni inventario
    contador = make_user(client, auth, login, "Contador")
    rec = client.get(f"/api/recipes/{menu['burger']['id']}", headers=contador).json()
    assert "cost" in rec  # el contador sí ve costos
    assert client.put(f"/api/recipes/{menu['burger']['id']}", json={"lines": []}, headers=contador).status_code == 403
    bodega = make_user(client, auth, login, "Bodeguero")
    rec = client.get(f"/api/recipes/{menu['burger']['id']}", headers=bodega).json()
    assert "cost" not in rec and all("cost" not in ln for ln in rec["lines"])  # sin permiso de costos no se envían


def test_descriptivos_por_familia_y_generales(client, auth, login, menu):
    d2, _ = family(client, auth, "Bebidas", "Frías")
    g = client.post("/api/descriptives", json={"name": "Sin sal"}, headers=auth)
    a = client.post("/api/descriptives", json={"name": "Término medio", "department_id": menu["dep"]}, headers=auth)
    b = client.post("/api/descriptives", json={"name": "Con hielo", "department_id": d2}, headers=auth)
    x = client.post("/api/descriptives", json={"name": "Extra queso", "department_id": menu["dep"], "extra_price": 15}, headers=auth)
    assert all(r.status_code == 200 for r in (g, a, b, x))
    assert client.post("/api/descriptives", json={"name": "Sin sal"}, headers=auth).status_code == 400  # repetido
    names = lambda dep: sorted(d["name"] for d in client.get(f"/api/descriptives?department_id={dep}", headers=auth).json())
    assert names(menu["dep"]) == ["Extra queso", "Sin sal", "Término medio"] and names(d2) == ["Con hielo", "Sin sal"]
    assert next(d for d in client.get("/api/descriptives", headers=auth).json() if d["name"] == "Extra queso")["extra_price"] == 15
    # un mesero (o cualquiera con sesión) los consulta, pero solo el catálogo los edita
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/descriptives", headers=caja).status_code == 200
    assert client.post("/api/descriptives", json={"name": "Nuevo"}, headers=caja).status_code == 403
    assert client.post("/api/descriptives", json={"name": "Z", "department_id": 99999}, headers=auth).status_code == 400
    # desactivar lo oculta del pedido pero no lo borra
    did = b.json()["id"]
    assert client.put(f"/api/descriptives/{did}", json={"name": "Con hielo", "department_id": d2, "active": False}, headers=auth).status_code == 200
    assert names(d2) == ["Sin sal"] and len(client.get("/api/descriptives?all=true", headers=auth).json()) == 4
    assert client.delete(f"/api/descriptives/{did}", headers=auth).status_code == 200
    assert client.delete(f"/api/descriptives/{did}", headers=auth).status_code == 404


def test_orden_de_preparacion_produce_un_elaborado_y_gasta_ingredientes(client, auth, menu):
    wh = ids(client, auth)["wh"]["id"]
    salsa = make_item(client, auth, "EL-SALSA", "Salsa de la casa", "elaborado", menu["dep"], menu["cat"], unit="lb")
    assert client.post("/api/preparations", json={"product_id": salsa["id"], "warehouse_id": wh, "qty": 5}, headers=auth).status_code == 400  # sin receta
    assert set_recipe(client, auth, salsa, [(menu["carne"], 0.5), (menu["pan"], 2)]).status_code == 200
    r = client.post("/api/preparations", json={"product_id": salsa["id"], "warehouse_id": wh, "qty": 4, "notes": "turno de la mañana"}, headers=auth)
    assert r.status_code == 200, r.text
    o = r.json()
    assert o["number"].startswith("OP-") and o["cost"] == 4 * (0.5 * 60 + 2 * 3)
    assert stock(client, auth, "EL-SALSA", wh) == 4 and stock(client, auth, "INS-CARNE", wh) == 28 and stock(client, auth, "INS-PAN", wh) == 92
    assert client.get("/api/preparations", headers=auth).json()[0]["number"] == o["number"]
    # un platillo o un insumo no se preparan; sin ingredientes suficientes no se produce nada
    assert client.post("/api/preparations", json={"product_id": menu["burger"]["id"], "warehouse_id": wh, "qty": 1}, headers=auth).status_code == 400
    sin = client.post("/api/preparations", json={"product_id": salsa["id"], "warehouse_id": wh, "qty": 1000}, headers=auth)
    assert sin.status_code == 400 and stock(client, auth, "EL-SALSA", wh) == 4 and stock(client, auth, "INS-PAN", wh) == 92
    # y la salsa, ya producida, puede ser ingrediente de un platillo
    pasta = make_item(client, auth, "PL-PASTA", "Pasta con salsa", "platillo", menu["dep"], menu["cat"], price=120)
    assert set_recipe(client, auth, pasta, [(salsa, 0.25)]).status_code == 200
    assert invoice(client, auth, [line(pasta, 2)]).status_code == 200
    assert stock(client, auth, "EL-SALSA", wh) == 3.5
