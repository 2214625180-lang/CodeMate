import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Header, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.config import settings
from app.sandbox.execution_client import ExecutionPlaneClient
from app.sandbox.runner import SandboxService, TestResult


class SandboxTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workspace: str = Field(min_length=1, max_length=255)
    command: str = Field(min_length=1, max_length=255)
    shell_command: str = Field(min_length=1, max_length=4096)
    image: str = Field(min_length=1, max_length=255)
    runtime: Literal["docker", "gvisor"]
    timeout_seconds: int = Field(ge=1, le=3600)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if settings.sandbox_execution_plane_enabled:
        settings._validate_execution_plane_config()
    yield


app = FastAPI(
    title="CodeMate Code Sandbox Broker",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, str]:
    result = {
        "status": "ok",
        "isolation": "managed-remote-execution",
        "transport": "mutual-tls",
        "workload_identity": "ed25519-request-bound",
    }
    if settings.sandbox_execution_plane_enabled:
        try:
            plane = ExecutionPlaneClient().health()
        except Exception as exc:  # noqa: BLE001 - readiness must fail closed.
            raise HTTPException(status_code=503, detail=f"Execution plane unavailable: {exc}") from exc
        if plane.get("status") != "ok" or plane.get("transport") != "mutual-tls":
            raise HTTPException(status_code=503, detail="Execution plane attestation failed")
        result["execution_backend"] = str(plane.get("backend", "unknown"))
    return result


@app.post("/v1/tests")
def run_tests(
    request: SandboxTestRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    require_token(authorization)
    if request.command not in settings.allowed_test_commands:
        raise HTTPException(status_code=403, detail="Test command is not allowlisted")
    expected_image = (
        settings.sandbox_node_image
        if request.command.startswith(("npm", "pnpm", "yarn"))
        else settings.sandbox_python_image
    )
    if request.image != expected_image:
        raise HTTPException(status_code=403, detail="Sandbox image is not allowlisted")
    workspace = safe_workspace(request.workspace)
    service = SandboxService()
    dependency = service._dependency_install_command(
        workspace=workspace,
        command=request.command,
    )
    expected_shell = service._test_shell_command(
        dependency_command=dependency,
        command=request.command,
    )
    if not secrets.compare_digest(request.shell_command, expected_shell):
        raise HTTPException(status_code=403, detail="Sandbox shell command was not derived by policy")
    result = execute_container(request, workspace)
    return result.to_dict()


def safe_workspace(relative: str) -> Path:
    root = Path(settings.sandbox_workspace_dir).resolve()
    workspace = (root / relative).resolve()
    try:
        workspace.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid sandbox workspace") from exc
    if not workspace.is_dir():
        raise HTTPException(status_code=404, detail="Sandbox workspace not found")
    return workspace


def execute_container(request: SandboxTestRequest, workspace: Path) -> TestResult:
    try:
        completed = ExecutionPlaneClient().execute(
            workspace=workspace,
            command=request.command,
            shell_command=request.shell_command,
            image=request.image,
            runtime=request.runtime,
            timeout_seconds=request.timeout_seconds,
        )
        return TestResult(
            passed=completed.passed,
            exit_code=completed.exit_code,
            stdout=completed.stdout,
            stderr=completed.stderr,
            command=request.command,
            tests_ran=True,
            timed_out=completed.timed_out,
            runtime=completed.backend,
        )
    except Exception as exc:  # noqa: BLE001 - preserve the stable broker result contract.
        return TestResult(
            passed=False,
            exit_code=126,
            stdout="",
            stderr=f"Managed sandbox execution failed: {exc}",
            command=request.command,
            tests_ran=False,
            runtime=settings.sandbox_execution_plane_backend,
        )


def require_token(authorization: str | None) -> None:
    scheme, separator, provided = (authorization or "").partition(" ")
    expected = (settings.sandbox_execution_broker_token or "").strip()
    if (
        not expected
        or not separator
        or scheme.lower() != "bearer"
        or not secrets.compare_digest(provided.strip(), expected)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Valid sandbox execution broker token required",
        )
