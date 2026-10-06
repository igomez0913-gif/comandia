"""Pruebas de Comandia: fiscal SAR, inventario, cobros, compras, bancos, roles y reportes."""
from datetime import timedelta

import pytest

from app.main import amount_words, clean_rtn, today_local


# ───────────────────────── utilidades ─────────────────────────
def product(client, auth, sku):
    rows = client.get(f"/api/products?q={sku}", headers=auth).json()
    return next(p for p in rows if p["sku"] == sku)


def stock(client, auth, sku, warehouse_id):
    p = product(client, auth, sku)
    return next((s["qty"] for s in p["stocks"] if s["warehouse_id"] == warehouse_id), 0)


def ids(client, auth):
    clients = client.get("/api/clients", headers=auth).json()
    whs = client.get("/api/warehouses", headers=auth).json()
    return {
        "con_rtn": next(c for c in clients if c["rtn"]),
        "final": next(c for c in clients if not c["rtn"]),
        "wh": whs[0],
        "wh2": whs[1],
    }


def line(p, qty=1, presentation=0, price=None):
    pres = p["presentations"][presentation]
    out = {"product_id": p["id"], "presentation_id": pres["id"], "qty": qty}
    if price is not None:
        out["price"] = price
    return out


def invoice(client, auth, items, kind="factura", client_key="con_rtn", **extra):
    i = ids(client, auth)
    body = {"kind": kind, "client_id": i[client_key]["id"], "warehouse_id": i["wh"]["id"], "items": items, **extra}
    return client.post("/api/documents", json=body, headers=auth)


# ───────────────────────── total en letras ─────────────────────────
@pytest.mark.parametrize("value,expected", [
    (0.5, "Cero lempiras con 50/100"),
    (1, "Un lempira con 00/100"),
    (21, "Veintiún lempiras con 00/100"),
    (31, "Treinta y un lempiras con 00/100"),
    (100, "Cien lempiras con 00/100"),
    (101.5, "Ciento un lempiras con 50/100"),
    (1001, "Mil un lempiras con 00/100"),
    (21000, "Veintiún mil lempiras con 00/100"),
    (1000000, "Un millón de lempiras con 00/100"),
    (2000000, "Dos millones de lempiras con 00/100"),
    (1000500, "Un millón quinientos lempiras con 00/100"),
    (2459.99, "Dos mil cuatrocientos cincuenta y nueve lempiras con 99/100"),
    (10810, "Diez mil ochocientos diez lempiras con 00/100"),
])
def test_total_en_letras(value, expected):
    assert amount_words(value) == expected


def test_rtn_se_normaliza_y_valida():
    assert clean_rtn("0801-9999-123456") == "08019999123456"
    assert clean_rtn("") == ""
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        clean_rtn("123")


# ───────────────────────── acceso ─────────────────────────
def test_login_y_sesion(client, login):
    assert client.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": "mala"}).status_code == 401
    assert client.get("/api/clients").status_code == 401
    h = login(client)
    assert client.get("/api/me", headers=h).json()["role"] == "Master"


def test_bloqueo_tras_intentos_fallidos(client):
    for _ in range(5):
        assert client.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": "x"}).status_code == 401
    assert client.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": "comandia123"}).status_code == 429


def test_usuarios_y_roles(client, auth, login):
    r = client.post("/api/users", json={"name": "Ana Vendedora", "email": "ana@miempresa.hn", "password": "clave123", "role": "Vendedor"}, headers=auth)
    assert r.status_code == 200
    ana = login(client, "ana@miempresa.hn", "clave123")
    # el vendedor factura y consulta, pero no administra
    assert client.get("/api/products", headers=ana).status_code == 200
    assert client.get("/api/users", headers=ana).status_code == 403
    assert client.get("/api/banks", headers=ana).status_code == 403
    assert client.get("/api/purchases", headers=ana).status_code == 403
    assert client.post("/api/cai", json={"cai": "X" * 12, "limit_date": "2099-01-01"}, headers=ana).status_code == 403
    p = product(client, auth, "CEM-050")
    assert client.delete(f"/api/products/{p['id']}", headers=ana).status_code == 403
    assert invoice(client, ana, [line(p, 1)]).status_code == 200
    # el dashboard no le muestra compras ni utilidad
    d = client.get("/api/dashboard", headers=ana).json()
    assert d["purchases"] is None and d["utility"] is None


def test_cambiar_clave_y_no_borrar_ultimo_master(client, auth, login):
    assert client.post("/api/me/password", json={"current": "mala", "new": "nueva123"}, headers=auth).status_code == 400
    assert client.post("/api/me/password", json={"current": "comandia123", "new": "nueva123"}, headers=auth).status_code == 200
    h = login(client, password="nueva123")
    me = client.get("/api/me", headers=h).json()
    assert client.delete(f"/api/users/{me['id']}", headers=h).status_code == 400
    assert client.put(f"/api/users/{me['id']}", json={"name": "Luis", "email": me["email"], "role": "Vendedor"}, headers=h).status_code == 400


