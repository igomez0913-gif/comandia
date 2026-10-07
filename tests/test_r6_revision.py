"""Revisión independiente de la división de cuenta: cada defecto que encontró queda cubierto por una prueba que antes fallaba.
Precisión de cantidades (factura, nota de crédito, inventario), cocina con muchas comandas, unir/transferir cuentas, cierre de cuentas y concurrencia."""
import random
import threading
from datetime import timedelta

import pytest

from test_api import ids, stock
from test_r1_recetas import make_item, set_recipe
from test_r2_salon import add, open_tab, pay_all, rest  # noqa: F401
from test_r5_dividir import pay_guest, send, split, tab_of


def doc_of(client, auth, did):
    r = client.get(f"/api/documents/{did}", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["document"]


def credit_note(client, auth, d, items):
    body = {"kind": "nota", "client_id": d["client_id"], "warehouse_id": ids(client, auth)["wh"]["id"], "ref_document_id": d["id"], "items": items}
    return client.post("/api/documents", json=body, headers=auth)


def mini_tab(client, auth, rest, product, qty=1, guests=3, mesa="1"):  # noqa: F811
    t = open_tab(client, auth, rest, mesa, guests=guests)
    t = add(client, auth, t, product, qty)
    return t, send(client, auth, t)["lines"][0]["id"]


# ───────────────────────── la factura de una parte cuadra y se puede acreditar completa ─────────────────────────
def test_la_factura_de_una_parte_guarda_la_fraccion_y_cantidad_por_precio_da_el_importe(client, auth, rest):  # noqa: F811
    t, lid = mini_tab(client, auth, rest, rest["burger"])
    split(client, auth, t, lid, [1, 2, 3])
    d = pay_guest(client, auth, t, 1, 33.34)["document"]
    it = doc_of(client, auth, d["id"])["items"][0]
    assert it["qty"] == pytest.approx(0.3334, abs=1e-9) and it["price"] == 100.0 and it["total"] == 33.34
    assert round(it["qty"] * it["price"], 2) == it["total"]  # lo que se imprime en la factura cuadra


def test_la_nota_de_credito_de_una_parte_devuelve_el_importe_exacto(client, auth, rest):  # noqa: F811
    t, lid = mini_tab(client, auth, rest, rest["burger"])
    split(client, auth, t, lid, [1, 2, 3])
    d = pay_guest(client, auth, t, 1, 33.34)["document"]
    full = doc_of(client, auth, d["id"])
    pid = str(full["items"][0]["product_id"])
    left = full["creditable"][pid]  # lo que la pantalla de nota de crédito precarga
    assert left == pytest.approx(0.3334, abs=1e-9)
    n = credit_note(client, auth, full, [{"product_id": full["items"][0]["product_id"], "qty": left, "price": 100}])
    assert n.status_code == 200, n.text
    assert n.json()["total"] == 33.34  # antes devolvía 33.00 y quedaban 0.34 sin poder acreditarse
    after = doc_of(client, auth, d["id"])
    assert after["creditable"] == {} and after["creditable_amount"] == 0


def test_una_parte_diminuta_no_sale_con_cantidad_cero_y_se_puede_acreditar(client, auth, rest):  # noqa: F811
    t, lid = mini_tab(client, auth, rest, rest["burger"], guests=2)
    assert split(client, auth, t, lid, [1, 2], weights=[1, 1000]).status_code == 200
    gt = tab_of(client, auth, t["id"])["guests_totals"]
    assert gt["1"] == 0.1 and gt["2"] == 99.9
    d = pay_guest(client, auth, t, 1, 0.1)["document"]
    full = doc_of(client, auth, d["id"])
    assert full["items"][0]["qty"] > 0 and full["creditable"], full["items"]  # antes: cantidad 0.00 y nunca se podía acreditar
    n = credit_note(client, auth, full, [{"product_id": full["items"][0]["product_id"], "qty": list(full["creditable"].values())[0], "price": 100}])
    assert n.status_code == 200 and n.json()["total"] == 0.1


def test_una_sola_factura_de_toda_la_cuenta_dividida_en_7_se_acredita_completa(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=7)
    add(client, auth, t, rest["burger"], 1)
    send(client, auth, t)
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 7}, headers=auth).status_code == 200
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(100)}, headers=auth)  # una sola factura con las 7 partes
    assert r.status_code == 200, r.text
    full = doc_of(client, auth, r.json()["document"]["id"])
    assert len(full["items"]) == 7 and sum(i["qty"] for i in full["items"]) == pytest.approx(1.0, abs=1e-7)  # antes sumaban 0.98
    pid = full["items"][0]["product_id"]
    n = credit_note(client, auth, full, [{"product_id": pid, "qty": full["creditable"][str(pid)], "price": 100}])
    assert n.status_code == 200 and n.json()["total"] == 100.0


