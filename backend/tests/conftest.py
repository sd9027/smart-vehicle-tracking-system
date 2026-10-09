"""Test setup: a throwaway SQLite database so tests never touch your MySQL data.

SQLite ignores SELECT ... FOR UPDATE, so locking behaviour is only partly tested here.
The conditional-update and constraint protections work the same on both databases.
"""
import os
import pathlib
import sys

TEST_DB = pathlib.Path(__file__).parent / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
os.environ["JWT_SECRET"] = "test-only-secret-" + "x" * 40
os.environ["SIMULATOR_ENABLED"] = "false"
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from datetime import date, timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Driver, FuelType, Role, User, Vehicle  # noqa: E402
from app.security import hash_password, login_limiter  # noqa: E402

PASSWORD = "Password123!"


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    login_limiter.reset()
    pw = hash_password(PASSWORD)
    with SessionLocal() as s:
        s.add_all([
            User(name="Admin", email="admin@test.local", role=Role.ADMIN, password_hash=pw),
            User(name="Manager", email="manager@test.local", role=Role.MANAGER, password_hash=pw),
            User(name="Viewer", email="viewer@test.local", role=Role.VIEWER, password_hash=pw),
            Vehicle(registration_no="UK07AA1111", model="Test Van", fuel_type=FuelType.DIESEL),
            Driver(name="Test Driver", license_no="UK0720200011111",
                   license_expiry=date.today() + timedelta(days=365), phone="+91 9000000001"),
            Driver(name="Second Driver", license_no="UK0720200022222",
                   license_expiry=date.today() + timedelta(days=365), phone="+91 9000000002"),
        ])
        s.commit()
    with TestClient(app) as c:
        yield c
    engine.dispose()


def auth(client, email="manager@test.local", password=PASSWORD) -> dict:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