# ───────────────────────── roles y permisos (v2.5) ─────────────────────────
def make_user(client, auth, login, role, name=None):
    email = f"{role.lower()}@miempresa.hn"
    r = client.post("/api/users", json={"name": name or f"Prueba {role}", "email": email, "password": "clave123", "role": role}, headers=auth)
    assert r.status_code == 200, r.text
    return login(client, email, "clave123")


def test_catalogo_de_roles(client, auth):
    data = client.get("/api/roles", headers=auth).json()
    names = [r["name"] for r in data["roles"]]
    assert names == ["Master", "Administrador", "Supervisor", "Contador", "Cajero", "Vendedor", "Bodeguero"]
    # quien administra catálogo debe poder ver costos (el formulario de producto los guarda)
    for r in data["roles"]:
        if "catalogo" in r["permissions"]:
            assert "ver_costos" in r["permissions"], r["name"]
    me = client.get("/api/me", headers=auth).json()
    assert "usuarios" in me["permissions"] and me["active"] is True


def test_cajero_factura_y_cobra_pero_no_anula_ni_cambia_precios(client, auth, login):
    caja = make_user(client, auth, login, "Cajero")
    p = product(client, auth, "CLV-200")
    r = invoice(client, caja, [line(p, 2)])
    assert r.status_code == 200, r.text
    d = r.json()
    assert client.post(f"/api/documents/{d['id']}/payments", json={"amount": 10, "method": "Efectivo"}, headers=caja).status_code == 200
    # no cambia precios ni anula ni emite notas de crédito
    assert invoice(client, caja, [line(p, 1, price=1)]).status_code == 403
    assert client.post(f"/api/documents/{d['id']}/void", headers=caja).status_code == 403
    assert invoice(client, caja, [line(p, 1)], kind="nota").status_code == 403
    # el mismo precio del catálogo sí se acepta aunque venga explícito
    assert invoice(client, caja, [line(p, 1, price=p["presentations"][0]["price"])]).status_code == 200
    # sin costos, sin bancos, sin reportes, sin usuarios
    assert client.get("/api/products", headers=caja).json()[0]["cost"] is None
    for url in ("/api/banks", "/api/purchases", "/api/users", "/api/reports", "/api/suppliers"):
        assert client.get(url, headers=caja).status_code == 403, url
    assert client.get("/api/banks/accounts", headers=caja).status_code == 200
    assert client.get("/api/dashboard", headers=caja).json()["utility"] is None


def test_vendedor_factura_pero_no_cobra(client, auth, login):
    ven = make_user(client, auth, login, "Vendedor")
    p = product(client, auth, "CLV-200")
    d = invoice(client, ven, [line(p, 2)]).json()
    assert client.post(f"/api/documents/{d['id']}/payments", json={"amount": 10, "method": "Efectivo"}, headers=ven).status_code == 403
    assert client.get("/api/banks/accounts", headers=ven).status_code == 403
    assert invoice(client, ven, [line(p, 1)], kind="cotizacion").status_code == 200


def test_bodeguero_solo_inventario(client, auth, login):
    bod = make_user(client, auth, login, "Bodeguero")
    i = ids(client, auth)
    p = product(client, auth, "CLV-200")
    assert client.get("/api/products", headers=bod).status_code == 200
    r = client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": i["wh"]["id"], "qty": 5, "concept": "conteo"}, headers=bod)
    assert r.status_code == 200, r.text
    r = client.post("/api/stock/transfer", json={"product_id": p["id"], "from_warehouse_id": i["wh"]["id"], "to_warehouse_id": i["wh2"]["id"], "qty": 1}, headers=bod)
    assert r.status_code == 200, r.text
    assert invoice(client, bod, [line(p, 1)]).status_code == 403
    assert invoice(client, bod, [line(p, 1)], kind="cotizacion").status_code == 403
    assert client.post("/api/products", json={}, headers=bod).status_code == 403
    assert client.get("/api/products", headers=bod).json()[0]["cost"] is None


def test_contador_ve_libros_y_bancos_pero_no_vende(client, auth, login):
    con = make_user(client, auth, login, "Contador")
    p = product(client, auth, "CLV-200")
    assert client.get("/api/reports?period=all", headers=con).status_code == 200
    assert client.get("/api/reports/libro-ventas.csv?period=all", headers=con).status_code == 200
    assert client.get("/api/banks", headers=con).status_code == 200
    assert client.get("/api/purchases", headers=con).status_code == 200
    assert client.get("/api/products", headers=con).json()[0]["cost"] is not None
    assert invoice(client, con, [line(p, 1)]).status_code == 403
    assert client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": 1, "qty": 1, "concept": "x"}, headers=con).status_code == 403
    assert client.put("/api/settings", json={"name": "X", "rtn": "08019999123456"}, headers=con).status_code == 403


def test_supervisor_anula_y_cambia_precios_pero_no_configura(client, auth, login):
    sup = make_user(client, auth, login, "Supervisor")
    p = product(client, auth, "CLV-200")
    d = invoice(client, sup, [line(p, 1, price=1)])
    assert d.status_code == 200, d.text
    assert client.post(f"/api/documents/{d.json()['id']}/void", headers=sup).status_code == 200
    assert client.get("/api/banks", headers=sup).status_code == 403
    assert client.get("/api/users", headers=sup).status_code == 403
    assert client.post("/api/cai", json={"cai": "X" * 12, "limit_date": "2099-01-01"}, headers=sup).status_code == 403