def test_propiedad_cada_parte_facturada_cuadra_y_la_suma_es_el_plato(client, auth, rest):  # noqa: F811
    """Con precios y números de partes al azar: cantidad × precio = importe en cada línea y las partes suman el plato completo."""
    rng = random.Random(11)
    plato = make_item(client, auth, "PL-AZAR", "Plato al azar", "producto", rest["dep"], rest["burger"]["category_id"], price=1, cost=1, stock_qty=100000)
    for k in range(8):
        price = round(rng.uniform(1, 800), 2)
        client.put(f"/api/products/{plato['id']}", json={"sku": "PL-AZAR", "name": "Plato al azar", "department_id": rest["dep"], "category_id": rest["burger"]["category_id"],
                                                        "base_unit": "und", "cost": 1, "price": price, "kind": "producto", "tax_treatment": "gravado15"}, headers=auth)
        n = rng.randint(2, 9)
        t = open_tab(client, auth, rest, "1" if k % 2 == 0 else "2", guests=n)
        add(client, auth, t, plato, rng.choice([1, 1, 2, 3]))
        send(client, auth, t)
        total = tab_of(client, auth, t["id"])["total"]
        assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": n}, headers=auth).status_code == 200
        r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(total)}, headers=auth)
        assert r.status_code == 200, r.text
        full = doc_of(client, auth, r.json()["document"]["id"])
        assert round(sum(i["total"] for i in full["items"]), 2) == pytest.approx(total, abs=0.005)
        assert all(abs(round(i["qty"] * i["price"], 2) - i["total"]) < 0.005 for i in full["items"]), full["items"]


# ───────────────────────── inventario ─────────────────────────
def _receta(client, auth, rest, ingrediente_stock, cantidad, sku="X1"):  # noqa: F811
    ins = make_item(client, auth, f"INS-{sku}", f"Insumo {sku}", "insumo", rest["dep"], rest["burger"]["category_id"], cost=60, unit="lb", stock_qty=ingrediente_stock)
    plato = make_item(client, auth, f"PL-{sku}", f"Plato {sku}", "platillo", rest["dep"], rest["burger"]["category_id"], price=100, station="cocina")
    assert set_recipe(client, auth, plato, [(ins, cantidad)]).status_code == 200
    return ins, plato


def test_un_ingrediente_de_pocas_milesimas_se_descuenta_aunque_el_plato_no_se_divida(client, auth, rest):  # noqa: F811
    wh = ids(client, auth)["wh"]["id"]
    ins, plato = _receta(client, auth, rest, 50, 0.004, "SAL")
    for i in range(10):
        t = open_tab(client, auth, rest, "1" if i % 2 == 0 else "2")
        add(client, auth, t, plato, 1)
        send(client, auth, t)
        assert client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(100)}, headers=auth).status_code == 200
    assert stock(client, auth, "INS-SAL", wh) == pytest.approx(50 - 0.04, abs=1e-6)  # antes se redondeaba a cero en cada venta


