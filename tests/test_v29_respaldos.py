"""Pruebas de la v2.9: respaldo automático diario, respaldo manual y restauración."""
import os
from datetime import datetime
from types import SimpleNamespace

import pytest

from test_api import invoice, line, make_user, product


def test_respaldo_manual_y_lista(client, auth):
    r = client.post("/api/backups", headers=auth)
    assert r.status_code == 200, r.text
    info = r.json()
    assert info["size"] > 0 and "-manual-" in info["name"]
    data = client.get("/api/backups", headers=auth).json()
    assert info["name"] in [f["name"] for f in data["files"]]
    assert data["last"]["name"] == info["name"] and data["can_download"] is True
    assert client.get("/api/audit", headers=auth).json()["rows"][0]["action"] == "Respaldo manual"


def test_permisos_y_descarga(client, auth, login):
    name = client.post("/api/backups", headers=auth).json()["name"]
    r = client.get(f"/api/backups/{name}", headers=auth)
    assert r.status_code == 200 and len(r.content) > 0
    assert client.get("/api/backups/no-existe.sql", headers=auth).status_code == 404
    assert client.get("/api/backups/..%2F..%2Fsecret", headers=auth).status_code == 404
    adm = make_user(client, auth, login, "Administrador")
    assert client.get("/api/backups", headers=adm).json()["can_download"] is False
    assert client.get(f"/api/backups/{name}", headers=adm).status_code == 403
    caja = make_user(client, auth, login, "Cajero")
    assert client.get("/api/backups", headers=caja).status_code == 403
    assert client.post("/api/backups", headers=caja).status_code == 403


def test_configuracion_de_respaldos(client, auth, tmp_path):
    ok = {"enabled": True, "hour": 18, "keep": 10, "folder": str(tmp_path / "usb")}
    r = client.put("/api/backups/settings", json=ok, headers=auth)
    assert r.status_code == 200, r.text
    s = r.json()["settings"]
    assert (s["hour"], s["keep"], s["folder"]) == (18, 10, str(tmp_path / "usb"))
    assert os.path.isdir(tmp_path / "usb")
    assert client.put("/api/backups/settings", json={**ok, "folder": "relativa/carpeta"}, headers=auth).status_code == 400
    assert client.put("/api/backups/settings", json={**ok, "hour": 24}, headers=auth).status_code == 422
    assert client.put("/api/backups/settings", json={**ok, "keep": 0}, headers=auth).status_code == 422


def test_cuando_toca_el_respaldo_del_dia(tmp_path, monkeypatch):
    from app import main
    from app.respaldos import backup_name
    monkeypatch.setenv("COMANDIA_BACKUP_DIR", str(tmp_path))
    company = SimpleNamespace(backup_enabled=1, backup_hour=12, backup_dir="")
    morning, afternoon = datetime(2026, 10, 3, 9, 0), datetime(2026, 10, 3, 14, 0)
    assert main.backup_due(company, morning) is False  # todavía no es la hora
    assert main.backup_due(company, afternoon) is True
    (tmp_path / "comandia-manual-20261003-130000.sql").write_text("x")
    assert main.backup_due(company, afternoon) is True  # un respaldo manual no cuenta como el automático
    (tmp_path / "comandia-auto-20261003-120500.sql").write_text("x")
    assert main.backup_due(company, afternoon) is False  # ya se hizo el de hoy
    assert main.backup_due(company, datetime(2026, 10, 4, 14, 0)) is True  # al día siguiente toca otra vez
    company.backup_enabled = 0
    assert main.backup_due(company, datetime(2026, 10, 4, 14, 0)) is False
    assert backup_name(SimpleNamespace(database="comandia"), "auto", ".sql").startswith("comandia-auto-")


def test_el_respaldo_automatico_usa_la_fecha_de_honduras(client, auth, monkeypatch, tmp_path):
    """Con el equipo en otra zona horaria, el nombre del respaldo y la revisión diaria usan la misma fecha."""
    from app import main
    monkeypatch.setenv("COMANDIA_BACKUP_DIR", str(tmp_path))
    fake_local = datetime(2026, 10, 2, 18, 30)  # en Honduras todavía es 2 de octubre
    monkeypatch.setattr(main, "now_local", lambda: fake_local)
    client.put("/api/backups/settings", json={"enabled": True, "hour": 12, "keep": 30, "folder": ""}, headers=auth)
    info = main.run_backup("auto")
    assert "-auto-20261002-1830" in info["name"]
    db = main.SessionLocal()
    try:
        assert main.backup_due(db.query(main.Company).first(), fake_local) is False  # no lo repite cada 10 minutos
    finally:
        db.close()


def test_solo_se_guardan_los_ultimos_automaticos(tmp_path):
    from app.respaldos import list_backups, prune_auto
    for day in range(1, 8):
        (tmp_path / f"comandia-auto-202610{day:02d}-120000.sql").write_text("x")
    (tmp_path / "comandia-manual-20260901-120000.sql").write_text("x")
    assert prune_auto(str(tmp_path), 3) == 4  # ordena por la fecha del nombre, no por la del archivo
    names = sorted(r["name"] for r in list_backups(str(tmp_path)))
    assert names == ["comandia-auto-20261005-120000.sql", "comandia-auto-20261006-120000.sql", "comandia-auto-20261007-120000.sql",
                     "comandia-manual-20260901-120000.sql"]


