"""Salón: salones y plano de mesas, cuentas, pedidos con descriptivos, envío a cocina, cambio y unión de mesas,
transferencias, división de cuentas, cobro con factura e inventario, anulaciones con PIN y reporte de productos anulados."""
import pytest

from test_api import ids, make_user, product, stock
from test_r1_recetas import family, make_item, set_recipe


def set_prices_include_tax(client, auth, on):
    s = client.get("/api/settings", headers=auth).json()
    body = {k: s[k] for k in ("name", "legal_name", "rtn", "address", "phone", "email", "currency")}
    r = client.put("/api/settings", json={**body, "prices_include_tax": on}, headers=auth)
    assert r.status_code == 200, r.text


@pytest.fixture()
def rest(client, auth):
    """Un salón con 3 mesas, un menú con receta y descriptivos."""
    set_prices_include_tax(client, auth, True)  # el precio del menú es el precio final
    dep, cat = family(client, auth)
    carne = make_item(client, auth, "INS-CARNE", "Carne molida", "insumo", dep, cat, cost=60, unit="lb", stock_qty=50)
    pan = make_item(client, auth, "INS-PAN", "Pan de hamburguesa", "insumo", dep, cat, cost=3, stock_qty=200)
    burger = make_item(client, auth, "PL-HAMB", "Hamburguesa", "platillo", dep, cat, price=100, station="cocina")
    assert set_recipe(client, auth, burger, [(carne, 0.15), (pan, 1)]).status_code == 200
    cola = make_item(client, auth, "BEB-COLA", "Refresco", "producto", dep, cat, cost=10, price=30, station="barra", stock_qty=100)
    queso = client.post("/api/descriptives", json={"name": "Extra queso", "department_id": dep, "extra_price": 15}, headers=auth).json()
    sinceb = client.post("/api/descriptives", json={"name": "Sin cebolla"}, headers=auth).json()
    salon = client.post("/api/salons", json={"name": "Terraza"}, headers=auth).json()
    layout = client.put(f"/api/salons/{salon['id']}/layout", json={"items": [
        {"kind": "mesa", "name": "1", "x": 10, "y": 10, "seats": 4}, {"kind": "mesa", "name": "2", "x": 120, "y": 10, "shape": "redonda", "seats": 2},
        {"kind": "mesa", "name": "3", "x": 230, "y": 10, "seats": 6}, {"kind": "planta", "name": "Palmera", "x": 300, "y": 300, "w": 60, "h": 60},
        {"kind": "pared", "name": "", "x": 0, "y": 0, "w": 600, "h": 10}]}, headers=auth)
    assert layout.status_code == 200, layout.text
    mesas = {i["name"]: i["id"] for i in layout.json()["items"] if i["kind"] == "mesa"}
    return {"dep": dep, "carne": carne, "pan": pan, "burger": product(client, auth, "PL-HAMB"), "cola": cola, "queso": queso, "sinceb": sinceb, "salon": salon, "mesas": mesas}