@pytest.mark.parametrize("partes,receta", [(7, 0.03), (3, 0.03), (2, 0.03), (5, 0.02), (8, 0.03), (3, 0.01)])
def test_dividir_un_plato_gasta_los_mismos_ingredientes_que_sin_dividir(client, auth, rest, partes, receta):  # noqa: F811
    wh = ids(client, auth)["wh"]["id"]
    ins, plato = _receta(client, auth, rest, 50, receta, "DIV")
    t, lid = mini_tab(client, auth, rest, plato, guests=partes)
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": partes}, headers=auth).status_code == 200
    gt = tab_of(client, auth, t["id"])["guests_totals"]
    for g in range(1, partes + 1):
        pay_guest(client, auth, t, g, gt[str(g)])
    assert stock(client, auth, "INS-DIV", wh) == pytest.approx(50 - receta, abs=0.0006)  # antes: 0 (nada), +33% o más según las partes


def test_el_ultimo_comensal_puede_pagar_su_parte_aunque_la_existencia_alcance_justo(client, auth, rest):  # noqa: F811
    wh = ids(client, auth)["wh"]["id"]
    ins, plato = _receta(client, auth, rest, 0.5, 0.5, "UL")
    t, lid = mini_tab(client, auth, rest, plato)
    split(client, auth, t, lid, [1, 2, 3])
    gt = tab_of(client, auth, t["id"])["guests_totals"]
    pay_guest(client, auth, t, 1, gt["1"])
    pay_guest(client, auth, t, 2, gt["2"])
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"guest": 3, "payments": pay_all(gt["3"])}, headers=auth)
    assert r.status_code == 200, r.text  # antes: «Stock insuficiente» y la cuenta quedaba atascada
    assert r.json()["closed"] is True and stock(client, auth, "INS-UL", wh) == pytest.approx(0, abs=0.0011)


def test_el_inventario_no_pasa_a_negativo_por_redondeo_pero_si_falta_de_verdad_se_rechaza(client, auth, rest):  # noqa: F811
    ins, plato = _receta(client, auth, rest, 0.1, 0.5, "FALTA")
    t, lid = mini_tab(client, auth, rest, plato, guests=1)
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(100)}, headers=auth)
    assert r.status_code == 400 and "Stock insuficiente" in r.json()["detail"]


# ───────────────────────── importes: redondeo igual en todas partes, centavos rotativos, importes enormes ─────────────────────────
def test_dividir_un_consumo_con_medias_porciones_no_cambia_el_total(client, auth, rest):  # noqa: F811
    p = make_item(client, auth, "X1", "Plato X", "producto", rest["dep"], rest["burger"]["category_id"], price=45.55, cost=1, stock_qty=100)
    t = open_tab(client, auth, rest, guests=2)
    t = add(client, auth, t, p, 0.5)
    assert t["total"] == 22.77
    lid = send(client, auth, t)["lines"][0]["id"]
    r = split(client, auth, t, lid, [1, 2]).json()
    assert r["total"] == 22.77 and round(sum(r["guests_totals"].values()), 2) == 22.77  # antes subía a 22.78
    r2 = client.post(f"/api/tabs/{t['id']}/pay", json={"payments": pay_all(22.77)}, headers=auth)
    assert r2.status_code == 200 and r2.json()["closed"] is True


def test_los_centavos_sobrantes_rotan_entre_consumos_alternados(client, auth, rest):  # noqa: F811
    a = make_item(client, auth, "BEB-A", "Cerveza", "producto", rest["dep"], rest["burger"]["category_id"], price=35, cost=1, stock_qty=1000)
    b = make_item(client, auth, "PL-B", "Pastel", "producto", rest["dep"], rest["burger"]["category_id"], price=55.55, cost=1, stock_qty=1000)
    t = open_tab(client, auth, rest, guests=2)
    for _ in range(20):
        add(client, auth, t, b, 1)
        t = add(client, auth, t, a, 1)
    send(client, auth, t)
    r = client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 2}, headers=auth).json()
    g = r["guests_totals"]
    assert r["total"] == 1811.0 and abs(g["1"] - g["2"]) <= 0.01  # antes: el comensal 1 pagaba 0.20 más, siempre