def test_administrador_no_toca_a_un_master(client, auth, login):
    adm = make_user(client, auth, login, "Administrador")
    users = client.get("/api/users", headers=adm).json()
    luis = next(u for u in users if u["role"] == "Master")
    body = {"name": "Luis", "email": luis["email"], "role": "Administrador"}
    assert client.put(f"/api/users/{luis['id']}", json=body, headers=adm).status_code == 403
    assert client.put(f"/api/users/{luis['id']}", json={**body, "password": "hackeada1", "role": "Master"}, headers=adm).status_code == 403
    assert client.delete(f"/api/users/{luis['id']}", headers=adm).status_code == 403
    assert client.post("/api/users", json={"name": "Otro Master", "email": "m2@miempresa.hn", "password": "clave123", "role": "Master"}, headers=adm).status_code == 403
    # el administrador sí crea cajeros y nadie puede cambiarse su propio rol
    assert client.post("/api/users", json={"name": "Una Cajera", "email": "c@miempresa.hn", "password": "clave123", "role": "Cajero"}, headers=adm).status_code == 200
    me = next(u for u in users if u["role"] == "Administrador")
    assert client.put(f"/api/users/{me['id']}", json={"name": me["name"], "email": me["email"], "role": "Master"}, headers=adm).status_code == 403
    assert client.put(f"/api/users/{me['id']}", json={"name": me["name"], "email": me["email"], "role": "Supervisor"}, headers=adm).status_code == 400


def test_master_crea_master_y_protege_al_ultimo(client, auth, login):
    assert client.post("/api/users", json={"name": "Segundo Master", "email": "m2@miempresa.hn", "password": "clave123", "role": "Master"}, headers=auth).status_code == 200
    m2 = login(client, "m2@miempresa.hn", "clave123")
    luis = next(u for u in client.get("/api/users", headers=m2).json() if u["email"] == "luis@miempresa.hn")
    # con dos Master, uno puede pasar al otro a Administrador
    assert client.put(f"/api/users/{luis['id']}", json={"name": luis["name"], "email": luis["email"], "role": "Administrador"}, headers=m2).status_code == 200
    # ya queda un solo Master: no se puede borrar ni desactivar
    yo = next(u for u in client.get("/api/users", headers=m2).json() if u["email"] == "m2@miempresa.hn")
    assert client.delete(f"/api/users/{yo['id']}", headers=m2).status_code == 400


def test_usuario_desactivado_no_entra_ni_sigue_con_su_token(client, auth, login):
    caja = make_user(client, auth, login, "Cajero")
    cu = next(u for u in client.get("/api/users", headers=auth).json() if u["role"] == "Cajero")
    assert client.get("/api/clients", headers=caja).status_code == 200
    r = client.put(f"/api/users/{cu['id']}", json={"name": cu["name"], "email": cu["email"], "role": "Cajero", "active": False}, headers=auth)
    assert r.status_code == 200
    assert client.get("/api/clients", headers=caja).status_code == 401  # el token ya no sirve
    assert client.post("/api/auth/login", json={"email": cu["email"], "password": "clave123"}).status_code == 403
    client.put(f"/api/users/{cu['id']}", json={"name": cu["name"], "email": cu["email"], "role": "Cajero", "active": True}, headers=auth)
    assert client.post("/api/auth/login", json={"email": cu["email"], "password": "clave123"}).status_code == 200
    # nadie se desactiva a sí mismo
    me = client.get("/api/me", headers=auth).json()
    assert client.put(f"/api/users/{me['id']}", json={"name": me["name"], "email": me["email"], "role": "Master", "active": False}, headers=auth).status_code == 400


def test_rol_invalido_y_migracion_de_bases_viejas(client, auth):
    assert client.post("/api/users", json={"name": "Raro Rol", "email": "r@miempresa.hn", "password": "clave123", "role": "Dios"}, headers=auth).status_code == 400
    from app.main import SessionLocal, User, migrate_users
    db = SessionLocal()
    try:
        for u in db.query(User).all():
            u.role, u.active = "Administrador", None  # como quedaba una base de la v2.4
        db.commit()
        migrate_users(db)
        users = db.query(User).all()
        assert [u.role for u in users] == ["Master"] and users[0].active == 1
    finally:
        db.close()


# ───────────────────────── facturación SAR ─────────────────────────
def test_factura_numero_isv_y_stock(client, auth):
    i = ids(client, auth)
    cem = product(client, auth, "CEM-050")
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    tarima = next(x for x in cem["presentations"] if x["factor"] == 40)
    r = invoice(client, auth, [{"product_id": cem["id"], "presentation_id": tarima["id"], "qty": 1}])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["number"] == "001-001-01-00002459"
    assert d["gravado_15"] == 9400 and d["isv_15"] == 1410 and d["total"] == 10810
    assert d["amount_words"] == "Diez mil ochocientos diez lempiras con 00/100"
    assert d["cai"] and d["limit_date"] and "001-001-01-" in d["range_label"]
    # la tarima descuenta su factor (40 sacos) de la bodega elegida
    assert before - stock(client, auth, "CEM-050", i["wh"]["id"]) == 40