def open_tab(client, auth, rest, mesa="1", **extra):
    r = client.post("/api/tabs", json={"table_ids": [rest["mesas"][mesa]], "guests": 2, **extra}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def add(client, auth, tab, product, qty=1, **extra):
    r = client.post(f"/api/tabs/{tab['id']}/lines", json={"product_id": product["id"], "qty": qty, **extra}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


def pay_all(tab_total):
    return [{"method": "Efectivo", "amount": tab_total}]


# ───────────────────────── plano ─────────────────────────
def test_plano_con_mesas_mobiliario_y_estado(client, auth, rest):
    salons = client.get("/api/salons", headers=auth).json()
    assert len(salons) == 1 and sorted(i["kind"] for i in salons[0]["items"]) == ["mesa", "mesa", "mesa", "pared", "planta"]
    assert all(i["tab"] is None for i in salons[0]["items"] if i["kind"] == "mesa")  # todas libres
    t = open_tab(client, auth, rest)
    mesa1 = next(i for i in client.get("/api/salons", headers=auth).json()[0]["items"] if i["name"] == "1")
    assert mesa1["tab"]["id"] == t["id"] and mesa1["tab"]["total"] == 0


def test_validaciones_del_plano(client, auth, rest):
    sid = rest["salon"]["id"]
    put = lambda items: client.put(f"/api/salons/{sid}/layout", json={"items": items}, headers=auth)
    assert put([{"kind": "mesa", "name": "A"}, {"kind": "mesa", "name": "a"}]).status_code == 400  # mesa repetida
    assert put([{"kind": "mesa", "name": ""}]).status_code == 400
    assert put([{"kind": "sillon", "name": "x"}]).status_code == 400
    assert put([{"kind": "mesa", "name": "A", "shape": "triangulo"}]).status_code == 400
    assert put([{"kind": "mesa", "name": "A", "w": 5}]).status_code == 422
    assert client.post("/api/salons", json={"name": "terraza"}, headers=auth).status_code == 400  # nombre repetido sin importar mayúsculas


def test_no_se_quita_una_mesa_con_cuenta_abierta_y_las_usadas_solo_se_desactivan(client, auth, rest):
    sid = rest["salon"]["id"]
    t = open_tab(client, auth, rest, "1")
    todas = client.get("/api/salons", headers=auth).json()[0]["items"]
    sin_mesa1 = [{k: i[k] for k in ("id", "kind", "name", "shape", "x", "y", "w", "h", "rotation", "seats")} for i in todas if i["name"] != "1"]
    r = client.put(f"/api/salons/{sid}/layout", json={"items": sin_mesa1}, headers=auth)
    assert r.status_code == 400 and "cuenta abierta" in r.json()["detail"]
    assert client.delete(f"/api/salons/{sid}", headers=auth).status_code == 400  # el salón tiene una cuenta abierta
    client.post(f"/api/tabs/{t['id']}/close-empty", headers=auth)
    assert client.put(f"/api/salons/{sid}/layout", json={"items": sin_mesa1}, headers=auth).status_code == 200  # ya con historial: solo se desactiva
    assert "1" not in [i["name"] for i in client.get("/api/salons", headers=auth).json()[0]["items"]]


def test_solo_quien_diseña_el_salon_lo_cambia(client, auth, login, rest):
    mesero = make_user(client, auth, login, "Mesero")
    assert client.get("/api/salons", headers=mesero).status_code == 200  # lo ve para tomar pedidos
    assert client.post("/api/salons", json={"name": "Otro"}, headers=mesero).status_code == 403
    assert client.put(f"/api/salons/{rest['salon']['id']}/layout", json={"items": []}, headers=mesero).status_code == 403
    cocina = make_user(client, auth, login, "Cocina")
    assert client.post("/api/tabs", json={"table_ids": []}, headers=cocina).status_code == 403  # la cocina no abre cuentas


# ───────────────────────── cuentas y pedidos ─────────────────────────
def test_una_mesa_solo_tiene_una_cuenta_abierta(client, auth, rest):
    open_tab(client, auth, rest, "1")
    r = client.post("/api/tabs", json={"table_ids": [rest["mesas"]["1"]]}, headers=auth)
    assert r.status_code == 400 and "ya tiene la cuenta abierta" in r.json()["detail"]
    assert client.post("/api/tabs", json={"table_ids": [999999]}, headers=auth).status_code == 400
    planta = next(i["id"] for i in client.get("/api/salons", headers=auth).json()[0]["items"] if i["kind"] == "planta")
    assert client.post("/api/tabs", json={"table_ids": [planta]}, headers=auth).status_code == 400  # una planta no es una mesa


def test_pedido_con_descriptivos_recargo_y_comensal(client, auth, rest):
    t = open_tab(client, auth, rest)
    t = add(client, auth, t, rest["burger"], 2, descriptive_ids=[rest["queso"]["id"], rest["sinceb"]["id"]], note="bien cocida", guest=2)
    ln = t["lines"][0]
    assert ln["unit_price"] == 115 and ln["total"] == 230 and ln["descriptives"] == "Extra queso, Sin cebolla" and ln["guest"] == 2 and ln["status"] == "nueva"
    assert t["total"] == 230 and t["guests_totals"] == {"2": 230.0}
    # un insumo no se vende; un comensal inexistente o un descriptivo de otra familia se rechazan
    assert client.post(f"/api/tabs/{t['id']}/lines", json={"product_id": rest["carne"]["id"]}, headers=auth).status_code == 400
    assert client.post(f"/api/tabs/{t['id']}/lines", json={"product_id": rest["burger"]["id"], "guest": 9}, headers=auth).status_code == 400
    otra, _ = family(client, auth, "Bebidas", "Frías")
    hielo = client.post("/api/descriptives", json={"name": "Con hielo", "department_id": otra}, headers=auth).json()
    r = client.post(f"/api/tabs/{t['id']}/lines", json={"product_id": rest["burger"]["id"], "descriptive_ids": [hielo["id"]]}, headers=auth)
    assert r.status_code == 400 and "no aplica" in r.json()["detail"]
    assert client.post(f"/api/tabs/{t['id']}/lines", json={"product_id": rest["burger"]["id"], "qty": 0}, headers=auth).status_code == 422


def test_enviar_a_cocina_agrupa_por_estacion_y_no_repite(client, auth, rest):
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    add(client, auth, t, rest["cola"], 2)
    r = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()
    assert sorted(c["station"] for c in r["comandas"]) == ["barra", "cocina"]
    assert all(ln["status"] == "enviada" for ln in r["tab"]["lines"])
    assert client.post(f"/api/tabs/{t['id']}/send", headers=auth).status_code == 400  # nada nuevo
    assert client.put(f"/api/tabs/{t['id']}/lines/{r['tab']['lines'][0]['id']}", json={"qty": 5}, headers=auth).status_code == 400  # ya enviada


def test_editar_y_quitar_lo_que_aun_no_se_envio(client, auth, rest):
    t = open_tab(client, auth, rest)
    t = add(client, auth, t, rest["burger"], 1)
    lid = t["lines"][0]["id"]
    t = client.put(f"/api/tabs/{t['id']}/lines/{lid}", json={"qty": 3, "note": "sin sal"}, headers=auth).json()
    assert t["lines"][0]["qty"] == 3 and t["total"] == 300
    t = client.post(f"/api/tabs/{t['id']}/lines/{lid}/void", json={}, headers=auth).json()
    assert t["lines"] == [] and t["total"] == 0


# ───────────────────────── anulaciones ─────────────────────────
def test_anular_lo_enviado_pide_motivo_y_pin_si_no_se_tiene_permiso(client, auth, login, rest):
    mesero = make_user(client, auth, login, "Mesero")
    sup = make_user(client, auth, login, "Supervisor")
    assert client.post("/api/me/pin", json={"password": "clave123", "pin": "4455"}, headers=sup).status_code == 200
    t = client.post("/api/tabs", json={"table_ids": [rest["mesas"]["1"]]}, headers=mesero).json()
    add(client, mesero, t, rest["burger"], 1)
    sent = client.post(f"/api/tabs/{t['id']}/send", headers=mesero).json()["tab"]
    lid = sent["lines"][0]["id"]
    url = f"/api/tabs/{t['id']}/lines/{lid}/void"
    assert client.post(url, json={"reason": ""}, headers=mesero).status_code == 400  # sin motivo
    r = client.post(url, json={"reason": "El cliente se fue"}, headers=mesero)
    assert r.status_code == 403 and "AUTORIZACION" in r.json()["detail"]  # el mesero no puede solo
    assert client.post(url, json={"reason": "El cliente se fue", "auth_pin": "0000"}, headers=mesero).status_code == 403  # PIN equivocado
    ok = client.post(url, json={"reason": "El cliente se fue", "auth_pin": "4455"}, headers=mesero)
    assert ok.status_code == 200 and ok.json()["total"] == 0 and ok.json()["lines"][0]["status"] == "anulada"
    rep = client.get("/api/reports/voided-lines", headers=auth).json()
    assert rep["total"] == 100 and rep["rows"][0]["reason"] == "El cliente se fue" and rep["rows"][0]["voided_by"] == sup_name(client, sup)
    assert client.get("/api/reports/voided-lines", headers=mesero).status_code == 403  # el reporte es de gerencia


def sup_name(client, headers):
    return client.get("/api/me", headers=headers).json()["name"]


def test_quien_puede_anular_lo_hace_directo(client, auth, rest):
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["cola"], 1)
    lid = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()["tab"]["lines"][0]["id"]
    r = client.post(f"/api/tabs/{t['id']}/lines/{lid}/void", json={"reason": "Se derramó"}, headers=auth)
    assert r.status_code == 200 and r.json()["lines"][0]["status"] == "anulada"
    assert client.post(f"/api/tabs/{t['id']}/lines/{lid}/void", json={"reason": "otra vez"}, headers=auth).status_code == 400  # ya anulada


# ───────────────────────── cambiar, unir, transferir ─────────────────────────
def test_cambiar_de_mesa_libera_la_anterior(client, auth, rest):
    t = open_tab(client, auth, rest, "1")
    other = open_tab(client, auth, rest, "3")
    assert client.post(f"/api/tabs/{t['id']}/move", json={"table_ids": [rest["mesas"]["3"]]}, headers=auth).status_code == 400  # ocupada
    r = client.post(f"/api/tabs/{t['id']}/move", json={"table_ids": [rest["mesas"]["2"]]}, headers=auth)
    assert r.status_code == 200 and [x["name"] for x in r.json()["tables"]] == ["2"]
    items = {i["name"]: i for i in client.get("/api/salons", headers=auth).json()[0]["items"] if i["kind"] == "mesa"}
    assert items["1"]["tab"] is None and items["2"]["tab"]["id"] == t["id"] and items["3"]["tab"]["id"] == other["id"]
    # pasarse a varias mesas a la vez (ya libre la 1)
    assert client.post(f"/api/tabs/{t['id']}/move", json={"table_ids": [rest["mesas"]["1"], rest["mesas"]["2"]]}, headers=auth).status_code == 200


def test_unir_cuentas_junta_consumos_mesas_y_comensales(client, auth, rest):
    a = open_tab(client, auth, rest, "1")
    b = open_tab(client, auth, rest, "2")
    add(client, auth, a, rest["burger"], 1, guest=1)
    add(client, auth, b, rest["cola"], 2, guest=2)
    r = client.post(f"/api/tabs/{a['id']}/merge", json={"from_tab_id": b["id"]}, headers=auth)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["total"] == 160 and sorted(x["name"] for x in m["tables"]) == ["1", "2"] and m["guests"] == 4
    assert sorted(m["guests_totals"].items()) == [("1", 100.0), ("4", 60.0)]  # el comensal 2 de la otra cuenta pasa a ser el 4
    assert client.get(f"/api/tabs/{b['id']}", headers=auth).json()["status"] == "Unida"
    assert client.post(f"/api/tabs/{a['id']}/merge", json={"from_tab_id": a["id"]}, headers=auth).status_code == 400
    assert client.post(f"/api/tabs/{a['id']}/merge", json={"from_tab_id": b["id"]}, headers=auth).status_code == 400  # la otra ya no está abierta


def test_transferir_consumos_a_otra_cuenta_o_a_una_mesa_libre(client, auth, rest):
    a = open_tab(client, auth, rest, "1")
    a = add(client, auth, a, rest["burger"], 1)
    a = add(client, auth, a, rest["cola"], 1)
    l1, l2 = (ln["id"] for ln in a["lines"])
    r = client.post(f"/api/tabs/{a['id']}/transfer", json={"line_ids": [l1], "to_table_id": rest["mesas"]["2"]}, headers=auth)
    assert r.status_code == 200, r.text
    assert r.json()["from"]["total"] == 30 and r.json()["to"]["total"] == 100 and [x["name"] for x in r.json()["to"]["tables"]] == ["2"]  # se abrió cuenta en la mesa libre
    b = r.json()["to"]
    r = client.post(f"/api/tabs/{a['id']}/transfer", json={"line_ids": [l2], "to_tab_id": b["id"]}, headers=auth)
    assert r.status_code == 200 and r.json()["to"]["total"] == 130 and r.json()["from"]["lines_count"] == 0
    bad = client.post(f"/api/tabs/{a['id']}/transfer", json={"line_ids": [l1], "to_tab_id": b["id"]}, headers=auth)
    assert bad.status_code == 400  # esa línea ya no está en la cuenta de origen
    assert client.post(f"/api/tabs/{b['id']}/transfer", json={"line_ids": [l1]}, headers=auth).status_code == 400  # falta el destino
    assert client.post(f"/api/tabs/{b['id']}/transfer", json={"line_ids": [l1], "to_tab_id": b["id"]}, headers=auth).status_code == 400  # a sí misma


def test_cerrar_cuenta_vacia(client, auth, rest):
    t = open_tab(client, auth, rest)
    assert client.post(f"/api/tabs/{t['id']}/close-empty", headers=auth).json()["status"] == "Cerrada"
    assert open_tab(client, auth, rest)["status"] == "Abierta"  # la mesa quedó libre
    t2 = open_tab(client, auth, rest, "2")
    add(client, auth, t2, rest["cola"], 1)
    assert client.post(f"/api/tabs/{t2['id']}/close-empty", headers=auth).status_code == 400  # tiene consumos


# ───────────────────────── cobro ─────────────────────────
def test_cobrar_emite_la_factura_descuenta_ingredientes_y_libera_la_mesa(client, auth, rest):
    wh = ids(client, auth)["wh"]["id"]
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 2, descriptive_ids=[rest["queso"]["id"]])
    add(client, auth, t, rest["cola"], 2)
    assert client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(290)}, headers=auth).status_code == 400  # sin enviar a cocina
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(290), "received": 300, "tip": 29}, headers=auth)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["closed"] is True and out["tab"]["status"] == "Cerrada" and out["document"]["total"] == 290 and out["document"]["kind"] == "factura"
    assert out["document"]["change"] == 10 and out["tip"] == 29 and out["tab"]["settlements"][0]["tip"] == 29
    assert round(stock(client, auth, "INS-CARNE", wh), 2) == 49.7 and stock(client, auth, "INS-PAN", wh) == 198 and stock(client, auth, "BEB-COLA", wh) == 98
    items = {i["name"]: i for i in client.get("/api/salons", headers=auth).json()[0]["items"] if i["kind"] == "mesa"}
    assert items["1"]["tab"] is None  # la mesa quedó libre
    assert client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(1)}, headers=auth).status_code == 400  # ya cerrada


