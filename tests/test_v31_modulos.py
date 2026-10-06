"""Pruebas de los módulos adicionales de la v3.1: reabastecimiento, etiquetas, notas de débito y guías de remisión."""
from datetime import date, timedelta

from app import licencia
from test_api import ids, invoice, line, product
from test_v29_licencia import end_trial, install_id, issue, keys  # noqa: F401


def test_reabastecimiento_sugiere_y_crea_ordenes_por_proveedor(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    base = next(r for r in client.get("/api/replenishment?days=30", headers=auth).json()["rows"] if r["sku"] == "CEM-050")["sold"]
    for _ in range(3):
        assert invoice(client, auth, [line(p, 5)]).status_code == 200
    data = client.get("/api/replenishment?days=30&lead=7&cover=30", headers=auth).json()
    row = next(r for r in data["rows"] if r["sku"] == "CEM-050")
    assert row["sold"] == base + 15 and row["daily"] == round((base + 15) / 30, 2) and row["stock"] > 0
    assert data["summary"]["products"] >= 1
    # lo que ya viene en una orden pendiente se descuenta de la sugerencia
    sup = client.get("/api/suppliers", headers=auth).json()[0]["id"]
    from app.main import Product, SessionLocal
    db = SessionLocal()
    db.query(Product).filter(Product.sku == "CEM-050").one().min_stock = row["stock"] + 100  # por debajo del mínimo: hay que pedir
    db.commit()
    db.close()
    forced = client.get("/api/replenishment?days=30&lead=7&cover=365", headers=auth).json()
    need = next(r for r in forced["rows"] if r["sku"] == "CEM-050")
    assert need["suggested"] > 0
    res = client.post("/api/replenishment/orders", json={"warehouse_id": i["wh"]["id"], "lines": [{"product_id": p["id"], "qty": need["suggested"], "supplier_id": sup, "unit_cost": 100}]}, headers=auth)
    assert res.status_code == 200 and len(res.json()["orders"]) == 1
    order = client.get(f"/api/purchases/{res.json()['orders'][0]['id']}", headers=auth).json()
    assert order["status"] == "Pendiente" and order["items"][0]["qty"] == need["suggested"]
    after = next(r for r in client.get("/api/replenishment?days=30&lead=7&cover=365", headers=auth).json()["rows"] if r["sku"] == "CEM-050")
    assert after["incoming"] == need["suggested"] and after["suggested"] == 0
    # una compra pendiente no mueve la existencia hasta recibirla
    assert after["stock"] == need["stock"]
    # un cajero no ve compras
    assert client.get("/api/replenishment", headers={"Authorization": "Bearer x"}).status_code == 401


def test_modulos_nuevos_con_candado_etiquetas_y_reabastecimiento(client, auth, keys):
    end_trial(client)
    for call in (lambda: client.get("/api/replenishment", headers=auth), lambda: client.get("/api/labels/products", headers=auth)):
        r = call()
        assert r.status_code == 403 and "no está activado" in r.json()["detail"]
    key = issue(keys, install_id(client, auth), modules=("etiquetas", "reabastecimiento"))
    assert client.post("/api/license", json={"key": key}, headers=auth).status_code == 200
    assert client.get("/api/replenishment", headers=auth).status_code == 200
    rows = client.get("/api/labels/products", headers=auth).json()
    assert rows and "presentations" in rows[0] and rows[0]["cost"] is None  # las etiquetas no exponen costos


def add_cai_for(client, auth, purpose, code, est="001"):
    body = {"cai": "D4E5F6-A7B8C9-001122-DDEEFF-AA0044", "doc_type": code, "purpose": purpose, "establishment": est, "emission_point": "001", "range_from": 1, "range_to": 50,
            "limit_date": (date.today() + timedelta(days=200)).isoformat()}
    r = client.post("/api/cai", json=body, headers=auth)
    assert r.status_code == 200, r.text


def test_nota_de_debito_aumenta_lo_que_debe_la_factura(client, auth):
    p = product(client, auth, "CEM-050")
    i = ids(client, auth)
    inv = invoice(client, auth, [line(p, 2)], payment_terms="Contado")
    assert inv.status_code == 200
    inv = inv.json()
    pay = client.post(f"/api/documents/{inv['id']}/payments", json={"amount": inv["total"], "method": "Efectivo"}, headers=auth)
    assert pay.status_code == 200 and client.get(f"/api/documents/{inv['id']}", headers=auth).json()["document"]["status"] == "Pagada"
    body = {"kind": "debito", "client_id": inv["client_id"], "warehouse_id": inv["warehouse_id"], "ref_document_id": inv["id"],
            "items": [{"description": "Intereses por mora", "qty": 1, "price": 100, "tax_treatment": "exento"}]}
    # sin CAI de nota de débito no se puede emitir (y el mensaje lo dice)
    r = client.post("/api/documents", json=body, headers=auth)
    assert r.status_code == 400 and "nota de débito" in r.json()["detail"].lower()
    add_cai_for(client, auth, "debito", "04")
    stock_before = next(s["qty"] for s in product(client, auth, "CEM-050")["stocks"] if s["warehouse_id"] == i["wh"]["id"])
    r = client.post("/api/documents", json=body, headers=auth)
    assert r.status_code == 200, r.text
    nd = r.json()
    assert nd["kind"] == "debito" and nd["kind_label"] == "Nota de débito" and nd["number"].startswith("001-001-04-") and nd["total"] == 100 and nd["ref_number"] == inv["number"]
    assert next(s["qty"] for s in product(client, auth, "CEM-050")["stocks"] if s["warehouse_id"] == i["wh"]["id"]) == stock_before  # no mueve inventario
    after = client.get(f"/api/documents/{inv['id']}", headers=auth).json()["document"]
    assert after["status"] == "Parcial" and after["balance"] == 100 and after["debited"] == 100 and [n["number"] for n in after["debit_notes"]] == [nd["number"]]
    # cobrar el cargo deja la factura pagada; anular la nota la deja como estaba
    assert client.post(f"/api/documents/{inv['id']}/payments", json={"amount": 100, "method": "Efectivo"}, headers=auth).status_code == 200
    assert client.get(f"/api/documents/{inv['id']}", headers=auth).json()["document"]["status"] == "Pagada"
    # libro de ventas: la nota de débito suma
    csv = client.get("/api/reports/libro-ventas.csv?period=all", headers=auth).text
    assert "Nota de débito" in csv and nd["number"] in csv
    # validaciones
    for bad in ({**body, "ref_document_id": None}, {**body, "items": [{"description": "", "qty": 1, "price": 5}]}, {**body, "items": [{"description": "x", "qty": 1, "price": 0}]}):
        assert client.post("/api/documents", json=bad, headers=auth).status_code == 400
    blocked = client.post(f"/api/documents/{nd['id']}/void", headers=auth)
    assert blocked.status_code == 400 and "ya se cobró" in blocked.json()["detail"]
    # una nota sin cobrar sí se puede anular y la factura vuelve a quedar pagada
    nd2 = client.post("/api/documents", json=body, headers=auth).json()
    assert client.get(f"/api/documents/{inv['id']}", headers=auth).json()["document"]["status"] == "Parcial"
    assert client.post(f"/api/documents/{nd2['id']}/void", headers=auth).status_code == 200
    back = client.get(f"/api/documents/{inv['id']}", headers=auth).json()["document"]
    assert back["status"] == "Pagada" and back["balance"] == 0
    # una factura con notas de débito vigentes no se puede anular
    assert client.post(f"/api/documents/{inv['id']}/void", headers=auth).status_code == 400


def test_docs_fiscales_con_candado(client, auth, keys):
    p = product(client, auth, "CEM-050")
    inv = invoice(client, auth, [line(p, 1)]).json()
    end_trial(client)
    body_nd = {"kind": "debito", "client_id": inv["client_id"], "warehouse_id": inv["warehouse_id"], "ref_document_id": inv["id"], "items": [{"description": "Flete", "qty": 1, "price": 50}]}
    for r in (client.post("/api/documents", json=body_nd, headers=auth), client.post("/api/cai", json={"cai": "D4E5F6-A7B8C9-001122-DDEEFF-AA0044", "doc_type": "04", "purpose": "debito", "limit_date": (date.today() + timedelta(days=90)).isoformat()}, headers=auth)):
        assert r.status_code == 403 and "no está activado" in r.json()["detail"]
    assert invoice(client, auth, [line(p, 1)]).status_code == 200  # facturar y las notas de crédito siguen funcionando
    key = issue(keys, install_id(client, auth), modules=("docs_fiscales",))
    assert client.post("/api/license", json={"key": key}, headers=auth).status_code == 200
    assert client.post("/api/documents", json=body_nd, headers=auth).status_code != 403  # ya no está bloqueada por la licencia


def test_ventas_por_rango_de_fechas(client, auth, login):
    p = product(client, auth, "CEM-050")
    r1 = invoice(client, auth, [line(p, 2)]).json()
    r2 = invoice(client, auth, [line(p, 1)]).json()
    assert client.post(f"/api/documents/{r2['id']}/void", headers=auth).status_code == 200
    from app.main import today_local
    today = today_local().isoformat()  # la fecha de Honduras (el servidor puede estar en otra zona horaria)
    data = client.get(f"/api/reports/ventas-detallado?start={today}&end={today}", headers=auth).json()
    mine = [v for v in data["ventas"] if v["numero"] in (r1["number"], r2["number"])]
    assert [v["estado"] for v in mine] == [r1["status"], "Anulada"] and mine[1]["total"] == 0  # la anulada sale en cero
    one = mine[0]
    assert abs(one["gravado"] + one["isv"] + one["exento"] - one["total"]) < 0.01 and one["isv"] > 0
    assert data["totales"]["documentos"] == len(data["ventas"]) and abs(sum(v["total"] for v in data["ventas"]) - data["totales"]["total"]) < 0.01
    csv = client.get(f"/api/reports/ventas-detallado.csv?start={today}&end={today}", headers=auth).text
    assert r1["number"] in csv and "TOTAL" in csv
    for bad in ("start=2026-13-01&end=2026-01-01", f"start={today}&end=2020-01-01", "start=2020-01-01&end=2023-01-01"):
        assert client.get(f"/api/reports/ventas-detallado?{bad}", headers=auth).status_code == 400
    cajero = make_user_local(client, auth, login)
    assert client.get(f"/api/reports/ventas-detallado?start={today}&end={today}", headers=cajero).status_code == 403  # sin permiso de reportes


def make_user_local(client, auth, login):
    from test_api import make_user
    return make_user(client, auth, login, "Cajero")


def test_libro_de_ventas_diario(client, auth, login):
    import csv as csvmod
    import io

    from openpyxl import load_workbook

    from app.main import Document, SessionLocal, today_local
    p = product(client, auth, "CEM-050")
    from app.main import today_local as _today
    base_book = client.get(f"/api/reports/libro-ventas-diario?month={_today().strftime('%Y-%m')}", headers=auth).json()
    base = next((r for r in base_book["dias"] if r["fecha"] == _today().isoformat() and r["kind"] == "factura" and r["serie"] == "Normal"), {"documentos": 0, "total": 0, "desde": None})
    series = {s["code"]: s["id"] for s in client.get("/api/settings", headers=auth).json()["series"]}
    normal = [invoice(client, auth, [line(p, q)]).json() for q in (1, 2, 3)]
    serie_e = [invoice(client, auth, [line(p, 1)], series_id=series["E"]).json() for _ in range(2)]
    assert client.post(f"/api/documents/{normal[1]['id']}/void", headers=auth).status_code == 200
    nc = client.post("/api/documents", json={"kind": "nota", "client_id": normal[2]["client_id"], "warehouse_id": normal[2]["warehouse_id"], "ref_document_id": normal[2]["id"],
                                             "items": [line(p, 1)]}, headers=auth)
    assert nc.status_code == 200, nc.text
    add_cai_for(client, auth, "debito", "04")
    nd = client.post("/api/documents", json={"kind": "debito", "client_id": normal[0]["client_id"], "warehouse_id": normal[0]["warehouse_id"], "ref_document_id": normal[0]["id"],
                                             "items": [{"description": "Flete", "qty": 1, "price": 100, "tax_treatment": "gravado15"}]}, headers=auth).json()
    today = today_local()
    month = today.strftime("%Y-%m")
    book = client.get(f"/api/reports/libro-ventas-diario?month={month}", headers=auth).json()
    assert book["serie"] == "Todas" and set(book["series_disponibles"]) >= {"Normal", "E"} and book["empresa"]["rtn"] and book["cai"]
    day = [r for r in book["dias"] if r["fecha"] == today.isoformat()]
    fn = next(r for r in day if r["kind"] == "factura" and r["serie"] == "Normal")
    assert fn["desde"] == (base["desde"] or normal[0]["number"]) and fn["hasta"] == normal[2]["number"] and fn["documentos"] == base["documentos"] + 3
    assert fn["anuladas"] == [normal[1]["number"]] and fn["saltos_total"] == 0
    assert abs(fn["total"] - (base["total"] + normal[0]["total"] + normal[2]["total"])) < 0.01  # la anulada no suma
    fe = next(r for r in day if r["serie"] == "E")
    assert (fe["desde"], fe["hasta"], fe["documentos"]) == (serie_e[0]["number"], serie_e[1]["number"], 2)
    cn = next(r for r in day if r["kind"] == "nota")
    assert cn["total"] < 0 and cn["desde"] == nc.json()["number"] and cn["tipo"] == "Nota de crédito"
    db_ = next(r for r in day if r["kind"] == "debito")
    assert db_["desde"] == nd["number"] and db_["total"] == 115 and db_["gravado_15"] == 100 and db_["isv_15"] == 15
    t = book["totales"]
    assert abs(t["netas"]["total"] - (t["facturas"]["total"] + t["debitos"]["total"] + t["creditos"]["total"])) < 0.01
    assert t["netas"]["anuladas"] == 1 and t["facturas"]["documentos"] >= 5
    for r in book["dias"]:  # cada fila cuadra: importes por tasa + ISV = total
        assert abs(r["exento"] + r["exonerado"] + r["gravado_15"] + r["isv_15"] + r["gravado_18"] + r["isv_18"] - r["total"]) < 0.02, r
    # filtro por serie
    only_e = client.get(f"/api/reports/libro-ventas-diario?month={month}&series=E", headers=auth).json()
    assert {r["serie"] for r in only_e["dias"]} == {"E"} and only_e["totales"]["netas"]["documentos"] == 2 and only_e["serie"] == "E"
    only_n = client.get(f"/api/reports/libro-ventas-diario?month={month}&series=normal", headers=auth).json()
    assert "E" not in {r["serie"] for r in only_n["dias"]}
    # el resumen coincide con el libro detallado documento por documento
    detail = list(csvmod.reader(io.StringIO(client.get("/api/reports/libro-ventas.csv?period=month", headers=auth).text.lstrip("﻿"))))
    total_col = detail[0].index("Total")
    assert abs(sum(float(r[total_col]) for r in detail[1:]) - t["netas"]["total"]) < 0.02
    # saltos en la numeración: se detectan y se avisan
    db = SessionLocal()
    doc = db.query(Document).filter(Document.number == normal[2]["number"]).one()
    gap_number = doc.number[:-8] + f"{int(doc.number[-8:]) + 2:08d}"
    doc.number = gap_number
    db.commit()
    db.close()
    gap = client.get(f"/api/reports/libro-ventas-diario?month={month}&series=normal", headers=auth).json()
    row = next(r for r in gap["dias"] if r["kind"] == "factura" and r["fecha"] == today.isoformat())
    assert row["saltos_total"] == 2 and gap["con_saltos"] >= 1  # faltaban los números intermedios
    # CSV y Excel
    csv_text = client.get(f"/api/reports/libro-ventas-diario.csv?month={month}", headers=auth).text.lstrip("﻿")
    assert "Número inicial" in csv_text and "VENTAS NETAS" in csv_text and nd["number"] in csv_text
    xl = client.get(f"/api/reports/libro-ventas-diario.xlsx?month={month}", headers=auth)
    assert xl.status_code == 200 and "spreadsheetml" in xl.headers["content-type"]
    ws = load_workbook(io.BytesIO(xl.content)).active
    texts = [str(c.value) for row in ws.iter_rows() for c in row if c.value is not None]
    assert "LIBRO DE VENTAS · RESUMEN DIARIO" in texts and "VENTAS NETAS" in texts and any("CAI" in x for x in texts)
    # parámetros y permisos
    for bad in ("month=2026-13", "start=2026-02-01&end=2026-01-01", "start=2020-01-01&end=2023-01-01", "month=abc"):
        assert client.get(f"/api/reports/libro-ventas-diario?{bad}", headers=auth).status_code == 400
    assert client.get(f"/api/reports/libro-ventas-diario?month={month}", headers=make_user_local(client, auth, login)).status_code == 403
