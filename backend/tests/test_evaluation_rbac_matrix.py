import ast
import re
import time
from dataclasses import dataclass
from pathlib import Path
from secrets import token_urlsafe
from typing import Literal, cast

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.auth import (
    EvaluationRole,
    identity_signature_payload,
    require_evaluation_admin,
    require_evaluation_runner,
    require_evaluation_viewer,
    sign_identity_payload,
)
from app.core.config import settings

RequiredRole = Literal["viewer", "runner", "admin"]


@dataclass(frozen=True)
class RouteSpec:
    method: str
    path: str
    required_role: RequiredRole


EXPECTED_ROUTE_RBAC: dict[tuple[str, str], RequiredRole] = {
    ("GET", "/evaluations"): "viewer",
    ("GET", "/evaluations/datasets"): "viewer",
    ("POST", "/evaluations/datasets"): "admin",
    ("POST", "/evaluations/datasets/{dataset_id}/run"): "runner",
    ("GET", "/evaluations/datasets/{dataset_id}/gate"): "viewer",
    ("POST", "/evaluations/capabilities/{capability}/evidence"): "admin",
    ("GET", "/evaluations/datasets/{dataset_id}/snapshots"): "viewer",
    ("POST", "/evaluations/datasets/{dataset_id}/snapshots/backfill"): "admin",
    ("GET", "/evaluations/datasets/{dataset_id}/history"): "viewer",
    ("GET", "/evaluations/dataset-snapshots/{snapshot_id}"): "viewer",
    ("GET", "/evaluations/datasets/{dataset_id}"): "viewer",
    ("PUT", "/evaluations/datasets/{dataset_id}"): "admin",
    ("DELETE", "/evaluations/datasets/{dataset_id}"): "admin",
    ("GET", "/evaluations/compare"): "viewer",
    ("GET", "/evaluations/{evaluation_run_id}/artifact"): "viewer",
    ("GET", "/evaluations/{evaluation_run_id}"): "viewer",
    ("POST", "/evaluations/retrieval"): "runner",
    ("POST", "/evaluations/fix"): "runner",
}


def test_evaluation_route_rbac_requirements_match_expected_matrix():
    assert source_declares_router_dependency("require_evaluation_viewer")
    parsed = parse_evaluation_route_specs()

    assert {(route.method, route.path): route.required_role for route in parsed} == EXPECTED_ROUTE_RBAC


def test_evaluation_route_rbac_status_matrix(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "evaluation_ci_token", "ci-token")
    monkeypatch.setattr(settings, "evaluation_read_token", "read-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", False)
    client = TestClient(create_auth_only_evaluation_app(parse_evaluation_route_specs()))

    for route in parse_evaluation_route_specs():
        url = concrete_path(route.path)
        cases = [
            ("anonymous", {}, 401),
            ("viewer", signed_identity_headers(route.method, url, "viewer"), viewer_status(route)),
            ("admin", signed_identity_headers(route.method, url, "admin"), 200),
            ("admin-token", {"Authorization": "Bearer secret-token"}, 200),
            ("ci-token", {"Authorization": "Bearer ci-token"}, ci_status(route)),
            ("read-token", {"Authorization": "Bearer read-token"}, read_status(route)),
        ]
        for principal_name, headers, expected_status in cases:
            response = client.request(route.method, url, headers=headers)
            assert response.status_code == expected_status, (
                f"{route.method} {route.path} as {principal_name} expected "
                f"{expected_status}, got {response.status_code}: {response.text}"
            )


def test_browser_token_only_fallback_is_blocked_for_every_evaluation_route(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", True)
    client = TestClient(create_auth_only_evaluation_app(parse_evaluation_route_specs()))

    for route in parse_evaluation_route_specs():
        response = client.request(
            route.method,
            concrete_path(route.path),
            headers={
                "Authorization": "Bearer secret-token",
                "X-CodeMate-Evaluation-Client": "browser",
            },
        )
        assert response.status_code == 401, (
            f"{route.method} {route.path} should reject browser token-only fallback"
        )
        assert response.json() == {"detail": "Signed evaluation identity required for browser requests"}


def test_signed_browser_identity_matrix_when_browser_identity_is_required(monkeypatch):
    monkeypatch.setattr(settings, "evaluation_admin_token", "secret-token")
    monkeypatch.setattr(settings, "codemate_proxy_identity_secret", "proxy-secret")
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "memory")
    monkeypatch.setattr(settings, "codemate_require_signed_browser_identity", True)
    client = TestClient(create_auth_only_evaluation_app(parse_evaluation_route_specs()))

    for route in parse_evaluation_route_specs():
        url = concrete_path(route.path)
        cases = [
            ("viewer", signed_identity_headers(route.method, url, "viewer", browser=True), viewer_status(route)),
            ("admin", signed_identity_headers(route.method, url, "admin", browser=True), 200),
        ]
        for principal_name, headers, expected_status in cases:
            response = client.request(route.method, url, headers=headers)
            assert response.status_code == expected_status, (
                f"{route.method} {route.path} as browser {principal_name} expected "
                f"{expected_status}, got {response.status_code}: {response.text}"
            )