def test_correlativo_avanza_sin_saltos(client, auth):
    p = product(client, auth, "CLV-200")
    a = invoice(client, auth, [line(p)]).json()["number"]
    b = invoice(client, auth, [line(p)]).json()["number"]
    assert int(b[-8:]) == int(a[-8:]) + 1


def test_consumidor_final_sin_rtn_por_cualquier_monto(client, auth):
    cem = product(client, auth, "CEM-050")
    r = invoice(client, auth, [line(cem, 10)], client_key="final")  # L 2,817.50 sin RTN
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2817.5 and r.json()["rtn"] == ""


def test_stock_insuficiente_no_consume_correlativo(client, auth):
    cem = product(client, auth, "CEM-050")
    antes = client.get("/api/settings", headers=auth).json()["cai"]
    cai01 = next(c for c in antes if c["doc_type"] == "01")["current"]
    r = invoice(client, auth, [line(cem, 99999)])
    assert r.status_code == 400
    despues = client.get("/api/settings", headers=auth).json()["cai"]
    assert next(c for c in despues if c["doc_type"] == "01")["current"] == cai01


@pytest.mark.parametrize("qty", [0, -5])
def test_cantidad_invalida_rechazada(client, auth, qty):
    cem = product(client, auth, "CEM-050")
    assert invoice(client, auth, [line(cem, qty)]).status_code == 422


def test_el_factor_no_se_toma_del_cliente(client, auth):
    """Un cliente malicioso no puede mandar factor=0.001 para descontar casi nada."""
    i = ids(client, auth)
    cem = product(client, auth, "CEM-050")
    tarima = next(x for x in cem["presentations"] if x["factor"] == 40)
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    r = invoice(client, auth, [{"product_id": cem["id"], "presentation_id": tarima["id"], "qty": 1, "factor": 0.001}])
    assert r.status_code == 200
    assert before - stock(client, auth, "CEM-050", i["wh"]["id"]) == 40


def test_presentacion_de_otro_producto_rechazada(client, auth):
    cem, clavo = product(client, auth, "CEM-050"), product(client, auth, "CLV-200")
    r = invoice(client, auth, [{"product_id": cem["id"], "presentation_id": clavo["presentations"][0]["id"], "qty": 1}])
    assert r.status_code == 400