def test_un_importe_enorme_que_no_se_puede_dividir_con_exactitud_se_rechaza_y_no_cambia_nada(client, auth, rest):  # noqa: F811
    p = make_item(client, auth, "BANQ", "Banquete por persona", "producto", rest["dep"], rest["burger"]["category_id"], price=5000, cost=1, stock_qty=1000)
    t = open_tab(client, auth, rest, guests=7)
    t = add(client, auth, t, p, 250)
    send(client, auth, t)
    r = client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 7}, headers=auth)
    assert r.status_code == 400 and "demasiado grande" in r.json()["detail"]
    after = tab_of(client, auth, t["id"])
    assert after["total"] == 1250000.0 and len(after["lines"]) == 1 and after["lines"][0]["share"] is None  # antes se perdían L 0.06 sin avisar


def test_dividir_toda_la_cuenta_es_todo_o_nada(client, auth, rest):  # noqa: F811
    """Si un consumo no se puede dividir, ninguno de los demás queda a medias."""
    chico = make_item(client, auth, "CH", "Chico", "producto", rest["dep"], rest["burger"]["category_id"], price=10, cost=1, stock_qty=100)
    grande = make_item(client, auth, "BANQ2", "Banquete", "producto", rest["dep"], rest["burger"]["category_id"], price=5000, cost=1, stock_qty=1000)
    t = open_tab(client, auth, rest, guests=7)
    add(client, auth, t, chico, 1)
    t = add(client, auth, t, grande, 250)
    send(client, auth, t)
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 7}, headers=auth).status_code == 400
    assert all(ln["share"] is None and ln["group_id"] is None for ln in tab_of(client, auth, t["id"])["lines"])


# ───────────────────────── deshacer la división devuelve cada consumo a su comensal ─────────────────────────
def test_juntar_despues_de_dividir_toda_la_cuenta_devuelve_los_comensales_originales(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["burger"], 1, guest=1)
    add(client, auth, t, rest["cola"], 1, guest=2)
    t = add(client, auth, t, rest["cola"], 2, guest=3)
    send(client, auth, t)
    before = tab_of(client, auth, t["id"])["guests_totals"]
    assert before == {"1": 100.0, "2": 30.0, "3": 60.0}
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 3}, headers=auth).status_code == 200
    r = client.post(f"/api/tabs/{t['id']}/unsplit", json={}, headers=auth)
    assert r.status_code == 200 and r.json()["guests_totals"] == before  # antes todo quedaba con el comensal 1