def test_pago_que_no_cuadra_no_deja_nada_a_medias(client, auth, rest):
    wh = ids(client, auth)["wh"]["id"]
    facturas = len(client.get("/api/documents?kind=factura", headers=auth).json())
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(50)}, headers=auth)
    assert r.status_code == 400 and "Falta" in r.json()["detail"]
    after = client.get(f"/api/tabs/{t['id']}", headers=auth).json()
    assert after["status"] == "Abierta" and after["lines"][0]["status"] == "enviada" and after["settlements"] == []
    assert stock(client, auth, "INS-PAN", wh) == 200  # no se gastó nada
    assert len(client.get("/api/documents?kind=factura", headers=auth).json()) == facturas  # y no se emitió ni se gastó un número fiscal


def test_dividir_la_cuenta_por_comensal(client, auth, rest):
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["burger"], 1, guest=1)
    add(client, auth, t, rest["cola"], 1, guest=1)
    add(client, auth, t, rest["burger"], 1, guest=2)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    first = client.post(f"/api/tabs/{t['id']}/pay", json={"guest": 1, "payments": [{"method": "Tarjeta", "amount": 130}]}, headers=auth).json()
    assert first["closed"] is False and first["document"]["total"] == 130 and first["tab"]["total"] == 100  # queda lo del comensal 2
    second = client.post(f"/api/tabs/{t['id']}/pay", json={"guest": 2, "payments": pay_all(100), "buyer_name": "Ana", "buyer_rtn": "08011990123456"}, headers=auth).json()
    assert second["closed"] is True and len(second["tab"]["settlements"]) == 2
    assert first["document"]["number"] != second["document"]["number"]  # cada comensal con su propia factura
    assert client.post(f"/api/tabs/{t['id']}/pay", json={"guest": 3, "payments": pay_all(1)}, headers=auth).status_code == 400  # ya nada que cobrar


