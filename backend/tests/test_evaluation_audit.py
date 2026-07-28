import json
import logging
import time
from pathlib import Path
from secrets import token_urlsafe
from typing import cast

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import (
    EvaluationPrincipal,
    EvaluationRole,
    identity_signature_payload,
    require_evaluation_admin,
    require_evaluation_viewer,
    sign_identity_payload,
)
from app.core.audit import evaluation_audit_middleware
from app.core.config import settings


def test_backend_audit_logs_resolved_principal(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    caplog.set_level(logging.INFO, logger="codemate.audit")
    client = TestClient(create_audited_app())

    response = client.get(
        "/evaluations/ping",
        headers={
            "Authorization": "Bearer secret-token",
            **signed_identity_headers("GET", "/evaluations/ping", "viewer", "alice", "github"),
            "X-Forwarded-For": "203.0.113.10, 10.0.0.2",
            "User-Agent": "audit-test",
        },
    )

    assert response.status_code == 200
    record = read_single_audit_record(audit_path)
    assert record["eventType"] == "backend_evaluation_request"
    assert record["outcome"] == "success"
    assert record["actor"] == {
        "provider": "github",
        "login": "alice",
        "role": "viewer",
    }
    assert record["method"] == "GET"
    assert record["path"] == "/evaluations/ping"
    assert record["status"] == 200
    assert record["reason"] is None
    assert record["ip"] == "203.0.113.10"
    assert record["userAgent"] == "audit-test"
    assert record["metadata"]["authMethod"] == "token"
    assert record["metadata"]["durationMs"] >= 0
    assert any(
        json.loads(log_record.message)["eventType"] == "backend_evaluation_request"
        for log_record in caplog.records
        if log_record.name == "codemate.audit"
    )


def test_backend_audit_logs_forbidden_viewer_principal(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    client = TestClient(create_audited_app())

    response = client.post(
        "/evaluations/admin",
        headers={
            "Authorization": "Bearer secret-token",
            **signed_identity_headers("POST", "/evaluations/admin", "viewer", "bob", "github"),
        },
    )

    assert response.status_code == 403
    record = read_single_audit_record(audit_path)
    assert record["outcome"] == "blocked"
    assert record["actor"] == {
        "provider": "github",
        "login": "bob",
        "role": "viewer",
    }
    assert record["method"] == "POST"
    assert record["path"] == "/evaluations/admin"
    assert record["status"] == 403
    assert record["reason"] == "forbidden"
    assert record["metadata"]["authMethod"] == "token"


def test_backend_audit_logs_unauthenticated_attempt(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    client = TestClient(create_audited_app())

    response = client.get("/evaluations/ping")

    assert response.status_code == 401
    record = read_single_audit_record(audit_path)
    assert record["outcome"] == "blocked"
    assert record["actor"] == {
        "provider": "unknown",
        "login": "anonymous",
        "role": None,
    }
    assert record["status"] == 401
    assert record["reason"] == "unauthorized"
    assert record["metadata"]["authMethod"] is None


def test_backend_audit_uses_mcp_approval_event_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    client = TestClient(create_audited_app())

    response = client.post(
        "/mcp-approvals/ping",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    record = read_single_audit_record(audit_path)
    assert record["eventType"] == "backend_mcp_approval_request"
    assert record["path"] == "/mcp-approvals/ping"


def test_backend_audit_uses_mcp_execution_event_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    client = TestClient(create_audited_app())

    response = client.post(
        "/mcp-executions/ping",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    record = read_single_audit_record(audit_path)
    assert record["eventType"] == "backend_mcp_execution_request"


def test_backend_audit_uses_mcp_operations_event_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    client = TestClient(create_audited_app())

    response = client.post(
        "/mcp-operations/ping",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    record = read_single_audit_record(audit_path)
    assert record["eventType"] == "backend_mcp_operations_request"


def test_backend_audit_uses_mcp_registry_event_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    client = TestClient(create_audited_app())

    response = client.post(
        "/mcp-registry/ping",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    record = read_single_audit_record(audit_path)
    assert record["eventType"] == "backend_mcp_registry_request"


def test_backend_audit_uses_mcp_quota_event_type(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    audit_path = tmp_path / "events.jsonl"
    monkeypatch.setattr(settings, "security_audit_log_path", str(audit_path))
    client = TestClient(create_audited_app())

    response = client.post(
        "/mcp-quotas/ping",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    assert read_single_audit_record(audit_path)["eventType"] == "backend_mcp_quota_request"


def test_fail_closed_audit_persists_intent_before_handler(monkeypatch, tmp_path):
    called = []
    captured = []
    monkeypatch.setattr(settings, "security_audit_log_path", str(tmp_path / "intent.jsonl"))
    monkeypatch.setattr(settings, "security_audit_sinks", "http,s3")
    monkeypatch.setattr(settings, "security_audit_fail_closed", True)
    monkeypatch.setattr(
        "app.core.audit.enqueue_remote_security_audit_record",
        lambda record: captured.append(record),
    )
    app = FastAPI()
    app.middleware("http")(evaluation_audit_middleware)

    @app.post("/mcp-registry/change")
    def change():
        called.append(True)
        return {"ok": True}

    response = TestClient(app).post("/mcp-registry/change")

    assert response.status_code == 200
    assert called == [True]
    assert [item["eventType"] for item in captured] == [
        "backend_security_request_intent",
        "backend_mcp_registry_request",
    ]
    assert captured[1]["metadata"]["intentId"] == captured[0]["id"]


def test_fail_closed_audit_does_not_execute_handler_when_intent_fails(monkeypatch):
    called = []
    monkeypatch.setattr(settings, "security_audit_log_path", None)
    monkeypatch.setattr(settings, "security_audit_sinks", "http,s3")
    monkeypatch.setattr(settings, "security_audit_fail_closed", True)

    def fail(_record):
        raise RuntimeError("outbox unavailable")

    monkeypatch.setattr("app.core.audit.enqueue_remote_security_audit_record", fail)
    app = FastAPI()
    app.middleware("http")(evaluation_audit_middleware)

    @app.post("/mcp-registry/change")
    def change():
        called.append(True)
        return {"ok": True}

    response = TestClient(app, raise_server_exceptions=False).post("/mcp-registry/change")

    assert response.status_code == 500
    assert called == []


def create_audited_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(evaluation_audit_middleware)

    @app.get("/evaluations/ping")
    def ping(
        principal: EvaluationPrincipal = Depends(require_evaluation_viewer),
    ):
        return {"role": principal.role}

    @app.post("/evaluations/admin")
    def admin(
        principal: EvaluationPrincipal = Depends(require_evaluation_admin),
    ):
        return {"role": principal.role}

    @app.post("/mcp-approvals/ping")
    def approval_admin(
        principal: EvaluationPrincipal = Depends(require_evaluation_admin),
    ):
        return {"role": principal.role}

    @app.post("/mcp-executions/ping")
    def execution_admin(
        principal: EvaluationPrincipal = Depends(require_evaluation_admin),
    ):
        return {"role": principal.role}

    @app.post("/mcp-operations/ping")
    def operations_admin(
        principal: EvaluationPrincipal = Depends(require_evaluation_admin),
    ):
        return {"role": principal.role}

    @app.post("/mcp-registry/ping")
    def registry_admin(
        principal: EvaluationPrincipal = Depends(require_evaluation_admin),
    ):
        return {"role": principal.role}

    @app.post("/mcp-quotas/ping")
    def quota_admin(
        principal: EvaluationPrincipal = Depends(require_evaluation_admin),
    ):
        return {"role": principal.role}

    return app


def read_single_audit_record(audit_path: Path) -> dict:
    lines = audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    return json.loads(lines[0])


def signed_identity_headers(
    method: str,
    path_with_query: str,
    role: str,
    login: str,
    provider: str,
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = token_urlsafe(24)
    payload = identity_signature_payload(
        method=method,
        path_with_query=path_with_query,
        timestamp=timestamp,
        nonce=nonce,
        role=cast(EvaluationRole, role),
        login=login,
        provider=provider,
    )
    return {
        "X-CodeMate-Evaluation-Role": role,
        "X-CodeMate-Evaluation-User": login,
        "X-CodeMate-Evaluation-Provider": provider,
        "X-CodeMate-Evaluation-Identity-Timestamp": timestamp,
        "X-CodeMate-Evaluation-Identity-Nonce": nonce,
        "X-CodeMate-Evaluation-Identity-Signature": sign_identity_payload(
            payload,
            "secret-token",
        ),
    }
