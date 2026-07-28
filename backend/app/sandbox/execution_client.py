import uuid
import time
from pathlib import Path

import httpx

from app.core.config import settings
from app.sandbox.execution_protocol import ExecutionRequest, ExecutionResponse
from app.sandbox.workload_identity import issue_assertion, load_private_key
from app.sandbox.workspace_archive import create_archive


class ExecutionPlaneClient:
    def execute(
        self,
        *,
        workspace: Path,
        command: str,
        shell_command: str,
        image: str,
        runtime: str,
        timeout_seconds: int,
    ) -> ExecutionResponse:
        archive, digest = create_archive(
            workspace,
            max_bytes=settings.sandbox_workspace_archive_max_bytes,
            max_files=settings.sandbox_workspace_archive_max_files,
        )
        request = ExecutionRequest(
            execution_id=str(uuid.uuid4()),
            archive_base64=archive,
            archive_sha256=digest,
            command=command,
            shell_command=shell_command,
            image=image,
            requested_runtime=runtime,
            timeout_seconds=timeout_seconds,
        )
        private_key_path = settings.sandbox_workload_identity_private_key_path
        if not private_key_path:
            raise RuntimeError("Sandbox workload identity private key is not configured")
        assertion = issue_assertion(
            private_key=load_private_key(private_key_path),
            issuer=settings.sandbox_workload_identity_issuer,
            subject=settings.sandbox_workload_identity_subject,
            audience=settings.sandbox_workload_identity_audience,
            request_hash=request.binding_hash(),
            ttl_seconds=settings.sandbox_workload_identity_ttl_seconds,
        )
        url = (settings.sandbox_execution_plane_url or "").rstrip("/")
        if not url.startswith("https://"):
            raise RuntimeError("Sandbox execution plane must use HTTPS")
        kwargs = {
            "verify": settings.sandbox_execution_plane_ca_path,
            "cert": (
                settings.sandbox_execution_plane_cert_path,
                settings.sandbox_execution_plane_key_path,
            ),
            "timeout": timeout_seconds + 30,
            "follow_redirects": False,
            "trust_env": False,
        }
        if settings.sandbox_execution_plane_proxy_url:
            kwargs["proxy"] = settings.sandbox_execution_plane_proxy_url
        with httpx.Client(**kwargs) as client:
            for attempt in range(max(1, settings.sandbox_execution_client_max_attempts)):
                try:
                    response = client.post(
                        f"{url}/v1/executions",
                        headers={"Authorization": f"Bearer {assertion}"},
                        json=request.model_dump(),
                    )
                    if (
                        response.status_code == 409
                        and "Retry-After" in response.headers
                        and attempt + 1 < settings.sandbox_execution_client_max_attempts
                    ):
                        try:
                            retry_after = float(response.headers["Retry-After"])
                        except ValueError:
                            retry_after = 1.0
                        time.sleep(max(0.0, min(2.0, retry_after)))
                        continue
                    response.raise_for_status()
                    break
                except httpx.TransportError:
                    if attempt + 1 >= settings.sandbox_execution_client_max_attempts:
                        raise
                    time.sleep(0.25 * (attempt + 1))
            else:  # pragma: no cover - the bounded loop always raises or breaks.
                raise RuntimeError("Sandbox execution retry budget exhausted")
        result = ExecutionResponse.model_validate(response.json())
        if result.execution_id != request.execution_id or result.archive_sha256 != digest:
            raise RuntimeError("Execution plane returned an unbound response")
        return result

    def health(self) -> dict:
        url = (settings.sandbox_execution_plane_url or "").rstrip("/")
        if not url.startswith("https://"):
            return {"status": "unconfigured"}
        kwargs = {
            "verify": settings.sandbox_execution_plane_ca_path,
            "cert": (
                settings.sandbox_execution_plane_cert_path,
                settings.sandbox_execution_plane_key_path,
            ),
            "timeout": 3,
            "follow_redirects": False,
            "trust_env": False,
        }
        if settings.sandbox_execution_plane_proxy_url:
            kwargs["proxy"] = settings.sandbox_execution_plane_proxy_url
        with httpx.Client(**kwargs) as client:
            response = client.get(f"{url}/health")
            response.raise_for_status()
            return response.json()
