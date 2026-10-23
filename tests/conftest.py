"""Shared test setup.

Every test gets a brand-new in-memory SQLite database. The web app is pointed at it
by overriding get_db, so tests never touch a real database, network or AI model.
"""
import os

os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789-abcdefghijklmnop")
os.environ.setdefault("AI_PROVIDER", "ollama")
os.environ.setdefault("BCRYPT_ROUNDS", "4")  # fast hashing in tests only

from collections.abc import Generator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (registers every table on Base.metadata)
from app import database  # noqa: E402
from app.ai.provider import set_provider  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import Base, get_db  # noqa: E402
from app.integrations.registry import set_test_transport  # noqa: E402
from app.models import Project, ProjectMember, User  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402
from app.services.users import create_user, ensure_roles  # noqa: E402

PASSWORD = "Test-passw0rd"


@pytest.fixture
def engine():
    test_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory) -> Generator[Session, None, None]:
    with session_factory() as session:
        yield session


@pytest.fixture
def app_instance(session_factory, monkeypatch, tmp_path):
    from app.main import app

    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(database, "SessionLocal", session_factory)
    monkeypatch.setattr("app.main.SessionLocal", session_factory)
    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads")
    auth_router._attempts.clear()
    yield app
    app.dependency_overrides.clear()
    set_provider(None)
    set_test_transport(None)


@pytest.fixture
def client(app_instance) -> TestClient:
    return TestClient(app_instance)


@pytest.fixture
def people(db) -> dict[str, User]:
    """An admin, a PM, two BAs and two projects. Asha is only on PAY; Ben only on CRM."""
    ensure_roles(db)
    out = {
        "admin": create_user(db, "admin@test.com", "Ada Admin", PASSWORD, ["Admin"]),
        "pm": create_user(db, "pm@test.com", "Priya PM", PASSWORD, ["PM"]),
        "asha": create_user(db, "asha@test.com", "Asha Rao", PASSWORD, ["BA"]),
        "ben": create_user(db, "ben@test.com", "Ben Carter", PASSWORD, ["BA"]),
    }
    pay = Project(key="PAY", name="Payments", owner_id=out["pm"].id)
    crm = Project(key="CRM", name="Customer Portal", owner_id=out["pm"].id)
    db.add_all([pay, crm])
    db.flush()
    db.add_all([
        ProjectMember(project_id=pay.id, user_id=out["asha"].id),
        ProjectMember(project_id=crm.id, user_id=out["ben"].id),
        ProjectMember(project_id=pay.id, user_id=out["pm"].id, role_in_project="PM"),
    ])
    db.commit()
    out["pay"], out["crm"] = pay, crm
    return out


def login(client: TestClient, email: str, password: str = PASSWORD) -> TestClient:
    """Sign in through the real login form; afterwards client.csrf holds the form token."""
    client.get("/login")
    token = client.cookies.get("csrf_token")
    response = client.post("/login", data={"email": email, "password": password, "csrf_token": token},
                           follow_redirects=False)
    assert response.status_code == 303, response.text
    client.csrf = token  # type: ignore[attr-defined]
    return client


def form(client: TestClient, **data) -> dict:
    return {"csrf_token": client.csrf, **data}  # type: ignore[attr-defined]
