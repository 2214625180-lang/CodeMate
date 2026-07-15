import shutil
import secrets
import socket
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, Response, status

from app.core.config import settings
from app.sandbox.execution_backends import execute_backend
from app.sandbox.execution_protocol import ExecutionRequest, ExecutionResponse
from app.sandbox.execution_store import build_execution_state_store
from app.sandbox.node_attestation import NodeAttestationError, NodeAttestationVerifier
from app.sandbox.runner import SandboxService
from app.sandbox.supply_chain import SupplyChainVerificationError, SupplyChainVerifier
from app.sandbox.workload_identity import (
    WorkloadIdentityError,
    load_public_key,
    verify_assertion,
)
from app.sandbox.workspace_archive import WorkspaceArchiveError, extract_archive


execution_store = build_execution_state_store()
instance_id = f"{socket.gethostname()}:{uuid.uuid4()}"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.validate_execution_plane_server_config()
    if not execution_store.health():
        raise RuntimeError("Shared sandbox execution state is unavailable")
    NodeAttestationVerifier().verify()
    yield


app = FastAPI(
    title="CodeMate Managed Sandbox Execution Plane",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def identify_execution_plane_instance(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-CodeMate-Execution-Plane-Instance"] = instance_id
    return response


@app.get("/health")
def health() -> dict[str, str]:
    try:
        state_ok = execution_store.health()
        NodeAttestationVerifier().verify()
    except Exception as exc:  # noqa: BLE001 - readiness is intentionally fail-closed.
        raise HTTPException(status_code=503, detail=f"Execution plane readiness failed: {exc}") from exc
    return {
        "status": "ok" if state_ok else "failed",
        "transport": "mutual-tls",
        "identity": "ed25519-request-bound",
        "backend": settings.sandbox_execution_plane_backend,
        "shared_state": settings.sandbox_execution_state_backend,
        "supply_chain": "enforced" if settings.sandbox_supply_chain_enabled else "disabled",
        "node_attestation": "enforced" if settings.sandbox_node_attestation_enabled else "disabled",
    }


@app.post("/v1/executions", response_model=ExecutionResponse)
def execute(
    request: ExecutionRequest,
    response: Response,
    authorization: str | None = Header(default=None),
) -> ExecutionResponse:
    assertion = _bearer(authorization)
    public_key_path = settings.sandbox_workload_identity_public_key_path
    if not public_key_path:
        raise HTTPException(status_code=503, detail="Workload identity verifier is not configured")
    try:
        claims = verify_assertion(
            assertion,
            public_key=load_public_key(public_key_path),
            issuer=settings.sandbox_workload_identity_issuer,
            subject=settings.sandbox_workload_identity_subject,
            audience=settings.sandbox_workload_identity_audience,
            request_hash=request.binding_hash(),
        )
    except WorkloadIdentityError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    allowed_images = {settings.sandbox_node_image, settings.sandbox_python_image}
    if request.image not in allowed_images or request.command not in settings.allowed_test_commands:
        raise HTTPException(status_code=403, detail="Execution request is not allowlisted")
    request_hash = request.binding_hash()
    current = int(time.time())
    try:
        claim = execution_store.claim(
            execution_id=request.execution_id,
            request_hash=request_hash,
            assertion_jti=str(claims["jti"]),
            assertion_ttl=max(1, int(claims["exp"]) - current),
            owner=instance_id,
            lease_seconds=request.timeout_seconds
            + max(10, settings.sandbox_execution_lease_grace_seconds),
        )
    except Exception as exc:  # noqa: BLE001 - shared state must fail closed.
        raise HTTPException(status_code=503, detail=f"Shared execution state unavailable: {exc}") from exc
    if claim.status == "cached" and claim.response:
        response.headers["X-CodeMate-Idempotent-Replay"] = "true"
        return claim.response
    if claim.status == "in_progress":
        raise HTTPException(
            status_code=409,
            detail="Execution is already in progress",
            headers={"Retry-After": "1"},
        )
    if claim.status == "conflict":
        raise HTTPException(status_code=409, detail="Execution ID is bound to another request")
    if claim.status == "replayed":
        raise HTTPException(status_code=401, detail="Workload identity assertion was replayed")
    root = Path(settings.sandbox_kubernetes_workspace_root if settings.sandbox_execution_plane_backend == "kubernetes" else settings.sandbox_workspace_dir)
    workspace = root.resolve() / request.execution_id
    try:
        if workspace.exists():
            shutil.rmtree(workspace)
        extract_archive(
            request.archive_base64,
            workspace,
            expected_sha256=request.archive_sha256,
            max_bytes=settings.sandbox_workspace_archive_max_bytes,
            max_files=settings.sandbox_workspace_archive_max_files,
        )
        service = SandboxService()
        dependency = service._dependency_install_command(
            workspace=workspace, command=request.command
        )
        expected_shell = service._test_shell_command(
            dependency_command=dependency, command=request.command
        )
        if not secrets.compare_digest(request.shell_command, expected_shell):
            raise HTTPException(
                status_code=403,
                detail="Execution shell command was not independently derived by policy",
            )
        try:
            evidence = SupplyChainVerifier().verify(
                image=request.image,
                backend=settings.sandbox_execution_plane_backend,
            )
            if settings.sandbox_execution_plane_backend == "firecracker":
                evidence.update(NodeAttestationVerifier().verify())
        except (NodeAttestationError, SupplyChainVerificationError) as exc:
            raise HTTPException(status_code=412, detail=str(exc)) from exc
        result = execute_backend(request, workspace)
        if settings.sandbox_execution_plane_backend == "kubernetes":
            if not result.execution_node:
                raise HTTPException(
                    status_code=503,
                    detail="Kubernetes did not report the sandbox Job execution node",
                )
            try:
                evidence.update(
                    NodeAttestationVerifier().verify(node_id=result.execution_node)
                )
            except NodeAttestationError as exc:
                raise HTTPException(status_code=412, detail=str(exc)) from exc
        limit = settings.sandbox_execution_output_max_chars
        evidence.update(
            execution_plane_instance=instance_id,
            execution_node=result.execution_node or socket.gethostname(),
            execution_attempt=str(claim.attempt),
        )
        execution_response = ExecutionResponse(
            execution_id=request.execution_id,
            backend=settings.sandbox_execution_plane_backend,
            passed=result.passed,
            exit_code=result.exit_code,
            stdout=result.stdout[:limit],
            stderr=result.stderr[:limit],
            timed_out=result.timed_out,
            archive_sha256=request.archive_sha256,
            workload_subject=str(claims["sub"]),
            attestation=evidence,
        )
        try:
            committed = execution_store.complete(
                execution_id=request.execution_id,
                request_hash=request_hash,
                owner=instance_id,
                attempt=claim.attempt,
                response=execution_response,
            )
        except Exception as exc:  # noqa: BLE001 - never return an uncommitted result.
            raise HTTPException(status_code=503, detail=f"Execution result could not be committed: {exc}") from exc
        if not committed:
            raise HTTPException(status_code=409, detail="Execution lease ownership was lost")
        return execution_response
    except WorkspaceArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        if workspace.exists():
            shutil.rmtree(workspace)


def _bearer(authorization: str | None) -> str:
    scheme, separator, token = (authorization or "").partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Workload identity required")
    return token.strip()
