"""Pruebas de la v2.9: panel de inicio con ventas de hoy, por hora, por día, más vendidos, margen y alertas."""
from test_api import invoice, line, make_user, product


def test_panel_de_inicio(client, auth, login):
    base = client.get("/api/dashboard/insights", headers=auth).json()
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 2)]).json()
    d = client.get("/api/dashboard/insights", headers=auth).json()
    assert round(d["today"]["sales"] - base["today"]["sales"], 2) == f["total"]
    assert d["today"]["tickets"] == base["today"]["tickets"] + 1
    assert len(d["hours"]) == 24 and len(d["daily"]) == 30
    assert round(sum(d["hours"]) - sum(base["hours"]), 2) == f["total"]
    top = next(x for x in d["top_products"] if x["sku"] == "CEM-050")
    assert top["amount"] >= 490 and "cost" in top
    assert d["margin"]["sales"] > 0 and d["margin"]["pct"] is not None
    assert d["top_clients"] and all(set(a) >= {"level", "title", "text", "go"} for a in d["alerts"])
    # sin permiso de costos no se ven costos ni margen
    caja = make_user(client, auth, login, "Cajero")
    c = client.get("/api/dashboard/insights", headers=caja).json()
    assert c["margin"] is None and all("cost" not in x for x in c["top_products"])


def test_alerta_de_turno_olvidado(client, auth, login):
    from datetime import timedelta

    from app.main import CashShift, SessionLocal, now_local
    caja = make_user(client, auth, login, "Cajero", "Carla")
    sid = client.post("/api/shifts/open", json={"caja": "Caja 3"}, headers=caja).json()["id"]
    db = SessionLocal()
    db.get(CashShift, sid).opened_at = now_local() - timedelta(days=2)
    db.commit()
    db.close()
    alerts = client.get("/api/dashboard/insights", headers=auth).json()["alerts"]
    assert any("turno" in a["title"] and "Caja 3" in a["text"] for a in alerts)
