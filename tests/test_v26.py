"""Pruebas de la v2.6: notas de crédito ligadas a la factura, bitácora y cierre de caja."""
from test_api import ids, invoice, line, make_user, product, stock


def nota(client, auth, factura, items, **extra):
    return invoice(client, auth, items, kind="nota", ref_document_id=factura["id"], **extra)


# ───────────────────────── notas de crédito ligadas a la factura ─────────────────────────
def test_nota_ligada_rebaja_saldo_y_referencia_la_factura(client, auth):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 4)]).json()  # 4 × 245 + ISV = 1 127.00
    r = nota(client, auth, f, [line(p, 1)])
    assert r.status_code == 200, r.text
    n = r.json()
    assert n["ref_document_id"] == f["id"] and n["ref_number"] == f["number"] and n["client_ref"] == f["number"]
    inv = client.get(f"/api/documents/{f['id']}", headers=auth).json()["document"]
    assert inv["credited"] == 281.75 and inv["balance"] == round(1127 - 281.75, 2)
    assert inv["status"] == "Parcial" and inv["credit_notes"][0]["number"] == n["number"]
    # el cobro ya no puede pasar del saldo neto
    over = client.post(f"/api/documents/{f['id']}/payments", json={"amount": 1127}, headers=auth)
    assert over.status_code == 400
    ok = client.post(f"/api/documents/{f['id']}/payments", json={"amount": inv["balance"]}, headers=auth)
    assert ok.status_code == 200 and ok.json()["status"] == "Pagada"


def test_nota_total_deja_la_factura_acreditada(client, auth):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 2)]).json()
    assert nota(client, auth, f, [line(p, 2)]).status_code == 200
    inv = client.get(f"/api/documents/{f['id']}", headers=auth).json()["document"]
    assert inv["status"] == "Acreditada" and inv["balance"] == 0
    assert client.post(f"/api/documents/{f['id']}/payments", json={"amount": 1}, headers=auth).status_code == 400
    # ya no figura en cuentas por cobrar
    assert f["number"] not in client.get("/api/reports/cxc.csv", headers=auth).content.decode("utf-8-sig")


def test_nota_no_acredita_mas_de_lo_facturado(client, auth):
    p = product(client, auth, "CEM-050")
    otro = product(client, auth, "CLV-200")
    f = invoice(client, auth, [line(p, 3)]).json()
    assert nota(client, auth, f, [line(p, 2)]).status_code == 200
    r = nota(client, auth, f, [line(p, 2)])  # solo queda 1 saco
    assert r.status_code == 400 and "solo quedan 1" in r.json()["detail"]
    r = nota(client, auth, f, [line(otro, 1)])
    assert r.status_code == 400 and "no está en la factura" in r.json()["detail"]
    # una tarima son 40 sacos: también se controla por unidades base
    assert nota(client, auth, f, [line(p, 1, presentation=1)]).status_code == 400


def test_nota_valida_cliente_y_factura_anulada(client, auth):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 1)]).json()
    i = ids(client, auth)
    r = nota(client, auth, f, [line(p, 1)], client_id=i["final"]["id"])
    assert r.status_code == 400 and "mismo cliente" in r.json()["detail"]
    client.post(f"/api/documents/{f['id']}/void", headers=auth)
    r = nota(client, auth, f, [line(p, 1)])
    assert r.status_code == 400 and "anulada" in r.json()["detail"]


def test_anular_nota_restituye_saldo_y_factura_con_notas_no_se_anula(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    before = stock(client, auth, "CEM-050", i["wh"]["id"])
    f = invoice(client, auth, [line(p, 2)]).json()
    n = nota(client, auth, f, [line(p, 2)]).json()
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) == before  # salió y regresó
    r = client.post(f"/api/documents/{f['id']}/void", headers=auth)
    assert r.status_code == 400 and "notas de crédito" in r.json()["detail"]
    assert client.post(f"/api/documents/{n['id']}/void", headers=auth).status_code == 200
    inv = client.get(f"/api/documents/{f['id']}", headers=auth).json()["document"]
    assert inv["status"] == "Pendiente" and inv["balance"] == f["total"] and inv["credited"] == 0
    assert stock(client, auth, "CEM-050", i["wh"]["id"]) == before - 2
    assert client.post(f"/api/documents/{f['id']}/void", headers=auth).status_code == 200


def test_libro_de_ventas_muestra_factura_que_modifica(client, auth):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 2)]).json()
    n = nota(client, auth, f, [line(p, 1)]).json()
    text = client.get("/api/reports/libro-ventas.csv?period=all", headers=auth).content.decode("utf-8-sig")
    assert "Factura que modifica" in text.splitlines()[0]
    row = next(l for l in text.splitlines() if n["number"] in l)
    assert f["number"] in row


# ───────────────────────── usuario que emite y cobra ─────────────────────────
def test_documento_y_cobro_guardan_quien_los_hizo(client, auth, login):
    caja = make_user(client, auth, login, "Cajero", "Carla Caja")
    p = product(client, auth, "CEM-050")
    f = invoice(client, caja, [line(p, 1)]).json()
    assert f["user"] == "Carla Caja"
    d = client.post(f"/api/documents/{f['id']}/payments", json={"amount": f["total"]}, headers=caja).json()
    assert d["payments"][0]["user"] == "Carla Caja"


