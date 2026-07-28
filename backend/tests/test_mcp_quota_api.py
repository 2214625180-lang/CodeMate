from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import mcp_quotas
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.mcp_tenant import MCPTenant


def create_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'quota-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        tenant = MCPTenant(slug="quota-api", name="Quota API")
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        tenant_id = tenant.id

    def override_db():
        with factory() as db:
            yield db

    monkeypatch.setattr(settings, "evaluation_admin_token", "quota-admin-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    monkeypatch.setattr(settings, "mcp_quota_backend", "database")
    app = FastAPI()
    app.include_router(mcp_quotas.router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app), tenant_id


def test_quota_api_crud_reset_freeze_and_overview(tmp_path, monkeypatch):
    client, tenant_id = create_client(tmp_path, monkeypatch)
    headers = {"Authorization": "Bearer quota-admin-token"}
    assert client.get(f"/mcp-quotas/tenants/{tenant_id}/policies").status_code == 401

    created = client.post(
        f"/mcp-quotas/tenants/{tenant_id}/policies",
        headers=headers,
        json={
            "principal_type": "agent",
            "principal_id": "codemate-agent",
            "server_name": "docs",
            "tool_name": "search",
            "rate_limit_per_minute": 10,
            "daily_call_limit": 100,
            "daily_cost_limit": 250,
            "concurrent_limit": 2,
            "run_call_limit": 5,
            "call_cost_units": 2.5,
        },
    )
    policy = created.json()
    frozen = client.patch(
        f"/mcp-quotas/policies/{policy['id']}",
        headers=headers,
        json={"expected_version": policy["version"], "frozen": True},
    )
    adjusted = client.post(
        f"/mcp-quotas/policies/{policy['id']}/temporary-adjustment",
        headers=headers,
        json={
            "expected_version": frozen.json()["version"],
            "duration_seconds": 3600,
            "daily_call_limit": 200,
        },
    )
    reset = client.post(
        f"/mcp-quotas/policies/{policy['id']}/reset",
        headers=headers,
        json={"expected_version": adjusted.json()["version"]},
    )
    overview = client.get(
        f"/mcp-quotas/tenants/{tenant_id}/overview",
        headers=headers,
    )
    metrics = client.get(
        f"/mcp-quotas/tenants/{tenant_id}/metrics/prometheus",
        headers=headers,
    )

    assert created.status_code == 201
    assert frozen.status_code == 200 and frozen.json()["frozen"] is True
    assert adjusted.status_code == 200
    assert adjusted.json()["temporary_override"] == {"daily_call_limit": 200}
    assert reset.status_code == 200 and reset.json()["reset_at"]
    assert overview.status_code == 200
    assert overview.json()["policies"][0]["daily_call_limit"] == 100
    assert "codemate_mcp_quota_calls" in metrics.text

    disabled = client.delete(f"/mcp-quotas/policies/{policy['id']}", headers=headers)
    assert disabled.status_code == 204
