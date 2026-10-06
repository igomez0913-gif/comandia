"""Pruebas de la v2.9: turnos de caja con fondo, retiros, gastos, ingresos y cierre con cuadre."""
from test_api import invoice, line, make_user, product


def test_turno_completo(client, auth, login):
    caja = make_user(client, auth, login, "Cajero", "Carla Caja")
    assert client.get("/api/shifts/current", headers=caja).json()["shift"] is None
    sh = client.post("/api/shifts/open", json={"caja": "Caja 1", "opening": 500}, headers=caja).json()
    assert sh["status"] == "Abierto" and sh["expected"]["Efectivo"] == 500
    assert client.post("/api/shifts/open", json={"caja": "Caja 2", "opening": 0}, headers=caja).status_code == 400  # uno a la vez
    otro = make_user(client, auth, login, "Supervisor", "Sara")
    assert client.post("/api/shifts/open", json={"caja": "caja 1", "opening": 0}, headers=otro).status_code == 400  # caja ocupada

    p = product(client, auth, "CEM-050")
    f = invoice(client, caja, [line(p, 4)]).json()  # 1 127.00
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 700, "method": "Efectivo"}, headers=caja)
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 300, "method": "Tarjeta"}, headers=caja)
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 100, "method": "Transferencia"}, headers=caja)
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 27, "method": "Efectivo"}, headers=auth)  # cobro de otro usuario: no cuenta

    sid = sh["id"]
    assert client.post(f"/api/shifts/{sid}/moves", json={"kind": "Retiro", "amount": 5000, "concept": "Demasiado"}, headers=caja).status_code == 400
    client.post(f"/api/shifts/{sid}/moves", json={"kind": "Retiro", "amount": 600, "concept": "A caja fuerte"}, headers=caja)
    client.post(f"/api/shifts/{sid}/moves", json={"kind": "Gasto", "amount": 50, "concept": "Agua y café"}, headers=caja)
    cur = client.post(f"/api/shifts/{sid}/moves", json={"kind": "Ingreso", "amount": 20, "concept": "Sencillo"}, headers=caja).json()
    # 500 + 700 − 600 − 50 + 20 = 570
    assert cur["expected"] == {"Efectivo": 570, "Tarjeta": 300, "Transferencia": 100} and cur["collected"] == 1100
    assert len(cur["payments"]) == 3 and cur["moves_total"]["Retiro"] == 600

    assert client.post(f"/api/shifts/{sid}/close", json={"counted": {"Tarjeta": 300}}, headers=caja).status_code == 400  # falta el efectivo
    done = client.post(f"/api/shifts/{sid}/close", json={"counted": {"Efectivo": 560, "Tarjeta": 300, "Transferencia": 100}, "note": "faltan 10"}, headers=caja).json()
    assert done["status"] == "Cerrado" and done["difference"] == -10
    lines = {x["method"]: x for x in done["lines"]}
    assert lines["Efectivo"]["difference"] == -10 and lines["Tarjeta"]["difference"] == 0
    assert client.post(f"/api/shifts/{sid}/moves", json={"kind": "Gasto", "amount": 1, "concept": "tarde"}, headers=caja).status_code == 400
    # un cobro después de cerrar no cambia el turno cerrado
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 0.5, "method": "Efectivo"}, headers=caja)
    again = client.get(f"/api/shifts/{sid}", headers=caja).json()
    assert again["lines"] == done["lines"] and again["collected"] == 1100

    hist = client.get("/api/shifts", headers=auth).json()["rows"]
    row = next(r for r in hist if r["id"] == sid)
    assert row["difference"] == -10 and row["cash_counted"] == 560 and row["user"] == "Carla Caja"
    actions = [a["action"] for a in client.get("/api/audit", headers=auth).json()["rows"]]
    assert {"Abrió turno de caja", "Retiro de caja", "Gasto de caja", "Cerró turno de caja"} <= set(actions)


def test_turnos_permisos(client, auth, login):
    caja = make_user(client, auth, login, "Cajero")
    vend = make_user(client, auth, login, "Vendedor")
    assert client.post("/api/shifts/open", json={"caja": "Caja 9"}, headers=vend).status_code == 403
    sid = client.post("/api/shifts/open", json={"caja": "Caja 9"}, headers=auth).json()["id"]
    assert client.get(f"/api/shifts/{sid}", headers=caja).status_code == 403  # turno de otro
    assert client.get("/api/shifts", headers=caja).json()["rows"] == []