def test_cobrar_lineas_elegidas(client, auth, rest):
    t = open_tab(client, auth, rest)
    t = add(client, auth, t, rest["burger"], 1)
    t = add(client, auth, t, rest["cola"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    l1 = client.get(f"/api/tabs/{t['id']}", headers=auth).json()["lines"][1]["id"]
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"line_ids": [l1], "payments": pay_all(30)}, headers=auth).json()
    assert r["closed"] is False and r["document"]["total"] == 30 and r["tab"]["total"] == 100
    assert client.post(f"/api/tabs/{t['id']}/pay", json={"line_ids": [l1], "payments": pay_all(30)}, headers=auth).status_code == 400  # ya cobrada
    assert client.post(f"/api/tabs/{t['id']}/pay", json={"line_ids": [99999], "payments": pay_all(30)}, headers=auth).status_code == 400


def test_sin_ingredientes_no_se_cobra_ni_se_cierra(client, auth, rest):
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 400)  # 60 lb de carne: hay 50
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(40000)}, headers=auth)
    assert r.status_code == 400 and "Stock insuficiente" in r.json()["detail"]
    assert client.get(f"/api/tabs/{t['id']}", headers=auth).json()["status"] == "Abierta"


def test_el_mesero_toma_pedidos_pero_no_cobra(client, auth, login, rest):
    mesero = make_user(client, auth, login, "Mesero")
    cajero = make_user(client, auth, login, "Cajero")
    t = client.post("/api/tabs", json={"table_ids": [rest["mesas"]["1"]]}, headers=mesero).json()
    add(client, mesero, t, rest["cola"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=mesero)
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(30)}, headers=mesero)
    assert r.status_code == 403 and "Caja" in r.json()["detail"]
    ok = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(30)}, headers=cajero)  # el cajero sí, aunque no sepa de precios libres
    assert ok.status_code == 200 and ok.json()["closed"] is True
    # el mesero no ve costos de las recetas ni puede tocar el catálogo
    assert client.put(f"/api/recipes/{rest['burger']['id']}", json={"lines": []}, headers=mesero).status_code == 403