def test_isv_18_exento_y_exonerado_separados(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    items = [
        {**line(p, 1, price=100), "tax_treatment": "gravado15"},
        {**line(p, 1, price=100), "tax_treatment": "gravado18"},
        {**line(p, 1, price=100), "tax_treatment": "exento"},
        {**line(p, 1, price=100), "tax_treatment": "exonerado"},
    ]
    d = invoice(client, auth, items).json()
    assert (d["gravado_15"], d["isv_15"], d["gravado_18"], d["isv_18"], d["exento"], d["exonerado"]) == (100, 15, 100, 18, 100, 100)
    assert d["total"] == 433 and d["tax"] == 33


def test_nota_de_credito_tipo_06_devuelve_stock(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    r = invoice(client, auth, [line(p, 3)], kind="nota")
    assert r.status_code == 200, r.text
    d = r.json()
    assert "-06-" in d["number"] and d["status"] == "Procesada"
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) - before == 3


def test_cai_vencido_bloquea_y_uno_nuevo_vigente_se_usa(client, auth):
    from app.main import CaiRange, SessionLocal
    db = SessionLocal()
    for c in db.query(CaiRange).filter(CaiRange.doc_type == "01"):
        c.limit_date = today_local() - timedelta(days=1)
    db.commit()
    db.close()
    p = product(client, auth, "CLV-200")
    r = invoice(client, auth, [line(p)])
    assert r.status_code == 400 and "venció" in r.json()["detail"]
    nuevo = {"cai": "N1N2N3-N4N5N6-N7N8N9-N0N1N2-N3N4N5", "doc_type": "01", "range_from": 5000, "range_to": 5010,
             "limit_date": (today_local() + timedelta(days=90)).isoformat()}
    assert client.post("/api/cai", json=nuevo, headers=auth).status_code == 200
    d = invoice(client, auth, [line(p)]).json()
    assert d["number"] == "001-001-01-00005000"


def test_rango_agotado_bloquea(client, auth):
    cai = {"cai": "R1R2R3-R4R5R6-R7R8R9-R0R1R2-R3R4R5", "doc_type": "01", "range_from": 1, "range_to": 2,
           "limit_date": (today_local() + timedelta(days=30)).isoformat()}
    from app.main import CaiRange, SessionLocal
    db = SessionLocal()
    for c in db.query(CaiRange).filter(CaiRange.doc_type == "01"):
        c.active = 0
    db.commit()
    db.close()
    assert client.post("/api/cai", json=cai, headers=auth).status_code == 200
    p = product(client, auth, "CLV-200")
    n1 = invoice(client, auth, [line(p)]).json()["number"]
    n2 = invoice(client, auth, [line(p)]).json()["number"]
    assert n1.endswith("00000001") and n2.endswith("00000002")
    assert invoice(client, auth, [line(p)]).status_code == 400


def test_cai_no_acepta_fecha_vencida_ni_rango_invertido(client, auth):
    base = {"cai": "C1C2C3-C4C5C6-C7C8C9-C0C1C2-C3C4C5", "doc_type": "01"}
    assert client.post("/api/cai", json={**base, "limit_date": "2000-01-01"}, headers=auth).status_code == 400
    assert client.post("/api/cai", json={**base, "range_from": 10, "range_to": 5, "limit_date": "2099-01-01"}, headers=auth).status_code == 400


def test_serie_e_usa_su_propio_talonario_y_no_gasta_correlativo_normal(client, auth):
    cai01 = next(c for c in client.get("/api/settings", headers=auth).json()["cai"] if c["doc_type"] == "01")
    series = client.get("/api/series", headers=auth).json()
    serie_e = next(s for s in series if s["code"] == "E")
    p = product(client, auth, "CLV-200")
    d = invoice(client, auth, [line(p)], series_id=serie_e["id"]).json()
    assert d["number"] == "001-001-01-E00000001" and d["series"] == "E"
    d2 = invoice(client, auth, [line(p)], series_id=serie_e["id"]).json()
    assert d2["number"].endswith("E00000002")
    after = next(c for c in client.get("/api/settings", headers=auth).json()["cai"] if c["doc_type"] == "01")
    assert after["current"] == cai01["current"]
    normal = invoice(client, auth, [line(p)]).json()
    assert normal["number"] == "001-001-01-00002459" and normal["series"] == "Normal"


# ───────────────────────── cobros y cuentas por cobrar ─────────────────────────
def test_cobrar_no_cambia_el_numero_fiscal(client, auth):
    p = product(client, auth, "CEM-050")
    d = invoice(client, auth, [line(p, 2)]).json()
    r = client.post(f"/api/documents/{d['id']}/payments", json={"amount": d["total"], "method": "Efectivo"}, headers=auth)
    assert r.status_code == 200, r.text
    paid = r.json()
    assert paid["number"] == d["number"] and paid["status"] == "Pagada" and paid["balance"] == 0
    assert client.post(f"/api/documents/{d['id']}/payments", json={"amount": 1}, headers=auth).status_code == 400


def test_abonos_parciales_y_saldo(client, auth):
    p = product(client, auth, "CEM-050")
    d = invoice(client, auth, [line(p, 2)]).json()  # 2 x 245 + ISV = 563.50
    r1 = client.post(f"/api/documents/{d['id']}/payments", json={"amount": 200}, headers=auth).json()
    assert r1["status"] == "Parcial" and r1["paid"] == 200 and r1["balance"] == round(d["total"] - 200, 2)
    assert client.post(f"/api/documents/{d['id']}/payments", json={"amount": 99999}, headers=auth).status_code == 400
    r2 = client.post(f"/api/documents/{d['id']}/payments", json={"amount": r1["balance"]}, headers=auth).json()
    assert r2["status"] == "Pagada" and len(r2["payments"]) == 2
    cxc = client.get("/api/reports/cxc.csv", headers=auth).text
    assert d["number"] not in cxc


def test_cobro_a_banco_suma_al_saldo(client, auth):
    banks = client.get("/api/banks", headers=auth).json()["banks"]
    banco = banks[0]
    p = product(client, auth, "CEM-050")
    d = invoice(client, auth, [line(p, 1)]).json()
    client.post(f"/api/documents/{d['id']}/payments", json={"amount": d["total"], "bank_id": banco["id"], "method": "Transferencia"}, headers=auth)
    after = next(b for b in client.get("/api/banks", headers=auth).json()["banks"] if b["id"] == banco["id"])
    assert after["balance"] == round(banco["balance"] + d["total"], 2)


def test_no_se_cobra_cotizacion_ni_nota(client, auth):
    p = product(client, auth, "CEM-050")
    q = invoice(client, auth, [line(p)], kind="cotizacion").json()
    assert client.post(f"/api/documents/{q['id']}/payments", json={"amount": 10}, headers=auth).status_code == 400
    n = invoice(client, auth, [line(p)], kind="nota").json()
    assert client.post(f"/api/documents/{n['id']}/payments", json={"amount": 10}, headers=auth).status_code == 400


def test_factura_vence_sola(client, auth):
    p = product(client, auth, "CEM-050")
    d = invoice(client, auth, [line(p)], due_date=(today_local() - timedelta(days=3)).isoformat()).json()
    assert d["status"] == "Vencida"
    vencidas = client.get("/api/documents?kind=factura&status=Vencida", headers=auth).json()
    assert d["id"] in [x["id"] for x in vencidas]


# ───────────────────────── cotizaciones ─────────────────────────
def test_cotizacion_no_mueve_stock_y_se_factura(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    q = invoice(client, auth, [line(p, 2)], kind="cotizacion").json()
    assert q["number"].startswith("CT-") and q["cai"] == ""
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) == before
    f = client.post(f"/api/documents/{q['id']}/invoice", headers=auth)
    assert f.status_code == 200, f.text
    inv = f.json()
    assert inv["kind"] == "factura" and inv["client_ref"] == q["number"]
    assert before - stock(client, auth, "CEM-050", i["wh"]["id"]) == 2
    assert client.post(f"/api/documents/{q['id']}/invoice", headers=auth).status_code == 400  # no se factura dos veces


def test_numeracion_de_cotizaciones_continua_la_de_demo(client, auth):
    p = product(client, auth, "CEM-050")
    assert invoice(client, auth, [line(p)], kind="cotizacion").json()["number"] == "CT-000092"
    assert invoice(client, auth, [line(p)], kind="cotizacion").json()["number"] == "CT-000093"


# ───────────────────────── anulaciones ─────────────────────────
def test_anular_factura_devuelve_stock_y_conserva_numero(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    d = invoice(client, auth, [line(p, 5)]).json()
    mid = stock(client, auth, "CEM-050", i["wh"]["id"])
    r = client.post(f"/api/documents/{d['id']}/void", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "Anulada" and r.json()["number"] == d["number"]
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) - mid == 5
    assert client.post(f"/api/documents/{d['id']}/void", headers=auth).status_code == 400


def test_no_se_anula_factura_con_cobros(client, auth):
    p = product(client, auth, "CEM-050")
    d = invoice(client, auth, [line(p)]).json()
    client.post(f"/api/documents/{d['id']}/payments", json={"amount": 10}, headers=auth)
    assert client.post(f"/api/documents/{d['id']}/void", headers=auth).status_code == 400


def test_estado_manual_solo_para_cotizaciones(client, auth):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p)]).json()
    assert client.post(f"/api/documents/{f['id']}/status?status=Pagada", headers=auth).status_code == 400
    q = invoice(client, auth, [line(p)], kind="cotizacion").json()
    assert client.post(f"/api/documents/{q['id']}/status?status=Orden%20de%20venta", headers=auth).status_code == 200