def create_auth_only_evaluation_app(routes: list[RouteSpec]) -> FastAPI:
    app = FastAPI()
    for route in routes:
        dependencies = [Depends(require_evaluation_viewer)]
        if route.required_role == "runner":
            dependencies.append(Depends(require_evaluation_runner))
        if route.required_role == "admin":
            dependencies.append(Depends(require_evaluation_admin))
        app.add_api_route(
            route.path,
            endpoint=auth_only_endpoint,
            methods=[route.method],
            dependencies=dependencies,
        )
    return app


def auth_only_endpoint():
    return {"ok": True}


def viewer_status(route: RouteSpec) -> int:
    return 200 if route.required_role == "viewer" else 403


def ci_status(route: RouteSpec) -> int:
    return 403 if route.required_role == "admin" else 200


def read_status(route: RouteSpec) -> int:
    return 200 if route.required_role == "viewer" else 403


def concrete_path(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "test-id", path)


def signed_identity_headers(
    method: str,
    path_with_query: str,
    role: str,
    *,
    browser: bool = False,
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = token_urlsafe(24)
    login = f"{role}-user"
    provider = "github"
    payload = identity_signature_payload(
        method=method,
        path_with_query=path_with_query,
        timestamp=timestamp,
        nonce=nonce,
        role=cast(EvaluationRole, role),
        login=login,
        provider=provider,
    )
    headers = {
        "Authorization": "Bearer secret-token",
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
    if browser:
        headers["X-CodeMate-Evaluation-Client"] = "browser"
    return headers


def parse_evaluation_route_specs() -> list[RouteSpec]:
    tree = ast.parse(evaluations_route_source_path().read_text(encoding="utf-8"))
    routes: list[RouteSpec] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not is_router_method_decorator(decorator):
                continue
            method = cast(ast.Attribute, decorator.func).attr.upper()
            relative_path = route_decorator_path(decorator)
            required_role = route_required_role(decorator)
            routes.append(
                RouteSpec(
                    method=method,
                    path=evaluation_path(relative_path),
                    required_role=required_role,
                )
            )
    return routes


def route_required_role(decorator: ast.Call) -> RequiredRole:
    if decorator_depends_on(decorator, "require_evaluation_admin"):
        return "admin"
    if decorator_depends_on(decorator, "require_evaluation_runner"):
        return "runner"
    return "viewer"


def source_declares_router_dependency(dependency_name: str) -> bool:
    tree = ast.parse(evaluations_route_source_path().read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "router" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if not is_name(node.value.func, "APIRouter"):
            continue
        for keyword in node.value.keywords:
            if keyword.arg == "dependencies" and depends_on(keyword.value, dependency_name):
                return True
    return False


def is_router_method_decorator(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Attribute):
        return False
    if not is_name(node.func.value, "router"):
        return False
    return node.func.attr in {"get", "post", "put", "delete", "patch"}


def route_decorator_path(decorator: ast.Call) -> str:
    if decorator.args and isinstance(decorator.args[0], ast.Constant):
        value = decorator.args[0].value
        if isinstance(value, str):
            return value
    raise AssertionError(f"Route decorator missing literal path: {ast.unparse(decorator)}")


def decorator_depends_on(decorator: ast.Call, dependency_name: str) -> bool:
    return any(
        keyword.arg == "dependencies" and depends_on(keyword.value, dependency_name)
        for keyword in decorator.keywords
    )


def depends_on(node: ast.AST, dependency_name: str) -> bool:
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if not is_name(child.func, "Depends"):
            continue
        if child.args and is_name(child.args[0], dependency_name):
            return True
    return False


def is_name(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def evaluation_path(relative_path: str) -> str:
    return f"/evaluations{relative_path}"


def evaluations_route_source_path() -> Path:
    return Path(__file__).resolve().parents[1] / "app" / "api" / "routes" / "evaluations.py"
