import time
from secrets import token_urlsafe
from typing import cast

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import (
    EvaluationPrincipal,
    EvaluationRole,
    identity_signature_payload,
    require_evaluation_admin,
    require_evaluation_runner,
    require_evaluation_viewer,
    sign_identity_payload,
)
from app.core.config import settings


def test_viewer_role_can_access_viewer_dependency(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    client = create_client()

    response = client.get(
        "/viewer",
        headers={
            "Authorization": "Bearer secret-token",
            **signed_identity_headers("GET", "/viewer", "viewer", "alice", "github"),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "role": "viewer",
        "login": "alice",
        "provider": "github",
        "auth_method": "token",
        "token_kind": None,
    }


def test_viewer_role_cannot_access_admin_dependency(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    client = create_client()

    response = client.post(
        "/admin",
        headers={
            "Authorization": "Bearer secret-token",
            **signed_identity_headers("POST", "/admin", "viewer", "alice", "github"),
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Evaluation admin role required"}


def test_token_only_requests_remain_service_admin(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    client = create_client()

    response = client.post("/admin", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 200
    assert response.json() == {
        "role": "admin",
        "login": "service-admin-token",
        "provider": "service",
        "auth_method": "token",
        "token_kind": "admin",
    }


def test_ci_token_can_access_runner_dependency_but_not_admin_dependency(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "evaluation_ci_token", "ci-token")
    client = create_client()

    runner_response = client.post("/runner", headers={"Authorization": "Bearer ci-token"})
    admin_response = client.post("/admin", headers={"Authorization": "Bearer ci-token"})

    assert runner_response.status_code == 200
    assert runner_response.json() == {
        "role": "viewer",
        "login": "service-ci-token",
        "provider": "service",
        "auth_method": "token",
        "token_kind": "ci",
    }
    assert admin_response.status_code == 403
    assert admin_response.json() == {"detail": "Evaluation admin role required"}


def test_read_token_can_access_viewer_dependency_only(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "evaluation_read_token", "read-token")
    client = create_client()

    viewer_response = client.get("/viewer", headers={"Authorization": "Bearer read-token"})
    runner_response = client.post("/runner", headers={"Authorization": "Bearer read-token"})
    admin_response = client.post("/admin", headers={"Authorization": "Bearer read-token"})

    assert viewer_response.status_code == 200
    assert viewer_response.json() == {
        "role": "viewer",
        "login": "service-read-token",
        "provider": "service",
        "auth_method": "token",
        "token_kind": "read",
    }
    assert runner_response.status_code == 403
    assert runner_response.json() == {"detail": "Evaluation runner role required"}
    assert admin_response.status_code == 403
    assert admin_response.json() == {"detail": "Evaluation admin role required"}


def test_browser_proxy_token_only_requires_signed_identity_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", True)
    client = create_client()

    response = client.post(
        "/admin",
        headers={
            "Authorization": "Bearer secret-token",
            "X-CodeMate-Evaluation-Client": "browser",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Signed evaluation identity required for browser requests"}


def test_direct_browser_token_only_requires_signed_identity_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", True)
    client = create_client()

    response = client.post(
        "/admin",
        headers={
            "Authorization": "Bearer secret-token",
            "Origin": "http://localhost:3000",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Signed evaluation identity required for browser requests"}


def test_service_token_only_still_allowed_when_browser_identity_required(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", True)
    client = create_client()

    response = client.post("/admin", headers={"Authorization": "Bearer secret-token"})

    assert response.status_code == 200
    assert response.json() == {
        "role": "admin",
        "login": "service-admin-token",
        "provider": "service",
        "auth_method": "token",
        "token_kind": "admin",
    }


def test_signed_browser_identity_allowed_when_required(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", True)
    client = create_client()

    response = client.get(
        "/viewer",
        headers={
            "Authorization": "Bearer secret-token",
            "X-CodeMate-Evaluation-Client": "browser",
            **signed_identity_headers("GET", "/viewer", "viewer", "alice", "github"),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "role": "viewer",
        "login": "alice",
        "provider": "github",
        "auth_method": "token",
        "token_kind": None,
    }


def test_missing_token_is_unauthorized_when_backend_token_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    client = create_client()

    response = client.get("/viewer")

    assert response.status_code == 401
    assert response.json() == {"detail": "Evaluation API token required"}


def test_unsigned_identity_headers_are_rejected(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    client = create_client()

    response = client.get(
        "/viewer",
        headers={
            "Authorization": "Bearer secret-token",
            "X-CodeMate-Evaluation-Role": "viewer",
            "X-CodeMate-Evaluation-User": "alice",
            "X-CodeMate-Evaluation-Provider": "github",
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Valid evaluation identity signature required"}


def test_invalid_identity_signature_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    client = create_client()

    response = client.get(
        "/viewer",
        headers={
            "Authorization": "Bearer secret-token",
            **signed_identity_headers("GET", "/other", "viewer", "alice", "github"),
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Valid evaluation identity signature required"}


def test_previous_proxy_identity_secret_is_accepted(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "current-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_previous_secret", "previous-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    client = create_client()

    response = client.get(
        "/viewer",
        headers={
            "Authorization": "Bearer secret-token",
            **signed_identity_headers(
                "GET",
                "/viewer",
                "viewer",
                "alice",
                "github",
                signing_secret="previous-secret",
            ),
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "role": "viewer",
        "login": "alice",
        "provider": "github",
        "auth_method": "token",
        "token_kind": None,
    }


def test_unknown_proxy_identity_secret_is_rejected(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "current-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_previous_secret", "previous-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    client = create_client()

    response = client.get(
        "/viewer",
        headers={
            "Authorization": "Bearer secret-token",
            **signed_identity_headers(
                "GET",
                "/viewer",
                "viewer",
                "alice",
                "github",
                signing_secret="retired-secret",
            ),
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Valid evaluation identity signature required"}


def test_signed_identity_nonce_cannot_be_replayed(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    client = create_client()
    headers = {
        "Authorization": "Bearer secret-token",
        **signed_identity_headers("GET", "/viewer", "viewer", "alice", "github"),
    }

    first_response = client.get("/viewer", headers=headers)
    second_response = client.get("/viewer", headers=headers)

    assert first_response.status_code == 200
    assert second_response.status_code == 401
    assert second_response.json() == {"detail": "Evaluation identity nonce already used"}


def test_local_open_mode_defaults_to_admin(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", None)
    client = create_client()

    response = client.post("/admin")

    assert response.status_code == 200
    assert response.json() == {
        "role": "admin",
        "login": "local-dev",
        "provider": "local",
        "auth_method": "open",
        "token_kind": None,
    }


def create_client() -> TestClient:
    app = FastAPI()

    @app.get("/viewer")
    def viewer(
        principal: EvaluationPrincipal = Depends(require_evaluation_viewer),
    ):
        return principal_response(principal)

    @app.post("/admin")
    def admin(
        principal: EvaluationPrincipal = Depends(require_evaluation_admin),
    ):
        return principal_response(principal)

    @app.post("/runner")
    def runner(
        principal: EvaluationPrincipal = Depends(require_evaluation_runner),
    ):
        return principal_response(principal)

    return TestClient(app)


def principal_response(principal: EvaluationPrincipal) -> dict[str, str]:
    return {
        "role": principal.role,
        "login": principal.login,
        "provider": principal.provider,
        "auth_method": principal.auth_method,
        "token_kind": principal.token_kind,
    }


def signed_identity_headers(
    method: str,
    path_with_query: str,
    role: str,
    login: str,
    provider: str,
    *,
    signing_secret: str | None = None,
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
            signing_secret,
        ),
    }