def test_precio_con_recargo_no_exige_permiso_de_precios_al_cajero(client, auth, login, rest):
    cajero = make_user(client, auth, login, "Cajero")
    t = open_tab(client, cajero, rest)
    add(client, cajero, t, rest["burger"], 1, descriptive_ids=[rest["queso"]["id"]])  # L 115, que no es un precio del catálogo
    client.post(f"/api/tabs/{t['id']}/send", headers=cajero)
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(115)}, headers=cajero)
    assert r.status_code == 200 and r.json()["document"]["total"] == 115
    # pero el cajero sigue sin poder escribir precios libres en una factura normal
    i = ids(client, auth)
    libre = client.post("/api/documents", json={"kind": "factura", "client_id": i["final"]["id"], "warehouse_id": i["wh"]["id"],
                                                "items": [{"product_id": rest["cola"]["id"], "qty": 1, "price": 1}]}, headers=cajero)
    assert libre.status_code == 403


def test_catalogo_de_roles_incluye_mesero_y_cocina(client, auth):
    names = [r["name"] for r in client.get("/api/roles", headers=auth).json()["roles"]]
    assert names[-2:] == ["Mesero", "Cocina"]


def test_precios_con_isv_incluido_separan_el_impuesto_hacia_adentro(client, auth, rest):
    assert client.get("/api/settings", headers=auth).json()["prices_include_tax"] is True
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)  # L 100 con ISV
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    doc = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(100)}, headers=auth).json()["document"]
    assert doc["total"] == 100 and doc["gravado_15"] == 86.96 and doc["isv_15"] == 13.04 and doc["subtotal"] == 86.96
    # el total es exactamente lo que ve el cliente aunque haya varias líneas con centavos
    t = open_tab(client, auth, rest, "2")
    add(client, auth, t, rest["burger"], 3, descriptive_ids=[rest["queso"]["id"]])  # 3 × 115
    add(client, auth, t, rest["cola"], 7)  # 7 × 30
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    doc = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(555)}, headers=auth).json()["document"]
    assert doc["total"] == 555 and round(doc["gravado_15"] + doc["isv_15"], 2) == 555
    # una nota de crédito de una línea devuelve el precio final y deja las existencias como estaban
    i = ids(client, auth)
    note = client.post("/api/documents", json={"kind": "nota", "client_id": i["final"]["id"], "warehouse_id": i["wh"]["id"], "ref_document_id": doc["id"],
                                               "items": [{"product_id": rest["cola"]["id"], "qty": 1, "price": 30}]}, headers=auth)
    assert note.status_code == 200 and note.json()["total"] == 30