def test_respaldo_automatico_corre_y_borra_viejos(client, auth, tmp_path, monkeypatch):
    from app import main
    monkeypatch.setenv("COMANDIA_BACKUP_DIR", str(tmp_path))
    for day in range(1, 4):
        (tmp_path / f"comandia-auto-202609{day:02d}-120000.sql").write_text("viejo")
    client.put("/api/backups/settings", json={"enabled": True, "hour": 0, "keep": 2, "folder": ""}, headers=auth)
    info = main.run_backup("auto")
    autos = [f for f in client.get("/api/backups", headers=auth).json()["files"] if f["auto"]]
    assert len(autos) == 2 and info["name"] in [f["name"] for f in autos] and info["removed"] == 2
    assert client.get("/api/audit", headers=auth).json()["rows"][0]["action"] == "Respaldo automático"


def test_respaldo_propio_se_restaura_completo(client, auth, tmp_path):
    """El respaldo JSON (el que se usa cuando no hay mysqldump) devuelve exactamente los mismos datos."""
    from sqlalchemy import create_engine, func, select

    from app import main
    from app.respaldos import dump_json, restore_json
    p = product(client, auth, "CEM-050")
    f = invoice(client, auth, [line(p, 3)]).json()
    client.post(f"/api/documents/{f['id']}/payments", json={"amount": 100.55}, headers=auth)
    path = str(tmp_path / "copia.json.gz")
    dump_json(main.engine, main.Base.metadata, path)
    target = create_engine(f"sqlite:///{tmp_path / 'restaurada.db'}")
    counts = restore_json(target, main.Base.metadata, path)
    with main.engine.connect() as a, target.connect() as b:
        for table in main.Base.metadata.sorted_tables:
            n = a.execute(select(func.count()).select_from(table)).scalar()
            assert counts[table.name] == n == b.execute(select(func.count()).select_from(table)).scalar(), table.name
        doc = main.Document.__table__
        src = a.execute(doc.select().where(doc.c.id == f["id"])).mappings().one()
        dst = b.execute(doc.select().where(doc.c.id == f["id"])).mappings().one()
        assert dict(src) == dict(dst)  # montos, fechas y textos idénticos
    with pytest.raises(ValueError):
        restore_json(target, main.Base.metadata, path)  # ya tiene datos: pide --forzar
    assert restore_json(target, main.Base.metadata, path, force=True)["documents"] == counts["documents"]


def test_sin_mysqldump_usa_el_respaldo_propio(client, auth, monkeypatch):
    from app import main, respaldos
    if main.engine.url.get_backend_name() != "mysql":
        pytest.skip("solo aplica con MySQL")
    monkeypatch.setattr(respaldos, "find_mysqldump", lambda: "")
    info = client.post("/api/backups", headers=auth).json()
    assert info["name"].endswith(".json.gz") and info["method"] == "respaldo propio de Comandia"


def test_el_script_sql_cubre_todas_las_columnas_nuevas():
    """actualizar-db.sql (para MySQL Workbench) debe agregar las mismas columnas que Comandia agrega al iniciar."""
    from app.main import BASE_DIR, NEW_COLUMNS
    sql = open(os.path.join(BASE_DIR, "actualizar-db.sql"), encoding="utf-8").read()
    missing = [f"{t}.{c}" for t, c, _ in NEW_COLUMNS if f"CALL comandia_add_column('{t}', '{c}'" not in sql]
    assert missing == [], f"Faltan en actualizar-db.sql: {missing}"
    assert "SET SQL_SAFE_UPDATES = 0" in sql
    # Tablas que no existían en la v2.3 (la más antigua que el script actualiza): deben crearse si faltan.
    base_v23 = {"users", "company", "departments", "categories", "warehouses", "clients", "suppliers", "products", "presentations", "stocks",
                "stock_moves", "cai_ranges", "invoice_series", "documents", "document_items", "payments", "purchases", "purchase_items", "banks", "bank_moves"}
    from app.main import Base
    new_tables = sorted(set(Base.metadata.tables) - base_v23)
    assert [t for t in new_tables if f"CREATE TABLE IF NOT EXISTS {t}" not in sql] == [], new_tables


def test_los_indices_nuevos_estan_en_el_script_sql_y_se_crean_solos():
    from app.main import BASE_DIR, NEW_INDEXES, add_missing_indexes, engine
    sql = open(os.path.join(BASE_DIR, "actualizar-db.sql"), encoding="utf-8").read()
    assert [n for n, t, c in NEW_INDEXES if f"CALL comandia_add_index('{t}', '{n}'" not in sql] == []
    from sqlalchemy import inspect
    add_missing_indexes(engine)
    add_missing_indexes(engine)  # repetir no hace daño
    names = {i["name"] for t in ("documents", "payments") for i in inspect(engine).get_indexes(t)}
    assert {"ix_documents_issued_kind", "ix_documents_offline", "ix_payments_created"} <= names
