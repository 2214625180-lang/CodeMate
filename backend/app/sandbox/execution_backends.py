import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.sandbox.execution_protocol import ExecutionRequest


@dataclass(slots=True)
class BackendResult:
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    execution_node: str | None = None


def execute_backend(request: ExecutionRequest, workspace: Path) -> BackendResult:
    backend = settings.sandbox_execution_plane_backend.strip().lower()
    if backend == "firecracker":
        return execute_firecracker(request, workspace)
    if backend == "kubernetes":
        return execute_kubernetes(request, workspace)
    raise RuntimeError(f"Unsupported execution plane backend: {backend}")


def execute_firecracker(request: ExecutionRequest, workspace: Path) -> BackendResult:
    configured = settings.sandbox_firecracker_runner_command_json
    if not configured:
        raise RuntimeError("SANDBOX_FIRECRACKER_RUNNER_COMMAND_JSON is required")
    try:
        template = json.loads(configured)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Firecracker runner command must be a JSON argv array") from exc
    if not isinstance(template, list) or not template or not all(isinstance(item, str) for item in template):
        raise RuntimeError("Firecracker runner command must be a non-empty JSON argv array")
    values = {
        "workspace": str(workspace),
        "image": request.image,
        "command": request.shell_command,
        "timeout": str(request.timeout_seconds),
        "execution_id": request.execution_id,
    }
    argv = [item.format(**values) for item in template]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=request.timeout_seconds + 10,
            check=False,
            shell=False,
        )
        return BackendResult(
            passed=completed.returncode == 0,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except subprocess.TimeoutExpired as exc:
        return BackendResult(
            passed=False,
            exit_code=124,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + "\nFirecracker execution timed out.",
            timed_out=True,
        )


def kubernetes_job_manifest(request: ExecutionRequest) -> dict:
    name = f"codemate-{request.execution_id[:8]}"
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {"name": name, "namespace": settings.sandbox_kubernetes_namespace},
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": request.timeout_seconds,
            "ttlSecondsAfterFinished": 300,
            "template": {
                "metadata": {"labels": {"app": "codemate-sandbox-job"}},
                "spec": {
                    "automountServiceAccountToken": False,
                    "restartPolicy": "Never",
                    "runtimeClassName": "kata",
                    "nodeSelector": settings.sandbox_kubernetes_node_selector,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 65532,
                        "runAsGroup": 65532,
                        "fsGroup": 65532,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [{
                        "name": "tests",
                        "image": request.image,
                        "imagePullPolicy": "IfNotPresent",
                        "command": ["sh", "-lc", request.shell_command],
                        "workingDir": "/workspace",
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "readOnlyRootFilesystem": True,
                            "capabilities": {"drop": ["ALL"]},
                        },
                        "resources": {
                            "requests": {"cpu": "100m", "memory": "128Mi"},
                            "limits": {"cpu": "1", "memory": "512Mi"},
                        },
                        "volumeMounts": [
                            {"name": "workspace", "mountPath": "/workspace", "subPath": request.execution_id},
                            {"name": "tmp", "mountPath": "/tmp"},
                        ],
                    }],
                    "volumes": [
                        {"name": "workspace", "persistentVolumeClaim": {"claimName": settings.sandbox_kubernetes_pvc_name}},
                        {"name": "tmp", "emptyDir": {"sizeLimit": "64Mi"}},
                    ],
                },
            },
        },
    }


def execute_kubernetes(request: ExecutionRequest, workspace: Path) -> BackendResult:
    expected = Path(settings.sandbox_kubernetes_workspace_root).resolve() / request.execution_id
    if workspace.resolve() != expected:
        expected.parent.mkdir(parents=True, exist_ok=True)
        if expected.exists():
            shutil.rmtree(expected)
        shutil.move(str(workspace), str(expected))
    manifest = kubernetes_job_manifest(request)
    name = manifest["metadata"]["name"]
    base = [settings.sandbox_kubectl_path, "-n", settings.sandbox_kubernetes_namespace]
    created = subprocess.run(
        [settings.sandbox_kubectl_path, "create", "-f", "-"],
        input=json.dumps(manifest),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    if created.returncode != 0 and "already exists" not in created.stderr.lower():
        raise RuntimeError(f"Kubernetes sandbox Job creation failed: {created.stderr[-1000:]}")
    try:
        deadline = time.monotonic() + request.timeout_seconds
        passed = False
        failed = False
        status_stderr = ""
        while time.monotonic() < deadline:
            status_result = subprocess.run(
                [*base, "get", f"job/{name}", "-o", "json"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            status_stderr = status_result.stderr
            if status_result.returncode == 0:
                payload = json.loads(status_result.stdout)
                job_status = payload.get("status") or {}
                passed = int(job_status.get("succeeded") or 0) > 0
                failed = int(job_status.get("failed") or 0) > 0
                if passed or failed:
                    break
            time.sleep(0.5)
        logs = subprocess.run(
            [*base, "logs", f"job/{name}"], capture_output=True, text=True, timeout=30, check=False
        )
        execution_node = _kubernetes_job_node(base, name)
        timed_out = not passed and not failed
        return BackendResult(
            passed=passed,
            exit_code=0 if passed else (124 if timed_out else 1),
            stdout=logs.stdout,
            stderr="\n".join(part for part in (status_stderr, logs.stderr) if part),
            timed_out=timed_out,
            execution_node=execution_node,
        )
    finally:
        subprocess.run(
            [*base, "delete", f"job/{name}", "--ignore-not-found=true", "--wait=false"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )


def _kubernetes_job_node(base: list[str], job_name: str) -> str | None:
    result = subprocess.run(
        [*base, "get", "pods", "-l", f"job-name={job_name}", "-o", "json"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        items = json.loads(result.stdout).get("items") or []
    except (AttributeError, json.JSONDecodeError):
        return None
    for item in items:
        node_name = (item.get("spec") or {}).get("nodeName")
        if node_name:
            return str(node_name)
    return None