def test_sin_el_ajuste_el_impuesto_se_suma_como_siempre(client, auth, rest):
    set_prices_include_tax(client, auth, False)
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    doc = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(115)}, headers=auth).json()["document"]
    assert doc["total"] == 115 and doc["gravado_15"] == 100 and doc["isv_15"] == 15


def test_cambiar_comensales_y_nombre_de_la_cuenta(client, auth, rest):
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["cola"], 1, guest=3)
    r = client.put(f"/api/tabs/{t['id']}/guests", json={"guests": 5, "name": "Sra. Gómez"}, headers=auth)
    assert r.status_code == 200 and r.json()["guests"] == 5 and r.json()["name"] == "Sra. Gómez"
    bad = client.put(f"/api/tabs/{t['id']}/guests", json={"guests": 2}, headers=auth)
    assert bad.status_code == 400 and "comensal 3" in bad.json()["detail"]  # el 3 ya tiene consumos
    assert client.put(f"/api/tabs/{t['id']}/guests", json={"guests": 0}, headers=auth).status_code == 422


def test_la_cuenta_informa_los_minutos_y_el_estado_de_cocina(client, auth, rest):
    t = open_tab(client, auth, rest)
    assert t["minutes"] == 0 and client.get("/api/salons", headers=auth).json()[0]["items"][0]["tab"]["minutes"] == 0
    add(client, auth, t, rest["cola"], 1)
    sent = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()["tab"]
    assert sent["lines"][0]["kds"] == "pendiente"
    lid = sent["lines"][0]["id"]
    client.put(f"/api/kitchen/lines/{lid}/status", json={"status": "listo"}, headers=auth)
    assert client.get(f"/api/tabs/{t['id']}", headers=auth).json()["lines"][0]["kds"] == "listo"


