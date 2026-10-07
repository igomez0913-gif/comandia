"""Dividir la cuenta: reasignar comensal después de enviar, partir un plato compartido, partes iguales, y que el dinero cuadre al centavo."""
import random
from types import SimpleNamespace

import pytest

from test_api import ids, make_user, stock
from test_r1_recetas import make_item
from test_r2_salon import add, open_tab, pay_all, rest  # noqa: F401
from app.salon import line_amount, split_cents


def tab_of(client, auth, tid):
    return client.get(f"/api/tabs/{tid}", headers=auth).json()


def send(client, auth, t):
    r = client.post(f"/api/tabs/{t['id']}/send", headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["tab"]


def split(client, auth, t, lid, guests, weights=None):
    parts = [{"guest": g, **({"weight": weights[i]} if weights else {})} for i, g in enumerate(guests)]
    return client.post(f"/api/tabs/{t['id']}/lines/{lid}/split", json={"parts": parts}, headers=auth)


def pay_guest(client, auth, t, guest, amount):
    r = client.post(f"/api/tabs/{t['id']}/pay", json={"guest": guest, "payments": pay_all(amount)}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()


# ───────────────────────── el dinero cuadra al centavo ─────────────────────────
def test_split_cents_nunca_pierde_ni_sobra_un_centavo():
    assert split_cents(10000, [1, 1, 1]) == [3334, 3333, 3333] and split_cents(100, [1, 2]) == [33, 67] and split_cents(1, [1, 1]) == [1, 0]
    rng = random.Random(2026)
    for _ in range(3000):
        total, n = rng.randint(1, 2_000_000), rng.randint(2, 12)
        weights = [rng.choice([1, 1, 1, 2, 3, 0.5, 1.5]) for _ in range(n)]
        parts = split_cents(total, weights)
        assert sum(parts) == total and min(parts) >= 0
        eq = split_cents(total, [1] * n)
        assert sum(eq) == total and max(eq) - min(eq) <= 1  # partes iguales: nadie paga más de un centavo de diferencia


def test_la_fraccion_guardada_factura_exactamente_los_centavos_repartidos():
    """Con la fracción de 8 decimales que se guarda, qty × fracción × precio da justo los centavos de cada parte, para cualquier precio y cantidad."""
    from decimal import ROUND_HALF_EVEN, Decimal
    rng = random.Random(7)
    for _ in range(3000):
        price, qty, n = round(rng.uniform(0.05, 9999.99), 2), rng.randint(1, 20), rng.randint(2, 9)
        total = int((Decimal(str(qty)) * Decimal(str(price)) * 100).quantize(Decimal(1)))
        if total < n:
            continue
        cents = split_cents(total, [1] * n)
        shares = [(Decimal(c) / Decimal(total)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_EVEN) for c in cents]
        amounts = [line_amount(SimpleNamespace(qty=Decimal(qty), share=s, unit_price=Decimal(str(price)))) for s in shares]
        assert [round(a * 100) for a in amounts] == cents, (price, qty, n)


# ───────────────────────── reasignar comensal ─────────────────────────
def test_reasignar_comensal_despues_de_enviar_a_cocina(client, auth, login, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["burger"], 1, guest=1)
    add(client, auth, t, rest["cola"], 1, guest=1)
    sent = send(client, auth, t)
    cola = next(ln for ln in sent["lines"] if ln["description"] == "Refresco")
    assert sent["guests_totals"] == {"1": 130.0}
    r = client.post(f"/api/tabs/{t['id']}/guest", json={"line_ids": [cola["id"]], "guest": 3}, headers=auth)
    assert r.status_code == 200 and r.json()["guests_totals"] == {"1": 100.0, "3": 30.0} and r.json()["total"] == 130.0  # el total no cambia
    assert any(x["action"] == "Reasignó consumos a un comensal" and t["number"] in x["detail"] for x in client.get("/api/audit", headers=auth).json()["rows"])
    url = f"/api/tabs/{t['id']}/guest"
    assert client.post(url, json={"line_ids": [cola["id"]], "guest": 4}, headers=auth).status_code == 400  # no existe el comensal 4
    assert client.post(url, json={"line_ids": [999999], "guest": 1}, headers=auth).status_code == 400
    assert client.post(url, json={"line_ids": [], "guest": 1}, headers=auth).status_code == 422
    pay_guest(client, auth, t, 3, 30)  # ya cobrado el comensal 3: esa línea no se puede reasignar
    assert client.post(url, json={"line_ids": [cola["id"]], "guest": 1}, headers=auth).status_code == 400
    mesero = make_user(client, auth, login, "Mesero")
    t2 = client.post("/api/tabs", json={"table_ids": [rest["mesas"]["2"]], "guests": 2}, headers=mesero).json()
    add(client, mesero, t2, rest["cola"], 1)
    l2 = send(client, mesero, t2)["lines"][0]["id"]
    assert client.post(f"/api/tabs/{t2['id']}/guest", json={"line_ids": [l2], "guest": 2}, headers=mesero).status_code == 200  # el mesero sí puede
    cocina = make_user(client, auth, login, "Cocina")
    assert client.post(f"/api/tabs/{t2['id']}/guest", json={"line_ids": [l2], "guest": 1}, headers=cocina).status_code == 403


# ───────────────────────── partir un plato compartido ─────────────────────────
def test_plato_compartido_entre_tres_se_cobra_por_partes_y_descuenta_una_sola_vez(client, auth, rest):  # noqa: F811
    wh = ids(client, auth)["wh"]["id"]
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["burger"], 1)
    sent = send(client, auth, t)
    lid = sent["lines"][0]["id"]
    r = split(client, auth, t, lid, [1, 2, 3])
    assert r.status_code == 200, r.text
    lines = r.json()["lines"]
    assert [ln["total"] for ln in lines] == [33.34, 33.33, 33.33] and r.json()["total"] == 100.0  # los centavos suman justo L 100
    assert [ln["portion"] for ln in lines] == ["1/3", "1/3", "1/3"] and sum(1 for ln in lines if ln["is_part"]) == 2 and all(ln["status"] == "enviada" for ln in lines)
    assert r.json()["guests_totals"] == {"1": 33.34, "2": 33.33, "3": 33.33}
    # la cocina recibe el plato una sola vez
    kitchen = client.get("/api/kitchen?station=cocina", headers=auth).json()["comandas"]
    assert len(kitchen) == 1 and len(kitchen[0]["lines"]) == 1 and kitchen[0]["lines"][0]["qty"] == 1
    carne0, pan0 = stock(client, auth, "INS-CARNE", wh), stock(client, auth, "INS-PAN", wh)
    docs = [pay_guest(client, auth, t, g, a) for g, a in ((1, 33.34), (2, 33.33), (3, 33.33))]
    assert [d["document"]["total"] for d in docs] == [33.34, 33.33, 33.33] and docs[-1]["closed"] is True
    assert len({d["document"]["number"] for d in docs}) == 3  # una factura por comensal
    # el inventario baja lo de UN plato (carne 0.15 lb y 1 pan), con la tolerancia de redondeo de la existencia (2 decimales)
    assert abs((carne0 - stock(client, auth, "INS-CARNE", wh)) - 0.15) <= 0.02 and abs((pan0 - stock(client, auth, "INS-PAN", wh)) - 1) <= 0.02


def test_porciones_desiguales_y_estado_de_la_cuenta(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    add(client, auth, t, rest["burger"], 1)
    lid = send(client, auth, t)["lines"][0]["id"]
    r = split(client, auth, t, lid, [1, 2], weights=[1, 2])
    assert r.status_code == 200 and r.json()["guests_totals"] == {"1": 33.33, "2": 66.67}
    assert [ln["portion"] for ln in r.json()["lines"]] == ["1/3", "2/3"]


def test_validaciones_al_dividir_un_plato(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["burger"], 1)
    lid = send(client, auth, t)["lines"][0]["id"]
    assert client.post(f"/api/tabs/{t['id']}/lines/{lid}/split", json={"parts": [{"guest": 1}]}, headers=auth).status_code == 422  # al menos dos partes
    assert split(client, auth, t, lid, [1, 4]).status_code == 400  # el comensal 4 no existe
    assert split(client, auth, t, 999999, [1, 2]).status_code == 404
    assert split(client, auth, t, lid, [1, 2]).status_code == 200
    assert split(client, auth, t, lid, [1, 2]).status_code == 400  # ya está dividido: primero se juntan las partes
    # lo enviado a cocina no cambia de cantidad ni de nota (ni siquiera dividido)
    assert client.put(f"/api/tabs/{t['id']}/lines/{lid}", json={"qty": 3}, headers=auth).status_code == 400


def test_un_plato_dividido_sin_enviar_no_cambia_de_cantidad_pero_si_de_nota(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    t = add(client, auth, t, rest["burger"], 1)
    lid = t["lines"][0]["id"]
    assert split(client, auth, t, lid, [1, 2]).status_code == 200
    assert client.put(f"/api/tabs/{t['id']}/lines/{lid}", json={"qty": 3}, headers=auth).status_code == 400  # cambiaría el importe de las partes
    assert "dividido" in client.put(f"/api/tabs/{t['id']}/lines/{lid}", json={"qty": 3}, headers=auth).json()["detail"]
    assert client.put(f"/api/tabs/{t['id']}/lines/{lid}", json={"note": "sin sal"}, headers=auth).status_code == 200  # la nota para la cocina sí


def test_no_se_divide_lo_que_no_se_puede_repartir(client, auth, rest):  # noqa: F811
    barato = make_item(client, auth, "PL-CENT", "Dulce de un centavo", "platillo", rest["dep"], rest["burger"]["category_id"], price=0.01)
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, barato, 1)
    lid = send(client, auth, t)["lines"][0]["id"]
    r = split(client, auth, t, lid, [1, 2])
    assert r.status_code == 400 and "demasiado pequeño" in r.json()["detail"]
    t2 = open_tab(client, auth, rest, "2", guests=2)
    add(client, auth, t2, rest["burger"], 1)
    l2 = send(client, auth, t2)["lines"][0]["id"]
    zero = split(client, auth, t2, l2, [1, 2], weights=[1, 1000])  # L 100 entre 1 y 1000 porciones: una parte quedaría en 10 centavos, no en cero
    assert zero.status_code == 200 and min(ln["total"] for ln in zero.json()["lines"]) > 0
    pay_guest(client, auth, t2, 1, zero.json()["guests_totals"]["1"])
    paid = next(ln for ln in tab_of(client, auth, t2["id"])["lines"] if ln["status"] == "cobrada")
    assert split(client, auth, t2, paid["id"], [1, 2]).status_code == 400  # lo ya cobrado no se divide


def test_juntar_las_partes_de_un_plato(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["burger"], 1)
    lid = send(client, auth, t)["lines"][0]["id"]
    assert client.post(f"/api/tabs/{t['id']}/unsplit", json={"line_id": lid}, headers=auth).status_code == 400  # no está dividido
    split(client, auth, t, lid, [1, 2, 3])
    r = client.post(f"/api/tabs/{t['id']}/unsplit", json={"line_id": lid}, headers=auth)
    assert r.status_code == 200 and len(r.json()["lines"]) == 1 and r.json()["lines"][0]["share"] is None and r.json()["lines"][0]["total"] == 100 and r.json()["total"] == 100
    # con una parte ya cobrada no se junta
    split(client, auth, t, lid, [1, 2, 3])
    pay_guest(client, auth, t, 2, 33.33)
    assert client.post(f"/api/tabs/{t['id']}/unsplit", json={"line_id": lid}, headers=auth).status_code == 400
    assert client.post(f"/api/tabs/{t['id']}/unsplit", json={}, headers=auth).status_code == 400  # y «juntar todo» no encuentra nada que se pueda juntar


def test_anular_un_plato_dividido_lo_anula_completo_y_sale_una_vez_en_el_reporte(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, rest["burger"], 1)
    lid = send(client, auth, t)["lines"][0]["id"]
    split(client, auth, t, lid, [1, 2, 3])
    parts = tab_of(client, auth, t["id"])["lines"]
    # se anula desde una de las partes que no es la original
    child = next(ln for ln in parts if ln["is_part"])
    r = client.post(f"/api/tabs/{t['id']}/lines/{child['id']}/void", json={"reason": "El cliente se fue"}, headers=auth)
    assert r.status_code == 200 and all(ln["status"] == "anulada" for ln in r.json()["lines"]) and r.json()["total"] == 0
    rep = client.get("/api/reports/voided-lines", headers=auth).json()
    assert len(rep["rows"]) == 1 and rep["rows"][0]["amount"] == 100.0 and rep["total"] == 100.0
    # si ya se cobró una parte, se anula lo que falta (el comensal se fue sin pagar) y lo cobrado se conserva; como ya no queda nada, la cuenta se cierra sola
    t2 = open_tab(client, auth, rest, "2", guests=2)
    add(client, auth, t2, rest["burger"], 1)
    l2 = send(client, auth, t2)["lines"][0]["id"]
    split(client, auth, t2, l2, [1, 2])
    pay_guest(client, auth, t2, 1, 50)
    other = next(ln for ln in tab_of(client, auth, t2["id"])["lines"] if ln["status"] == "enviada")
    r2 = client.post(f"/api/tabs/{t2['id']}/lines/{other['id']}/void", json={"reason": "Se fueron sin pagar"}, headers=auth)
    assert r2.status_code == 200 and sorted(ln["status"] for ln in r2.json()["lines"]) == ["anulada", "cobrada"] and r2.json()["status"] == "Cerrada"
    rep = client.get("/api/reports/voided-lines", headers=auth).json()
    assert sorted(r["amount"] for r in rep["rows"]) == [50.0, 100.0] and rep["total"] == 150.0  # la parte anulada de la cuenta 2 también sale en el reporte


def test_dividir_un_plato_sin_enviar_y_quitarlo(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    t = add(client, auth, t, rest["burger"], 1)
    lid = t["lines"][0]["id"]
    assert split(client, auth, t, lid, [1, 2]).status_code == 200
    # al enviar, la comanda lleva el plato una sola vez y todas las partes quedan enviadas
    sent = client.post(f"/api/tabs/{t['id']}/send", headers=auth).json()
    assert len(sent["comandas"]) == 1 and len(sent["comandas"][0]["lines"]) == 1
    assert all(ln["status"] == "enviada" for ln in sent["tab"]["lines"]) and len(sent["tab"]["lines"]) == 2
    # sin enviar, quitar una parte quita el plato completo
    t2 = open_tab(client, auth, rest, "2", guests=2)
    t2 = add(client, auth, t2, rest["cola"], 1)
    split(client, auth, t2, t2["lines"][0]["id"], [1, 2])
    r = client.post(f"/api/tabs/{t2['id']}/lines/{t2['lines'][0]['id']}/void", json={}, headers=auth)
    assert r.status_code == 200 and r.json()["lines"] == []


def test_un_plato_dividido_viaja_completo_al_pasarlo_de_mesa(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    add(client, auth, t, rest["burger"], 1)
    lid = send(client, auth, t)["lines"][0]["id"]
    split(client, auth, t, lid, [1, 2])
    lines = tab_of(client, auth, t["id"])["lines"]
    one = client.post(f"/api/tabs/{t['id']}/transfer", json={"line_ids": [lines[0]["id"]], "to_table_id": rest["mesas"]["3"]}, headers=auth)
    assert one.status_code == 400 and "dividido" in one.json()["detail"]
    both = client.post(f"/api/tabs/{t['id']}/transfer", json={"line_ids": [ln["id"] for ln in lines], "to_table_id": rest["mesas"]["3"]}, headers=auth)
    assert both.status_code == 200 and len(both.json()["to"]["lines"]) == 2 and both.json()["to"]["total"] == 100.0


# ───────────────────────── dividir toda la cuenta en partes iguales ─────────────────────────
def test_dividir_la_cuenta_en_partes_iguales_cuadra_al_centavo(client, auth, rest):  # noqa: F811
    wh = ids(client, auth)["wh"]["id"]
    queso = rest["queso"]["id"]
    t = open_tab(client, auth, rest, guests=1)
    add(client, auth, t, rest["burger"], 1)  # L 100
    add(client, auth, t, rest["cola"], 1)  # L 30
    add(client, auth, t, rest["burger"], 1, descriptive_ids=[queso])  # L 115
    send(client, auth, t)
    r = client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 3}, headers=auth)
    assert r.status_code == 200, r.text
    tab = r.json()
    assert tab["guests"] == 3 and tab["total"] == 245.0  # el total no cambia
    g = tab["guests_totals"]
    assert round(sum(g.values()), 2) == 245.0 and max(g.values()) - min(g.values()) <= 0.02  # nadie paga más de un par de centavos de diferencia
    assert sum(1 for ln in tab["lines"] if ln["status"] == "enviada") == 9  # cada consumo en tres partes
    stock0 = {s: stock(client, auth, s, wh) for s in ("INS-CARNE", "INS-PAN", "BEB-COLA")}
    docs = [pay_guest(client, auth, t, n, g[str(n)]) for n in (1, 2, 3)]
    assert [d["document"]["total"] for d in docs] == [g["1"], g["2"], g["3"]] and docs[-1]["closed"] is True
    assert round(sum(d["document"]["total"] for d in docs), 2) == 245.0
    # inventario: 2 hamburguesas y 1 refresco en total (tolerancia del redondeo de la existencia)
    assert abs((stock0["INS-CARNE"] - stock(client, auth, "INS-CARNE", wh)) - 0.30) <= 0.03 and abs((stock0["INS-PAN"] - stock(client, auth, "INS-PAN", wh)) - 2) <= 0.04
    assert abs((stock0["BEB-COLA"] - stock(client, auth, "BEB-COLA", wh)) - 1) <= 0.02


def test_partes_iguales_validaciones_y_deshacer(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 2}, headers=auth).status_code == 400  # cuenta vacía
    add(client, auth, t, rest["burger"], 1)
    add(client, auth, t, rest["cola"], 2)
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 1}, headers=auth).status_code == 422
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 21}, headers=auth).status_code == 422
    ok = client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 4}, headers=auth)
    assert ok.status_code == 200 and ok.json()["guests"] == 4 and ok.json()["total"] == 160.0 and ok.json()["guests_totals"] == {"1": 40.0, "2": 40.0, "3": 40.0, "4": 40.0}
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 2}, headers=auth).status_code == 400  # ya está dividida
    un = client.post(f"/api/tabs/{t['id']}/unsplit", json={}, headers=auth)
    assert un.status_code == 200 and len(un.json()["lines"]) == 2 and un.json()["total"] == 160.0  # se deshace de un golpe
    assert client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 2}, headers=auth).status_code == 200