# ───────────────────────── inventario ─────────────────────────
def test_traslado_entre_bodegas(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    a0, b0 = stock(client, auth, "CEM-050", i["wh"]["id"]), stock(client, auth, "CEM-050", i["wh2"]["id"])
    body = {"product_id": p["id"], "from_warehouse_id": i["wh"]["id"], "to_warehouse_id": i["wh2"]["id"], "qty": 10}
    assert client.post("/api/stock/transfer", json=body, headers=auth).status_code == 200
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) == a0 - 10 and stock(client, auth, "CEM-050", i["wh2"]["id"]) == b0 + 10
    assert client.post("/api/stock/transfer", json={**body, "qty": 99999}, headers=auth).status_code == 400
    assert client.post("/api/stock/transfer", json={**body, "to_warehouse_id": i["wh"]["id"]}, headers=auth).status_code == 400


def test_ajuste_manual_y_kardex(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    r = client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": i["wh"]["id"], "qty": -7, "concept": "Merma por humedad"}, headers=auth)
    assert r.status_code == 200 and r.json()["stock"] == before - 7
    assert client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": i["wh"]["id"], "qty": -99999, "concept": "Imposible"}, headers=auth).status_code == 400
    assert client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": i["wh"]["id"], "qty": 0, "concept": "Nada"}, headers=auth).status_code == 400
    moves = client.get(f"/api/stock/moves?product_id={p['id']}", headers=auth).json()
    assert moves[0]["concept"] == "Ajuste: Merma por humedad" and moves[0]["qty"] == -7
    invoice(client, auth, [line(p, 1)])
    moves = client.get(f"/api/stock/moves?product_id={p['id']}", headers=auth).json()
    assert moves[0]["concept"].startswith("Factura 001-001-01-")


# ───────────────────────── compras ─────────────────────────
def test_compra_con_items_ingresa_inventario_y_actualiza_costo(client, auth):
    i = ids(client, auth)
    sup = client.get("/api/suppliers", headers=auth).json()[0]
    p = product(client, auth, "CEM-050")
    tarima = next(x for x in p["presentations"] if x["factor"] == 40)
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    body = {"supplier_id": sup["id"], "warehouse_id": i["wh"]["id"], "cai_supplier": "CAI-PROV-1",
            "items": [{"product_id": p["id"], "presentation_id": tarima["id"], "qty": 2, "unit_cost": 7000}]}
    r = client.post("/api/purchases", json=body, headers=auth)
    assert r.status_code == 200, r.text
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) - before == 80  # 2 tarimas x 40 sacos
    compra = client.get(f"/api/purchases/{r.json()['id']}", headers=auth).json()
    assert compra["gravado"] == 14000 and compra["isv"] == 2100 and compra["total"] == 16100
    assert product(client, auth, "CEM-050")["cost"] == 175  # 7000 / 40 sacos


