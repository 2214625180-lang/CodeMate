from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import mcp_registry
from app.core.config import settings
from app.core.database import Base, get_db


def create_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'registry-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "evaluation_admin_token", "registry-admin-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    monkeypatch.setattr(settings, "mcp_registry_enabled", True)
    monkeypatch.setattr(settings, "mcp_registry_master_key", "registry-master-key-32-characters-long")
    monkeypatch.setattr(settings, "mcp_client_servers_json", "[]")
    app = FastAPI()
    app.include_router(mcp_registry.router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_registry_api_auth_crud_and_secret_redaction(tmp_path, monkeypatch):
    client = create_client(tmp_path, monkeypatch)
    unauthorized = client.get("/mcp-registry/servers")
    headers = {"Authorization": "Bearer registry-admin-token"}
    created = client.post(
        "/mcp-registry/servers",
        headers=headers,
        json={
            "name": "docs",
            "url": "https://docs.example.com/mcp",
            "allowed_tools": ["search"],
            "tool_policies": {"search": "auto"},
        },
    )
    server = created.json()
    credential = client.put(
        f"/mcp-registry/servers/{server['id']}/credential",
        headers=headers,
        json={"auth_type": "bearer", "token": "super-secret-token"},
    )
    listed = client.get("/mcp-registry/servers", headers=headers)

    assert unauthorized.status_code == 401
    assert created.status_code == 201
    assert credential.status_code == 200
    assert "super-secret-token" not in credential.text
    assert listed.json()[0]["credential"]["auth_type"] == "bearer"
