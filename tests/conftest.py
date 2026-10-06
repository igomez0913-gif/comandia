import os
import sys
import tempfile

import pytest

# La base de datos de pruebas es un archivo temporal: nunca toca comandia.db.
_tmp = tempfile.mkdtemp(prefix="comandia-test-")
# TEST_DATABASE_URL permite correr la misma batería contra MySQL/MariaDB (usa una base de ensayo: se borra y recrea).
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{os.path.join(_tmp, 'test.db')}"
os.environ["COMANDIA_BACKUP_SCHEDULER"] = "0"  # el respaldo diario en segundo plano no corre durante las pruebas
os.environ["COMANDIA_BACKUP_DIR"] = os.path.join(_tmp, "respaldos")
os.environ["COMANDIA_LOGS"] = os.path.join(_tmp, "logs")  # los registros de las pruebas no ensucian la carpeta real
os.environ["COMANDIA_MARCA"] = os.path.join(_tmp, "instalado")  # marca de primera ejecución: nunca la del equipo real
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import _FAILS, API_RATE, Base, SessionLocal, app, engine, seed  # noqa: E402


@pytest.fixture()
def client():
    """Base limpia con los datos de demostración para cada prueba."""
    _FAILS.clear()
    API_RATE.clear()
    try:
        os.remove(os.environ["COMANDIA_MARCA"])
    except OSError:
        pass
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    db = SessionLocal()
    seed(db)
    db.close()
    with TestClient(app) as c:
        yield c


def _login(c, email="luis@miempresa.hn", password="comandia123"):
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.fixture()
def auth(client):
    return _login(client)


@pytest.fixture()
def login():
    return _login