def test_orden_pendiente_se_recibe_despues_y_se_anula(client, auth):
    i = ids(client, auth)
    sup = client.get("/api/suppliers", headers=auth).json()[0]
    p = product(client, auth, "CLV-200")
    before = stock(client, auth, "CLV-200", i["wh"]["id"])
    body = {"supplier_id": sup["id"], "warehouse_id": i["wh"]["id"], "status": "Pendiente",
            "items": [{"product_id": p["id"], "presentation_id": p["presentations"][1]["id"], "qty": 4, "unit_cost": 400}]}
    pid = client.post("/api/purchases", json=body, headers=auth).json()["id"]
    assert stock(client, auth, "CLV-200", i["wh"]["id"]) == before  # aún no entra
    assert client.post(f"/api/purchases/{pid}/receive", headers=auth).status_code == 200
    assert stock(client, auth, "CLV-200", i["wh"]["id"]) - before == 100  # 4 cajas x 25 lb
    assert client.post(f"/api/purchases/{pid}/receive", headers=auth).status_code == 400
    assert client.post(f"/api/purchases/{pid}/void", headers=auth).status_code == 200
    assert stock(client, auth, "CLV-200", i["wh"]["id"]) == before


def test_compra_manual_sin_items_requiere_total(client, auth):
    i = ids(client, auth)
    sup = client.get("/api/suppliers", headers=auth).json()[0]
    base = {"supplier_id": sup["id"], "warehouse_id": i["wh"]["id"]}
    assert client.post("/api/purchases", json=base, headers=auth).status_code == 400
    ok = client.post("/api/purchases", json={**base, "total": 1000, "gravado": 869.57, "isv": 130.43}, headers=auth)
    assert ok.status_code == 200 and ok.json()["number"].startswith("OC-")


# ───────────────────────── bancos ─────────────────────────
def test_banco_no_permite_egreso_mayor_al_saldo(client, auth):
    caja = client.get("/api/banks", headers=auth).json()["banks"][2]
    r = client.post("/api/banks/moves", json={"bank_id": caja["id"], "kind": "egreso", "concept": "Pago", "amount": caja["balance"] + 1}, headers=auth)
    assert r.status_code == 400
    r = client.post("/api/banks/moves", json={"bank_id": caja["id"], "kind": "egreso", "concept": "Pago", "amount": 40}, headers=auth)
    assert r.status_code == 200 and r.json()["balance"] == caja["balance"] - 40
    assert client.post("/api/banks/moves", json={"bank_id": caja["id"], "kind": "otro", "concept": "x", "amount": 1}, headers=auth).status_code == 400
    assert client.post("/api/banks/moves", json={"bank_id": caja["id"], "kind": "ingreso", "concept": "x", "amount": -5}, headers=auth).status_code == 422


# ───────────────────────── catálogos ─────────────────────────
def test_editar_y_borrar_clientes(client, auth):
    c = client.post("/api/clients", json={"name": "Ferretería Prueba", "rtn": "0801-2000-123456"}, headers=auth)
    assert c.status_code == 200
    cid = c.json()["id"]
    assert client.post("/api/clients", json={"name": "Duplicado", "rtn": "08012000123456"}, headers=auth).status_code == 400
    assert client.post("/api/clients", json={"name": "Mal RTN", "rtn": "123"}, headers=auth).status_code == 400
    assert client.put(f"/api/clients/{cid}", json={"name": "Ferretería Prueba S.A.", "rtn": "08012000123456", "phone": "9999-0000"}, headers=auth).status_code == 200
    assert next(x for x in client.get("/api/clients", headers=auth).json() if x["id"] == cid)["phone"] == "9999-0000"
    assert client.delete(f"/api/clients/{cid}", headers=auth).status_code == 200
    con_docs = ids(client, auth)["con_rtn"]
    p = product(client, auth, "CEM-050")
    invoice(client, auth, [line(p)])
    assert client.delete(f"/api/clients/{con_docs['id']}", headers=auth).status_code == 400


def test_editar_producto_y_proteger_los_usados(client, auth):
    cats = client.get("/api/departments", headers=auth).json()
    dep = cats["departments"][0]
    cat = dep["categories"][0]
    body = {"sku": "NUEVO-1", "name": "Producto nuevo", "department_id": dep["id"], "category_id": cat["id"], "base_unit": "und", "cost": 10, "price": 20,
            "presentations": [{"name": "Unidad", "unit": "und", "factor": 1, "price": 20}, {"name": "Caja 10", "unit": "caja", "factor": 10, "price": 180}]}
    r = client.post("/api/products", json=body, headers=auth)
    assert r.status_code == 200, r.text
    assert client.post("/api/products", json=body, headers=auth).status_code == 400  # SKU repetido
    pid = r.json()["id"]
    prod = product(client, auth, "NUEVO-1")
    upd = {**body, "name": "Producto renombrado", "price": 25, "presentations": [{"id": x["id"], "name": x["name"], "unit": x["unit"], "factor": x["factor"], "price": x["price"] + 5} for x in prod["presentations"]]}
    assert client.put(f"/api/products/{pid}", json=upd, headers=auth).status_code == 200
    after = product(client, auth, "NUEVO-1")
    assert after["name"] == "Producto renombrado" and after["presentations"][0]["price"] == 25
    # categoría de otro departamento
    otra = next(c for c in cats["categories"] if c["department_id"] != dep["id"])
    assert client.put(f"/api/products/{pid}", json={**upd, "category_id": otra["id"]}, headers=auth).status_code == 400
    # un producto vendido no se elimina ni cambia el factor ya usado
    cem = product(client, auth, "CEM-050")
    invoice(client, auth, [line(cem, 1, presentation=1)])
    assert client.delete(f"/api/products/{cem['id']}", headers=auth).status_code == 400
    pres = {x["id"]: x for x in cem["presentations"]}
    bad = {"sku": cem["sku"], "name": cem["name"], "department_id": cem["department_id"], "category_id": cem["category_id"], "base_unit": cem["base_unit"],
           "presentations": [{"id": cem["presentations"][1]["id"], "name": "Tarima", "unit": "tarima", "factor": 50, "price": 9400}]}
    assert client.put(f"/api/products/{cem['id']}", json=bad, headers=auth).status_code == 400
    assert client.delete(f"/api/products/{pid}", headers=auth).status_code == 200