def test_un_consumo_de_centavos_se_reparte_entre_menos_comensales(client, auth, rest):  # noqa: F811
    dos = make_item(client, auth, "PL-DOSC", "Dulce de dos centavos", "platillo", rest["dep"], rest["burger"]["category_id"], price=0.02)
    t = open_tab(client, auth, rest, guests=4)
    add(client, auth, t, dos, 1)
    r = client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 4}, headers=auth)
    assert r.status_code == 200 and len(r.json()["lines"]) == 2 and r.json()["total"] == 0.02  # dos centavos entre dos, no entre cuatro


def test_las_cortesias_sin_precio_no_se_dividen_pero_si_se_asignan(client, auth, rest):  # noqa: F811
    gratis = make_item(client, auth, "PL-GRAT", "Cortesía de la casa", "platillo", rest["dep"], rest["burger"]["category_id"], price=0)
    t = open_tab(client, auth, rest, guests=3)
    add(client, auth, t, gratis, 1)
    add(client, auth, t, rest["burger"], 1)
    r = client.post(f"/api/tabs/{t['id']}/split-equal", json={"parts": 3}, headers=auth)
    assert r.status_code == 200 and sum(1 for ln in r.json()["lines"] if ln["description"] == "Cortesía de la casa") == 1


# ───────────────────────── el aviso de «listo» no se pierde si ya pagaron ─────────────────────────
def test_el_aviso_de_listo_sigue_aunque_el_comensal_ya_haya_pagado(client, auth, rest):  # noqa: F811
    t = open_tab(client, auth, rest, guests=2)
    add(client, auth, t, rest["cola"], 1)
    lid = send(client, auth, t)["lines"][0]["id"]
    client.put(f"/api/kitchen/lines/{lid}/status", json={"status": "listo"}, headers=auth)
    pay_guest(client, auth, t, 1, 30)  # pagó antes de que le llevaran el refresco
    assert len(client.get("/api/kitchen/ready", headers=auth).json()) == 1
    client.put(f"/api/kitchen/lines/{lid}/status", json={"status": "servido"}, headers=auth)
    assert client.get("/api/kitchen/ready", headers=auth).json() == []


# ───────────────────────── bases que ya existían ─────────────────────────
def test_una_base_anterior_recibe_las_columnas_nuevas_al_iniciar():
    from sqlalchemy import inspect, text
    from app import main
    with main.engine.begin() as conn:
        for col in ("share", "group_id"):
            conn.execute(text(f"ALTER TABLE tab_lines DROP COLUMN {col}"))
    assert not {"share", "group_id"} & {c["name"] for c in inspect(main.engine).get_columns("tab_lines")}
    main.add_missing_columns(main.engine)
    assert {"share", "group_id"} <= {c["name"] for c in inspect(main.engine).get_columns("tab_lines")}
