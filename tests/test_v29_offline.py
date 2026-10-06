"""Pruebas de la v2.9: estado de la base de datos y ventas sin conexión que se sincronizan al volver."""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import OperationalError

from test_api import ids, product, stock


def sale(client, auth, p, qty, offline_id="", pay=None, **extra):
    i = ids(client, auth)
    total = round(float(p["presentations"][0]["price"]) * qty * 1.15, 2)
    body = {"client_id": i["final"]["id"], "warehouse_id": i["wh"]["id"], "items": [{"product_id": p["id"], "presentation_id": p["presentations"][0]["id"], "qty": qty}],
            "payments": [{"method": "Efectivo", "amount": pay if pay is not None else total}], "offline_id": offline_id, **({"offline": bool(offline_id)} | extra)}
    return client.post("/api/pos/sale", json=body, headers=auth)


def test_health_informa_la_base_de_datos(client, monkeypatch):
    h = client.get("/api/health").json()
    assert h["ok"] is True and h["db_ok"] is True
    import app.main as m

    def boom():
        raise OperationalError("SELECT 1", {}, Exception("Can't connect to MySQL server on 'x'"))
    monkeypatch.setattr(m.engine, "connect", boom)
    h = client.get("/api/health").json()
    assert h["ok"] is True and h["db_ok"] is False  # el servidor vive pero la base no contesta


def test_caida_de_la_base_responde_503():
    import app.main as m
    r = asyncio.run(m.db_unreachable(None, OperationalError("q", {}, Exception("(2003, \"Can't connect to MySQL server\")"))))
    assert r.status_code == 503 and b"DB_OFFLINE" in r.body
    r = asyncio.run(m.db_unreachable(None, OperationalError("q", {}, Exception("database is locked"))))
    assert r.status_code == 500


def test_venta_sin_conexion_se_sincroniza_una_sola_vez(client, auth):
    p = product(client, auth, "CEM-050")
    wh = ids(client, auth)["wh"]["id"]
    before = stock(client, auth, "CEM-050", wh)
    real = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    r = sale(client, auth, p, 2, offline_id="OFF-PC1-0001", offline_at=real, offline_user="Carla Caja")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "Pagada" and "Venta sin conexión OFF-PC1-0001" in d["notes"] and "cajero Carla Caja" in d["notes"]
    assert stock(client, auth, "CEM-050", wh) == before - 2
    # reintento (se perdió la respuesta): misma factura, sin duplicar ni descontar dos veces
    again = sale(client, auth, p, 2, offline_id="OFF-PC1-0001").json()
    assert again["duplicate"] is True and again["number"] == d["number"]
    assert stock(client, auth, "CEM-050", wh) == before - 2
    # la hora del cobro es la de la venta (hace 2 horas), no la de la sincronización
    paid = client.get(f"/api/documents/{d['id']}", headers=auth).json()["document"]["payments"][0]["created_at"]
    from app.main import now_local
    assert timedelta(minutes=100) < now_local() - datetime.fromisoformat(paid) < timedelta(minutes=140)
    actions = [a["action"] for a in client.get("/api/audit", headers=auth).json()["rows"]]
    assert "Venta sin conexión sincronizada" in actions


def test_venta_sin_conexion_acepta_existencia_insuficiente_pero_la_normal_no(client, auth):
    p = product(client, auth, "CEM-050")
    wh = ids(client, auth)["wh"]["id"]
    have = stock(client, auth, "CEM-050", wh)
    r = sale(client, auth, p, have + 5)
    assert r.status_code == 400 and "Stock insuficiente" in r.json()["detail"]
    r = sale(client, auth, p, have + 5, offline_id="OFF-PC1-0002")
    assert r.status_code == 200, r.text
    assert stock(client, auth, "CEM-050", wh) == -5  # la mercancía ya salió: queda en negativo para revisar


def test_service_worker_se_sirve_desde_la_raiz(client):
    r = client.get("/sw.js")
    assert r.status_code == 200 and r.headers["service-worker-allowed"] == "/" and "javascript" in r.headers["content-type"]


def test_reintento_de_una_venta_en_linea_tampoco_se_duplica(client, auth):
    """Si se cayó la conexión justo al cobrar, la pantalla reintenta con el mismo id: no se factura dos veces."""
    p = product(client, auth, "CEM-050")
    wh = ids(client, auth)["wh"]["id"]
    before = stock(client, auth, "CEM-050", wh)
    first = sale(client, auth, p, 1, offline_id="ON-ABC", offline=False).json()
    assert "Venta sin conexión" not in first["notes"]
    again = sale(client, auth, p, 1, offline_id="ON-ABC", offline=True).json()
    assert again["duplicate"] is True and again["number"] == first["number"]
    assert stock(client, auth, "CEM-050", wh) == before - 1
