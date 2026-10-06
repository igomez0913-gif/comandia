"""Pruebas de seguridad y confiabilidad: sesiones, claves, encabezados y existencias."""
import os
import threading

import pytest

from test_api import ids, invoice, line, product


def test_cambiar_la_clave_cierra_las_otras_sesiones(client, auth, login):
    again = login(client, "luis@miempresa.hn", "comandia123")
    assert client.get("/api/me", headers=again).status_code == 200
    r = client.post("/api/me/password", json={"current": "comandia123", "new": "Nueva-clave-2026"}, headers=auth)
    assert r.status_code == 200 and r.json()["token"]
    assert client.get("/api/me", headers=again).status_code == 401  # la sesión con la clave vieja ya no vale
    assert client.get("/api/me", headers=auth).status_code == 401
    assert client.get("/api/me", headers={"Authorization": "Bearer " + r.json()["token"]}).status_code == 200


def test_reglas_de_clave(client, auth):
    for weak in ("123456", "12345678", "password", "aaaaaaaa", "corta"):
        r = client.post("/api/me/password", json={"current": "comandia123", "new": weak}, headers=auth)
        assert r.status_code == 400, weak
    bad = client.post("/api/users", json={"name": "Nuevo Usuario", "email": "n@miempresa.hn", "password": "123456", "role": "Cajero"}, headers=auth)
    assert bad.status_code == 400 and "8 caracteres" in bad.json()["detail"]


def test_encabezados_de_seguridad_y_sin_cache_en_la_api(client, auth):
    r = client.get("/api/me", headers=auth)
    assert r.headers["cache-control"] == "no-store"
    home = client.get("/")
    assert home.headers["x-frame-options"] == "DENY" and home.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in home.headers["content-security-policy"] and "frame-ancestors 'none'" in home.headers["content-security-policy"]
    assert client.get("/docs").status_code == 404 and client.get("/openapi.json").status_code == 404  # la API no se publica sola


def test_alerta_si_se_sigue_con_la_clave_de_demostracion(client, auth):
    titles = [a["title"] for a in client.get("/api/dashboard/insights", headers=auth).json()["alerts"]]
    assert "Cambia tu clave" in titles
    client.post("/api/me/password", json={"current": "comandia123", "new": "Nueva-clave-2026"}, headers=auth)
    token = client.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": "Nueva-clave-2026"}).json()["token"]
    titles = [a["title"] for a in client.get("/api/dashboard/insights", headers={"Authorization": "Bearer " + token}).json()["alerts"]]
    assert "Cambia tu clave" not in titles


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL", "").startswith("mysql"), reason="el bloqueo de filas se prueba con MySQL/MariaDB (SQLite no permite escrituras simultáneas)")
def test_ventas_seguidas_no_pisan_la_existencia(client, auth):
    p = product(client, auth, "CEM-050")
    i = ids(client, auth)
    before = next(s["qty"] for s in product(client, auth, "CEM-050")["stocks"] if s["warehouse_id"] == i["wh"]["id"])
    results = []

    def sell():
        results.append(invoice(client, auth, [line(p, 1)]).status_code)

    threads = [threading.Thread(target=sell) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    after = next(s["qty"] for s in product(client, auth, "CEM-050")["stocks"] if s["warehouse_id"] == i["wh"]["id"])
    assert results.count(200) == 6 and before - after == 6


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL", "").startswith("mysql"), reason="la numeración simultánea se prueba con MySQL/MariaDB")
def test_ordenes_de_compra_simultaneas_no_repiten_numero(client, auth):
    i = ids(client, auth)
    p = product(client, auth, "CEM-050")
    sup = client.get("/api/suppliers", headers=auth).json()[0]["id"]
    codes = []

    def buy():
        r = client.post("/api/purchases", json={"supplier_id": sup, "warehouse_id": i["wh"]["id"], "status": "Pendiente", "items": [{"product_id": p["id"], "qty": 1, "unit_cost": 10}]}, headers=auth)
        codes.append((r.status_code, r.json().get("number")))

    threads = [threading.Thread(target=buy) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    numbers = [n for c, n in codes if c == 200]
    assert len(numbers) == 8 and len(set(numbers)) == 8
