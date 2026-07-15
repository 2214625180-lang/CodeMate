from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import security_audit
from app.core.config import settings


def test_frontend_security_audit_ingest_is_authenticated(monkeypatch):
    captured = []
    monkeypatch.setattr(settings, "security_audit_ingest_token", "ingest-token-32-characters-long")
    monkeypatch.setattr(security_audit, "emit_security_audit_record", captured.append)
    app = FastAPI()
    app.include_router(security_audit.router)
    client = TestClient(app)
    payload = {
        "id": "frontend-event-1",
        "timestamp": "2026-07-14T00:00:00+00:00",
        "eventType": "frontend_proxy_request",
        "outcome": "success",
        "metadata": {"test": True},
    }

    unauthorized = client.post("/security-audit/events", json=payload)
    accepted = client.post(
        "/security-audit/events",
        json=payload,
        headers={"Authorization": "Bearer ingest-token-32-characters-long"},
    )

    assert unauthorized.status_code == 401
    assert accepted.status_code == 202
    assert captured[0]["id"] == "frontend-event-1"
    assert captured[0]["metadata"]["source"] == "codemate-frontend"