def test_bodegas_departamentos_y_categorias(client, auth):
    w = client.post("/api/warehouses", json={"code": "nor", "name": "Bodega Norte"}, headers=auth)
    assert w.status_code == 200
    assert client.post("/api/warehouses", json={"code": "NOR", "name": "Otra"}, headers=auth).status_code == 400
    assert client.delete(f"/api/warehouses/{w.json()['id']}", headers=auth).status_code == 200
    assert "Bodega Norte" not in [x["name"] for x in client.get("/api/warehouses", headers=auth).json()]
    full = ids(client, auth)["wh"]
    assert client.delete(f"/api/warehouses/{full['id']}", headers=auth).status_code == 400  # tiene existencias
    d = client.post("/api/departments", json={"name": "Jardinería"}, headers=auth).json()["id"]
    c = client.post("/api/categories", json={"name": "Mangueras", "department_id": d}, headers=auth).json()["id"]
    assert client.delete(f"/api/departments/{d}", headers=auth).status_code == 400
    assert client.delete(f"/api/categories/{c}", headers=auth).status_code == 200
    assert client.delete(f"/api/departments/{d}", headers=auth).status_code == 200


# ───────────────────────── dashboard y reportes ─────────────────────────
def test_dashboard_calcula_variaciones_reales(client, auth):
    d = client.get("/api/dashboard?period=month", headers=auth).json()
    assert d["sales_delta"] != 12.5  # antes estaba fijo
    assert d["months"] and len(d["months"]) == 6
    assert d["cai"]["days_left"] > 0
    assert client.get("/api/dashboard?period=all", headers=auth).json()["sales_delta"] is None


def test_ventas_netas_restan_notas_de_credito(client, auth):
    antes = client.get("/api/dashboard?period=year", headers=auth).json()["sales"]
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 2)]).json()
    n = invoice(client, auth, [line(p, 1)], kind="nota").json()
    despues = client.get("/api/dashboard?period=year", headers=auth).json()["sales"]
    assert round(despues - antes, 2) == round(f["total"] - n["total"], 2)


def test_libros_sar_csv(client, auth):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p)]).json()
    anulada = invoice(client, auth, [line(p)]).json()
    client.post(f"/api/documents/{anulada['id']}/void", headers=auth)
    r = client.get("/api/reports/libro-ventas.csv?period=all", headers=auth)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    text = r.content.decode("utf-8-sig")
    assert text.splitlines()[0].startswith("Fecha,Tipo,Número,CAI")
    assert f["number"] in text and anulada["number"] in text  # la anulada también figura en el libro
    assert [l for l in text.splitlines() if anulada["number"] in l][0].endswith("Anulada")
    assert client.get("/api/reports/libro-compras.csv?period=all", headers=auth).status_code == 200
    inv = client.get("/api/reports/inventario.csv", headers=auth).content.decode("utf-8-sig")
    assert "CEM-050" in inv and "Valor al costo" in inv


def test_reporte_resumen(client, auth):
    r = client.get("/api/reports?period=all", headers=auth).json()
    assert r["libro_ventas"]["total"] > 0 and r["inventory_value"] > 0 and r["libro_compras"]["total"] > 0


# ───────────────────────── configuración ─────────────────────────
def test_configuracion_valida_rtn_y_logo(client, auth):
    cfg = client.get("/api/settings", headers=auth).json()
    body = {"name": cfg["name"], "legal_name": cfg["legal_name"], "rtn": "123", "address": "x", "phone": "x", "email": "x@x.hn"}
    assert client.put("/api/settings", json=body, headers=auth).status_code == 400
    assert client.put("/api/settings", json={**body, "rtn": "0801-9999-123456"}, headers=auth).status_code == 200
    bad = client.post("/api/settings/logo", files={"file": ("logo.png", b"no soy una imagen", "image/png")}, headers=auth)
    assert bad.status_code == 400
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    ok = client.post("/api/settings/logo", files={"file": ("logo.png", png, "image/png")}, headers=auth)
    assert ok.status_code == 200 and ok.json()["logo"].startswith("/static/uploads/logo.png")


def test_busqueda_global(client, auth):
    r = client.get("/api/search?q=cemento", headers=auth).json()
    assert any("Cemento" in x["name"] for x in r["products"])
