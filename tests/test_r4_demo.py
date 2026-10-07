"""La demostración de restaurante: menú con recetas coherentes, salones y un servicio completo de punta a punta."""
import pytest

from test_api import stock


@pytest.fixture()
def demo(client):
    """Reemplaza la demostración de ferretería por la del restaurante."""
    from app.demo_restaurante import seed_restaurante
    from app.main import Base, SessionLocal, engine
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed_restaurante(db)
    db.close()
    r = client.post("/api/auth/login", json={"email": "luis@miempresa.hn", "password": "comandia123"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def by_sku(client, h):
    return {p["sku"]: p for p in client.get("/api/products", headers=h).json()}


def test_el_menu_tiene_costos_por_receta_con_margen_sano(client, demo):
    prods = by_sku(client, demo)
    platos = [p for p in prods.values() if p["kind"] == "platillo"]
    assert len(platos) == 12 and all(p["sellable"] for p in platos)
    for p in platos:
        assert p["cost"] > 0, p["sku"]
        assert 0.05 < p["cost"] / p["price"] < 0.5, f"{p['name']}: costo {p['cost']} precio {p['price']}"  # el costo de alimentos va entre 5 % (café) y 50 %
    assert {p["kind"] for p in prods.values()} == {"insumo", "elaborado", "producto", "platillo"}
    assert prods["PL-ALITAS"]["cost"] > 0 and prods["EL-BBQ"]["kind"] == "elaborado"  # un platillo usa un elaborado


def test_salones_y_descriptivos_de_demostracion(client, demo):
    salons = client.get("/api/salons", headers=demo).json()
    assert [s["name"] for s in salons] == ["Salón principal", "Terraza"]
    assert sum(1 for s in salons for i in s["items"] if i["kind"] == "mesa") == 13
    deps = {d["name"]: d["id"] for d in client.get("/api/departments", headers=demo).json()["departments"]}
    names = sorted(d["name"] for d in client.get(f"/api/descriptives?department_id={deps['Hamburguesas']}", headers=demo).json())
    assert "Extra queso" in names and "Sin cebolla" in names and "Con hielo" not in names
    assert client.get("/api/settings", headers=demo).json()["prices_include_tax"] is True


def test_un_servicio_completo(client, demo):
    prods = by_sku(client, demo)
    salons = client.get("/api/salons", headers=demo).json()
    mesa = next(i for i in salons[0]["items"] if i["name"] == "1")
    tab = client.post("/api/tabs", json={"table_ids": [mesa["id"]], "guests": 2}, headers=demo).json()
    extra = next(d for d in client.get("/api/descriptives", headers=demo).json() if d["name"] == "Extra queso")
    for sku, qty, kw in (("PL-HAMB", 2, {"descriptive_ids": [extra["id"]]}), ("PL-ALITAS", 1, {}), ("BEB-COLA", 2, {}), ("BEB-JUGO", 1, {})):
        r = client.post(f"/api/tabs/{tab['id']}/lines", json={"product_id": prods[sku]["id"], "qty": qty, **kw}, headers=demo)
        assert r.status_code == 200, r.text
    sent = client.post(f"/api/tabs/{tab['id']}/send", headers=demo).json()
    assert sorted(c["station"] for c in sent["comandas"]) == ["barra", "cocina"]
    total = 2 * (135 + 15) + 165 + 2 * 35 + 55
    assert sent["tab"]["total"] == total
    wh = client.get("/api/warehouses", headers=demo).json()[0]["id"]
    before = {s: stock(client, demo, s, wh) for s in ("INS-CARNE", "INS-PAN", "BEB-COLA", "INS-ALITAS", "EL-BBQ")}
    paid = client.post(f"/api/tabs/{tab['id']}/pay", json={"payments": [{"method": "Efectivo", "amount": total}], "tip": 59}, headers=demo)
    assert paid.status_code == 200, paid.text
    doc = paid.json()["document"]
    assert doc["total"] == total and round(doc["gravado_15"] + doc["isv_15"], 2) == total  # el precio del menú es el precio final
    assert round(before["INS-CARNE"] - stock(client, demo, "INS-CARNE", wh), 2) == 0.5 and before["INS-PAN"] - stock(client, demo, "INS-PAN", wh) == 2
    assert before["BEB-COLA"] - stock(client, demo, "BEB-COLA", wh) == 2 and round(before["EL-BBQ"] - stock(client, demo, "EL-BBQ", wh), 2) == 0.1


def test_una_base_vacia_arranca_con_el_restaurante(monkeypatch):
    """Al iniciar sin datos (como una instalación nueva) se carga el restaurante, salvo que se pida la demostración antigua."""
    from app import main
    monkeypatch.setenv("COMANDIA_DEMO", "restaurante")
    main.Base.metadata.drop_all(main.engine)
    main.startup()
    db = main.SessionLocal()
    try:
        assert db.query(main.Product).filter(main.Product.sku == "PL-HAMB").first() is not None
        assert db.query(main.Product).filter(main.Product.sku == "CEM-050").first() is None
        assert db.query(main.User).filter(main.User.role == "Master").count() == 1
    finally:
        db.close()