def test_juntar_un_plato_partido_lo_devuelve_a_quien_lo_pidio(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    t = add(client, auth, t, rest["burger"], 1, guest=2)
    lid = send(client, auth, t)["lines"][0]["id"]
    split(client, auth, t, lid, [1, 2, 3])
    r = client.post(f"/api/tabs/{t['id']}/unsplit", json={"line_id": lid}, headers=auth)
    assert r.status_code == 200 and r.json()["guests_totals"] == {"2": 100.0}


# ───────────────────────── la nota de un plato compartido llega a cocina ─────────────────────────
def test_la_nota_escrita_en_cualquier_parte_llega_a_la_comanda(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    t = add(client, auth, t, rest["burger"], 1)
    lines = split(client, auth, t, t["lines"][0]["id"], [1, 2, 3]).json()["lines"]
    child = next(ln for ln in lines if ln["is_part"])
    assert client.put(f"/api/tabs/{t['id']}/lines/{child['id']}", json={"note": "SIN GLUTEN, es alergia"}, headers=auth).status_code == 200
    s = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()
    assert [ln["note"] for c in s["comandas"] for ln in c["lines"]] == ["SIN GLUTEN, es alergia"]  # antes salía vacía
    k = client.get("/api/kitchen", headers=auth).json()["comandas"]
    assert k[0]["lines"][0]["note"] == "SIN GLUTEN, es alergia"
    assert {ln["note"] for ln in s["tab"]["lines"]} == {"SIN GLUTEN, es alergia"}  # todas las partes muestran la misma nota


# ───────────────────────── pantalla de cocina ─────────────────────────
def test_la_cocina_sigue_viendo_lo_nuevo_con_cientos_de_comandas_servidas_antes(client, auth, rest):  # noqa: F811
    from app.cocina import Comanda
    from app.main import SessionLocal, now_local
    from app.salon import Tab, TabLine
    db = SessionLocal()
    try:
        for i in range(310):  # un día muy movido: comandas ya servidas de cuentas ya cobradas
            tab = Tab(number=f"HX-{i:06d}", status="Cerrada", closed_at=now_local(), opened_at=now_local(), waiter_name="x")
            db.add(tab)
            db.flush()
            c = Comanda(number=f"CM-9{i:05d}", tab_id=tab.id, station="cocina", created_at=now_local())
            db.add(c)
            db.flush()
            db.add(TabLine(tab_id=tab.id, product_id=rest["cola"]["id"], description="Refresco", qty=1, unit_price=30, status="cobrada", comanda_id=c.id, kds_status="servido"))
        old = Tab(number="HX-VIEJA", status="Cerrada", closed_at=now_local() - timedelta(hours=5), opened_at=now_local() - timedelta(hours=6), waiter_name="x")
        db.add(old)
        db.flush()  # una cuenta cerrada hace horas con un plato que nadie marcó «servido» no se queda para siempre
        co = Comanda(number="CM-8VIEJA", tab_id=old.id, station="cocina", created_at=now_local() - timedelta(hours=6))
        db.add(co)
        db.flush()
        db.add(TabLine(tab_id=old.id, product_id=rest["cola"]["id"], description="Refresco viejo", qty=1, unit_price=30, status="cobrada", comanda_id=co.id, kds_status="listo"))
        db.commit()
    finally:
        db.close()
    t = open_tab(client, auth, rest)
    add(client, auth, t, rest["burger"], 1)
    send(client, auth, t)
    got = client.get("/api/kitchen", headers=auth).json()["comandas"]
    assert [ln["description"] for c in got for ln in c["lines"]] == ["Hamburguesa"]  # antes: pantalla vacía
    assert [ln["description"] for c in client.get("/api/kitchen?station=cocina", headers=auth).json()["comandas"] for ln in c["lines"]] == ["Hamburguesa"]


def test_unir_cuentas_no_hace_desaparecer_los_pedidos_de_la_cocina(client, auth, rest):  # noqa: F811
    a, b = open_tab(client, auth, rest, "1"), open_tab(client, auth, rest, "2")
    add(client, auth, a, rest["cola"], 1)
    add(client, auth, b, rest["burger"], 1)
    send(client, auth, a)
    send(client, auth, b)
    assert len(client.get("/api/kitchen", headers=auth).json()["comandas"]) == 2
    assert client.post(f"/api/tabs/{a['id']}/merge", json={"from_tab_id": b["id"]}, headers=auth).status_code == 200
    got = client.get("/api/kitchen", headers=auth).json()["comandas"]
    assert sorted(ln["description"] for c in got for ln in c["lines"]) == ["Hamburguesa", "Refresco"]  # antes la hamburguesa desaparecía
    assert {c["tab_id"] for c in got} == {a["id"]} and all("1" in c["tables"] and "2" in c["tables"] for c in got)
    assert len(client.get(f"/api/comandas?tab_id={a['id']}", headers=auth).json()) == 2


def test_transferir_un_plato_enviado_cambia_la_mesa_que_ve_la_cocina(client, auth, rest):  # noqa: F811
    a = open_tab(client, auth, rest, "1")
    add(client, auth, a, rest["burger"], 1)
    add(client, auth, a, rest["burger"], 1)  # dos hamburguesas en la misma comanda
    s = send(client, auth, a)
    lines = s["lines"]
    moved = lines[0]["id"]
    r = client.post(f"/api/tabs/{a['id']}/transfer", json={"line_ids": [moved], "to_table_id": rest["mesas"]["3"]}, headers=auth)
    assert r.status_code == 200, r.text
    got = client.get("/api/kitchen", headers=auth).json()["comandas"]
    assert sorted(c["tables"] for c in got) == ["1", "3"] and sum(len(c["lines"]) for c in got) == 2  # antes la cocina seguía diciendo «Mesa 1» para las dos
    for c in got:
        assert len(c["lines"]) == 1
    ready_line = next(ln for c in got if c["tables"] == "3" for ln in c["lines"])
    assert ready_line["id"] == moved
    # cuando se va toda la comanda, la comanda misma cambia de cuenta
    r2 = client.post(f"/api/tabs/{a['id']}/transfer", json={"line_ids": [lines[1]["id"]], "to_table_id": rest["mesas"]["3"]}, headers=auth)
    assert r2.status_code == 200
    got2 = client.get("/api/kitchen", headers=auth).json()["comandas"]
    assert {c["tables"] for c in got2} == {"3"}


# ───────────────────────── cuentas que quedan abiertas ─────────────────────────
def test_la_cuenta_se_cierra_sola_si_lo_pendiente_se_anula_despues_de_cobrar_a_un_comensal(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    add(client, auth, t, rest["burger"], 1, guest=1)
    add(client, auth, t, rest["cola"], 1, guest=2)
    send(client, auth, t)
    pay_guest(client, auth, t, 1, 100)
    cola = next(ln for ln in tab_of(client, auth, t["id"])["lines"] if ln["status"] == "enviada")
    r = client.post(f"/api/tabs/{t['id']}/lines/{cola['id']}/void", json={"reason": "El cliente se fue"}, headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "Cerrada"  # antes: abierta para siempre y la mesa ocupada
    assert client.post("/api/tabs", json={"table_ids": [rest["mesas"]["1"]]}, headers=auth).status_code == 200  # la mesa quedó libre


def test_la_cuenta_se_cierra_sola_si_lo_pendiente_pasa_a_otra_mesa_despues_de_cobrar(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    add(client, auth, t, rest["burger"], 1, guest=1)
    add(client, auth, t, rest["cola"], 1, guest=2)
    send(client, auth, t)
    pay_guest(client, auth, t, 1, 100)
    cola = next(ln for ln in tab_of(client, auth, t["id"])["lines"] if ln["status"] == "enviada")
    r = client.post(f"/api/tabs/{t['id']}/transfer", json={"line_ids": [cola["id"]], "to_table_id": rest["mesas"]["2"]}, headers=auth)
    assert r.status_code == 200 and r.json()["from"]["status"] == "Cerrada" and r.json()["to"]["status"] == "Abierta"


def test_una_cuenta_sin_cobros_no_se_cierra_sola_al_quedar_vacia(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest)
    t = add(client, auth, t, rest["cola"], 1)
    r = client.post(f"/api/tabs/{t['id']}/lines/{t['lines'][0]['id']}/void", json={}, headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "Abierta"  # se cierra a propósito con «Cerrar cuenta vacía»


def test_si_se_fueron_sin_pagar_se_anulan_las_partes_que_faltan_y_lo_cobrado_se_conserva(client, auth, rest):  # noqa: F811
    t, lid = mini_tab(client, auth, rest, rest["burger"])
    split(client, auth, t, lid, [1, 2, 3])
    pay_guest(client, auth, t, 1, 33.34)
    pending = next(ln for ln in tab_of(client, auth, t["id"])["lines"] if ln["status"] == "enviada")
    assert pending["group_paid"] is True  # la pantalla lo sabe para no ofrecer «Juntar»
    r = client.post(f"/api/tabs/{t['id']}/lines/{pending['id']}/void", json={"reason": "Se fueron sin pagar"}, headers=auth)
    assert r.status_code == 200
    states = sorted(ln["status"] for ln in r.json()["lines"])
    assert states == ["anulada", "anulada", "cobrada"] and r.json()["status"] == "Cerrada"
    rep = client.get("/api/reports/voided-lines", headers=auth).json()
    assert len(rep["rows"]) == 1 and rep["rows"][0]["amount"] == 66.66
    # lo que queda de un plato con partes cobradas no se puede juntar ni pasar a otra cuenta (se cobraría de nuevo lo ya cobrado)
    t2, l2 = mini_tab(client, auth, rest, rest["burger"], mesa="2")
    split(client, auth, t2, l2, [1, 2, 3])
    pay_guest(client, auth, t2, 1, 33.34)
    rest_lines = [ln["id"] for ln in tab_of(client, auth, t2["id"])["lines"] if ln["status"] == "enviada"]
    assert client.post(f"/api/tabs/{t2['id']}/unsplit", json={"line_id": rest_lines[0]}, headers=auth).status_code == 400
    assert client.post(f"/api/tabs/{t2['id']}/transfer", json={"line_ids": rest_lines, "to_table_id": rest["mesas"]["3"]}, headers=auth).status_code == 400


def test_el_reporte_de_anulados_no_pierde_platos_por_las_partes(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=20)
    for _ in range(51):
        client.post(f"/api/tabs/{t['id']}/lines", json={"product_id": rest["burger"]["id"], "qty": 1}, headers=auth)
    client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    tab = client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 20}, headers=auth).json()
    for h in [ln for ln in tab["lines"] if not ln["is_part"]]:
        assert client.post(f"/api/tabs/{t['id']}/lines/{h['id']}/void", json={"reason": "Cliente se fue"}, headers=auth).status_code == 200
    rep = client.get("/api/reports/voided-lines", headers=auth).json()
    assert len(rep["rows"]) == 51 and rep["total"] == 5100.0  # antes: 1000 filas tomadas, las partes descartadas y platos que faltaban


# ───────────────────────── bitácora ─────────────────────────
def test_la_bitacora_dice_que_consumos_y_de_que_comensal_a_cual(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    t = add(client, auth, t, rest["burger"], 1, guest=1)
    lid = send(client, auth, t)["lines"][0]["id"]
    assert client.post(f"/api/tabs/{t['id']}/guest", json={"line_ids": [lid], "guest": 3}, headers=auth).status_code == 200
    split(client, auth, t, lid, [1, 2], weights=[1, 3])
    client.post(f"/api/tabs/{t['id']}/unsplit", json={}, headers=auth)
    rows = client.get("/api/audit", headers=auth).json()["rows"]
    detail = {r["action"]: r["detail"] for r in rows}
    assert "Hamburguesa (C1→C3)" in detail["Reasignó consumos a un comensal"]
    assert "C1 L 25.00, C2 L 75.00" in detail["Dividió un plato entre comensales"]
    assert "Hamburguesa" in detail["Juntó las partes de un plato"]


# ───────────────────────── concurrencia (solo MySQL/MariaDB: SQLite no bloquea filas) ─────────────────────────
def _es_mysql():
    from app.main import DB_URL
    return not DB_URL.startswith("sqlite")


@pytest.mark.skipif(not _es_mysql(), reason="SQLite no bloquea filas: la prueba de concurrencia solo tiene sentido en MySQL/MariaDB")
def test_dos_cobros_simultaneos_del_mismo_comensal_emiten_una_sola_factura(client, auth, rest, monkeypatch):  # noqa: F811
    """Un doble clic en «Cobrar»: la segunda petición ya leyó (su sesión, su usuario) cuando la primera todavía cobraba, y al obtener el bloqueo tiene que ver lo ya cobrado.
    Con el aislamiento por omisión de MySQL (REPEATABLE READ) veía las líneas «enviadas» de antes y emitía una segunda factura."""
    import time

    import app.salon as salon
    wh = ids(client, auth)["wh"]["id"]
    t = open_tab(client, auth, rest, guests=2)
    add(client, auth, t, rest["burger"], 1, guest=1)
    add(client, auth, t, rest["cola"], 1, guest=2)  # el comensal 2 no paga: la cuenta sigue abierta y la segunda petición no puede apoyarse en «ya está cerrada»
    send(client, auth, t)
    carne0 = stock(client, auth, "INS-CARNE", wh)
    real = salon._pos_sale
    started = threading.Event()

    def slow_sale(*a, **kw):
        started.set()
        time.sleep(0.8)  # la primera caja tarda: la segunda llega, lee y se queda esperando el bloqueo
        return real(*a, **kw)

    monkeypatch.setattr(salon, "_pos_sale", slow_sale)
    results = []

    def pay(wait):
        if wait:
            started.wait(5)
            time.sleep(0.2)
        results.append(client.post(f"/api/tabs/{t['id']}/pay", json={"guest": 1, "payments": pay_all(100)}, headers=auth).status_code)

    threads = [threading.Thread(target=pay, args=(False,)), threading.Thread(target=pay, args=(True,))]
    [th.start() for th in threads]
    [th.join() for th in threads]
    assert sorted(results) == [200, 400], results  # el segundo ve lo ya cobrado
    assert stock(client, auth, "INS-CARNE", wh) == pytest.approx(carne0 - 0.15, abs=1e-6)  # el inventario se descontó una sola vez
    assert len([ln for ln in tab_of(client, auth, t["id"])["lines"] if ln["status"] == "cobrada"]) == 1


# ───────────────────────── migración de la precisión de las columnas ─────────────────────────
def test_el_script_sql_y_el_esquema_completo_traen_los_cambios_de_precision():
    import os

    from app.main import BASE_DIR, NEW_COLUMNS, WIDEN_COLUMNS
    sql = open(os.path.join(BASE_DIR, "actualizar-db.sql"), encoding="utf-8").read()
    assert [f"{t}.{c}" for t, c, _, _ in WIDEN_COLUMNS if f"CALL comandia_widen_column('{t}', '{c}'" not in sql] == []
    assert ("tab_lines", "orig_guest", "INTEGER NULL") in NEW_COLUMNS
    full = open(os.path.join(BASE_DIR, "schema-completo.sql"), encoding="utf-8").read()
    assert "qty NUMERIC(16, 8)" in full and "qty NUMERIC(14, 4)" in full and "orig_guest INTEGER" in full  # regenerado con herramientas/generar-schema.py


@pytest.mark.skipif(not _es_mysql(), reason="SQLite no limita los decimales: solo MySQL/MariaDB necesita la migración")
def test_la_migracion_agranda_las_columnas_de_una_base_existente_y_se_puede_repetir(client):
    from app.main import WIDEN_COLUMNS, engine, widen_columns
    with engine.begin() as c:  # una base de la versión anterior: cantidades con 2 decimales
        for t, col, _ddl, _s in WIDEN_COLUMNS:
            c.exec_driver_sql(f"ALTER TABLE `{t}` MODIFY COLUMN `{col}` DECIMAL(12,2) NULL")
    widen_columns(engine)
    widen_columns(engine)
    with engine.connect() as c:
        got = {(t, col): int(c.exec_driver_sql("SELECT NUMERIC_SCALE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = %s", (t, col)).scalar())
               for t, col, _d, _s in WIDEN_COLUMNS}
    assert got == {(t, col): sc for t, col, _d, sc in WIDEN_COLUMNS}