def test_las_propinas_entran_al_cuadre_del_turno_y_del_dia(client, auth, login, rest):
    cajero = make_user(client, auth, login, "Cajero", "Carla Caja")
    sh = client.post("/api/shifts/open", json={"caja": "Caja 1", "opening": 500}, headers=cajero).json()
    t = open_tab(client, cajero, rest)
    add(client, cajero, t, rest["burger"], 1)  # L 100
    client.post(f"/api/tabs/{t['id']}/send", headers=cajero)
    pay = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": [{"method": "Tarjeta", "amount": 100}], "tip": 10, "tip_method": "Tarjeta"}, headers=cajero)
    assert pay.status_code == 200, pay.text
    t2 = open_tab(client, cajero, rest, "2")
    add(client, cajero, t2, rest["cola"], 2)  # L 60
    client.post(f"/api/tabs/{t2['id']}/send", headers=cajero)
    client.post(f"/api/tabs/{t2['id']}/pay", json={"payments": [{"method": "Efectivo", "amount": 60}], "tip": 6, "tip_method": "Efectivo"}, headers=cajero)
    cur = client.get(f"/api/shifts/{sh['id']}", headers=cajero).json()
    # efectivo: fondo 500 + cobro 60 + propina 6 · tarjeta: cobro 100 + propina 10
    assert cur["expected"]["Efectivo"] == 566 and cur["expected"]["Tarjeta"] == 110 and cur["tips"] == {"Efectivo": 6.0, "Tarjeta": 10.0} and cur["tips_total"] == 16
    assert cur["collected"] == 160  # las propinas no son ventas
    done = client.post(f"/api/shifts/{sh['id']}/close", json={"counted": {"Efectivo": 566, "Tarjeta": 110, "Transferencia": 0}}, headers=cajero).json()
    assert done["difference"] == 0 and done["tips_total"] == 16
    # el corte del día muestra las propinas y las suma a lo esperado
    corte = client.get("/api/cash/close", headers=cajero).json()
    assert corte["tips_total"] == 16 and {x["method"]: x["total"] for x in corte["tips"]} == {"Efectivo": 6.0, "Tarjeta": 10.0} and corte["collected"] == 160
    rec = client.post("/api/cash/close/record", json={"opening": 500, "counted": {"Efectivo": 566, "Tarjeta": 110, "Transferencia": 0}}, headers=cajero)
    assert rec.status_code == 200, rec.text
    lines = {x["method"]: x for x in rec.json()["lines"]}
    assert lines["Efectivo"]["expected"] == 566 and lines["Tarjeta"]["expected"] == 110  # lo esperado incluye las propinas
    assert rec.json()["result"] == "cuadra"


def test_formas_de_mesa_y_puerta_se_aceptan_y_las_demas_no(client, auth, rest):
    sid = rest["salon"]["id"]
    forma = lambda shape, kind="mesa", name="X": client.put(f"/api/salons/{sid}/layout", json={"items": [{"kind": kind, "name": name, "shape": shape, "seats": 4}]}, headers=auth)
    for shape in ("cuadrada", "redonda", "rectangular", "ovalada", "cabina", "barra", "alta", "sofa"):
        assert forma(shape).status_code == 200, shape
    assert forma("rectangular", "puerta", "").status_code == 200  # la puerta es un elemento más del plano
    assert forma("hexagonal").status_code == 400
