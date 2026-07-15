from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routes import mcp_operations
from app.core.config import settings
from app.core.database import Base, get_db
from app.models.mcp_server_health import MCPServerHealth


def create_client(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'operations-api.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as db:
        db.add(MCPServerHealth(server_name="docs", public_url="https://mcp.example/docs"))
        db.commit()

    def override_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr(settings, "evaluation_admin_token", "operations-admin-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    monkeypatch.setattr(settings, "mcp_client_servers_json", "[]")
    monkeypatch.setattr(
        mcp_operations,
        "enqueue_mcp_health_probe",
        lambda server_name=None: f"probe-{server_name or 'all'}",
    )
    monkeypatch.setattr(mcp_operations, "enqueue_mcp_compliance_scan", lambda: "compliance-1")
    monkeypatch.setattr(
        mcp_operations,
        "latest_compliance_report",
        lambda: {
            "schema_version": 1,
            "status": "compliant",
            "controls": [],
            "report_sha256": "a" * 64,
        },
    )
    app = FastAPI()
    app.include_router(mcp_operations.router)
    app.dependency_overrides[get_db] = override_db
    return TestClient(app)


def test_operations_api_requires_admin_and_controls_circuit(tmp_path, monkeypatch):
    client = create_client(tmp_path, monkeypatch)
    unauthorized = client.get("/mcp-operations/overview")
    headers = {"Authorization": "Bearer operations-admin-token"}
    overview = client.get("/mcp-operations/overview", headers=headers)
    server = overview.json()["servers"][0]
    controlled = client.post(
        "/mcp-operations/servers/docs/circuit",
        headers=headers,
        json={"action": "open", "expected_version": server["version"]},
    )
    probe = client.post("/mcp-operations/servers/docs/probe", headers=headers)
    metrics = client.get("/mcp-operations/metrics/prometheus", headers=headers)
    audit_delivery = client.get("/mcp-operations/security-audit", headers=headers)
    compliance = client.get("/mcp-operations/compliance/latest", headers=headers)
    compliance_scan = client.post("/mcp-operations/compliance/scan", headers=headers)

    assert unauthorized.status_code == 401
    assert overview.status_code == 200
    assert controlled.status_code == 200
    assert controlled.json()["circuit_state"] == "open"
    assert probe.json()["job_id"] == "probe-docs"
    assert metrics.status_code == 200
    assert "codemate_mcp_executions" in metrics.text
    assert audit_delivery.status_code == 200
    assert audit_delivery.json()["counts"] == {}
    assert compliance.json()["status"] == "compliant"
    assert compliance_scan.json()["job_id"] == "compliance-1"
