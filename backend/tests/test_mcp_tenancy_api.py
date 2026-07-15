from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import mcp_tenancy
from app.core.config import settings
from app.core.database import Base, get_db


def create_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'tenancy-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(settings, "evaluation_admin_token", "tenant-admin-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    monkeypatch.setattr(settings, "mcp_registry_master_key", "tenancy-master-key-32-characters-long")
    app = FastAPI()
    app.include_router(mcp_tenancy.router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_tenancy_api_auth_policy_crud_and_one_time_client_token(tmp_path, monkeypatch):
    client = create_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer tenant-admin-token"}

    assert client.get("/mcp-tenancy/tenants").status_code == 401
    created = client.post(
        "/mcp-tenancy/tenants",
        headers=headers,
        json={"slug": "acme", "name": "Acme"},
    )
    tenant = created.json()
    token = client.post(
        f"/mcp-tenancy/tenants/{tenant['id']}/client-token", headers=headers
    )
    membership = client.post(
        f"/mcp-tenancy/tenants/{tenant['id']}/memberships",
        headers=headers,
        json={"provider": "github", "subject": "alice", "role": "approver"},
    )
    binding = client.post(
        f"/mcp-tenancy/tenants/{tenant['id']}/bindings",
        headers=headers,
        json={"server_name": "docs", "enabled": True},
    )
    grant = client.post(
        f"/mcp-tenancy/tenants/{tenant['id']}/grants",
        headers=headers,
        json={
            "principal_type": "role",
            "principal_id": "approver",
            "server_name": "docs",
            "tool_name": "search",
            "permissions": ["approve"],
            "effect": "allow",
        },
    )
    listed = client.get(f"/mcp-tenancy/tenants/{tenant['id']}/grants", headers=headers)

    assert created.status_code == 201
    assert token.status_code == 200
    assert len(token.json()["client_token"]) >= 32
    assert token.json()["client_token"] not in client.get(
        "/mcp-tenancy/tenants", headers=headers
    ).text
    assert membership.status_code == binding.status_code == grant.status_code == 201
    assert listed.json()[0]["permissions"] == ["approve"]