# ───────────────────────── bitácora ─────────────────────────
def test_bitacora_registra_operaciones(client, auth, login):
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 1)]).json()
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 10, "method": "Tarjeta"}, headers=auth)
    i = ids(client, auth)
    client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": i["wh"]["id"], "qty": -1, "concept": "Merma"}, headers=auth)
    body = {k: p[k] for k in ("sku", "name", "department_id", "category_id", "base_unit", "cost", "min_stock", "tax_treatment")}
    body.update(price=250, presentations=[{**pr, "price": pr["price"]} for pr in p["presentations"]])
    assert client.put(f"/api/products/{p['id']}", json=body, headers=auth).status_code == 200
    client.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": "mala"})
    data = client.get("/api/audit", headers=auth).json()
    actions = [r["action"] for r in data["rows"]]
    for expected in ("Ingresó al sistema", "Emitió factura", "Registró cobro", "Ajustó inventario", "Editó producto", "Ingreso fallido"):
        assert expected in actions, expected
    price = next(r for r in data["rows"] if r["action"] == "Editó producto")
    assert "precio L 245.00 → L 250.00" in price["detail"] and price["user"] == "Luis Mendoza"
    assert data["rows"][0]["action"] == "Ingreso fallido"  # lo más reciente primero
    # filtro por texto y descarga
    only = client.get(f"/api/audit?q={f['number']}", headers=auth).json()["rows"]
    assert only and all(f["number"] in r["detail"] for r in only)
    csv = client.get("/api/audit.csv", headers=auth)
    assert csv.status_code == 200 and "Emitió factura" in csv.content.decode("utf-8-sig")


def test_bitacora_solo_para_master_y_administrador(client, auth, login):
    for role in ("Supervisor", "Contador", "Cajero", "Vendedor", "Bodeguero"):
        h = make_user(client, auth, login, role)
        assert client.get("/api/audit", headers=h).status_code == 403, role
    adm = make_user(client, auth, login, "Administrador")
    assert client.get("/api/audit", headers=adm).status_code == 200


def test_operacion_rechazada_no_queda_en_bitacora(client, auth):
    p = product(client, auth, "CEM-050")
    i = ids(client, auth)
    r = client.post("/api/stock/adjust", json={"product_id": p["id"], "warehouse_id": i["wh"]["id"], "qty": -99999, "concept": "Error"}, headers=auth)
    assert r.status_code == 400
    assert "Ajustó inventario" not in [x["action"] for x in client.get("/api/audit", headers=auth).json()["rows"]]


# ───────────────────────── cierre de caja ─────────────────────────
def test_cierre_de_caja_por_forma_de_pago_y_usuario(client, auth, login):
    caja = make_user(client, auth, login, "Cajero", "Carla Caja")
    p = product(client, auth, "CEM-050")
    base = client.get("/api/cash/close", headers=auth).json()  # la semilla puede traer documentos de hoy
    f1 = invoice(client, caja, [line(p, 1)]).json()
    f2 = invoice(client, auth, [line(p, 2)]).json()
    client.post(f"/api/documents/{f1['id']}/payments", json={"amount": 100, "method": "Efectivo"}, headers=caja)
    client.post(f"/api/documents/{f1['id']}/payments", json={"amount": 50, "method": "Tarjeta"}, headers=caja)
    client.post(f"/api/documents/{f2['id']}/payments", json={"amount": 200, "method": "Efectivo"}, headers=auth)

    full = client.get("/api/cash/close", headers=auth).json()
    assert full["sees_all"] and full["collected"] - base["collected"] == 350 and full["cash"] - base["cash"] == 300
    methods = {m["method"]: m["total"] for m in full["by_method"]}
    assert methods["Tarjeta"] - {m["method"]: m["total"] for m in base["by_method"]}["Tarjeta"] == 50
    users = {u["user"]: u["total"] for u in full["by_user"]}
    assert users["Carla Caja"] == 150 and users["Luis Mendoza"] == 200
    assert full["sales"]["invoices"] - base["sales"]["invoices"] == 2
    assert round(full["sales"]["invoiced"] - base["sales"]["invoiced"], 2) == round(f1["total"] + f2["total"], 2)

    # el cajero solo ve su propio corte, aunque pida el de otro usuario
    master_id = client.get("/api/me", headers=auth).json()["id"]
    own = client.get(f"/api/cash/close?user_id={master_id}", headers=caja).json()
    assert not own["sees_all"] and own["collected"] == 150 and own["users"] == []
    assert own["sales"]["invoices"] == 1

    csv = client.get("/api/cash/close.csv", headers=auth)
    assert csv.status_code == 200 and "TOTAL COBRADO" in csv.content.decode("utf-8-sig")


def test_cierre_de_caja_otro_dia_y_permisos(client, auth, login):
    empty = client.get("/api/cash/close?day=2001-01-01", headers=auth).json()
    assert empty["collected"] == 0 and empty["payments"] == [] and empty["day"] == "2001-01-01"
    for role in ("Vendedor", "Bodeguero"):
        h = make_user(client, auth, login, role)
        assert client.get("/api/cash/close", headers=h).status_code == 403, role


def test_migracion_agrega_columnas_nuevas(tmp_path):
    """Una base de la v2.5 (sin las columnas nuevas) se actualiza sola al iniciar."""
    import sqlite3

    from sqlalchemy import create_engine

    from app.main import add_missing_columns
    path = tmp_path / "v25.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, number VARCHAR(32))")
    con.execute("CREATE TABLE payments (id INTEGER PRIMARY KEY, amount NUMERIC)")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{path}")
    add_missing_columns(eng)
    add_missing_columns(eng)  # correr dos veces no falla
    with eng.connect() as conn:
        doc_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(documents)").fetchall()}
        pay_cols = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(payments)").fetchall()}
    assert {"ref_document_id", "user_id", "user_name", "series_code"} <= doc_cols
    assert {"user_id", "user_name"} <= pay_cols
