import base64
import hashlib
import io
import json
import tarfile
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient

import app.sandbox.execution_backends as backend_module
import app.sandbox.execution_client as client_module
import app.sandbox.execution_plane as plane_module
import app.sandbox.node_attestation as attestation_module
from app.core.config import settings
from app.sandbox.execution_backends import BackendResult, execute_firecracker, kubernetes_job_manifest
from app.sandbox.execution_client import ExecutionPlaneClient
from app.sandbox.execution_plane import app
from app.sandbox.execution_protocol import ExecutionRequest
from app.sandbox.execution_store import MemoryExecutionStateStore, RedisExecutionStateStore
from app.sandbox.node_attestation import NodeAttestationError, NodeAttestationVerifier
from app.sandbox.supply_chain import _attestation_statements, _statement_has_source
from app.sandbox.workload_identity import (
    ReplayCache,
    WorkloadIdentityError,
    issue_assertion,
    verify_assertion,
)
from app.sandbox.workspace_archive import WorkspaceArchiveError, create_archive, extract_archive


def key_pair(tmp_path):
    private = Ed25519PrivateKey.generate()
    public_path = tmp_path / "identity.pub"
    public_path.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private, public_path


def write_private_key(private, tmp_path):
    path = tmp_path / "identity.key"
    path.write_bytes(
        private.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return path


def request_for(tmp_path):
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "package.json").write_text('{"scripts":{"test":"echo ok"}}')
    archive, digest = create_archive(workspace, max_bytes=100_000, max_files=100)
    return ExecutionRequest(
        execution_id="12345678-1234-1234-1234-123456789012",
        archive_base64=archive,
        archive_sha256=digest,
        command="npm test",
        shell_command="npm test",
        image="node:20-alpine",
        requested_runtime="docker",
        timeout_seconds=30,
    )


def test_workload_identity_is_request_bound_and_replay_protected(tmp_path):
    private, _ = key_pair(tmp_path)
    token = issue_assertion(
        private_key=private,
        issuer="issuer",
        subject="spiffe://broker",
        audience="runner",
        request_hash="a" * 64,
        ttl_seconds=60,
        now=100,
    )
    claims = verify_assertion(
        token,
        public_key=private.public_key(),
        issuer="issuer",
        subject="spiffe://broker",
        audience="runner",
        request_hash="a" * 64,
        now=110,
    )
    cache = ReplayCache(entries={})
    cache.consume(claims["jti"], claims["exp"], now=110)
    with pytest.raises(WorkloadIdentityError, match="replayed"):
        cache.consume(claims["jti"], claims["exp"], now=110)
    with pytest.raises(WorkloadIdentityError, match="binding"):
        verify_assertion(
            token,
            public_key=private.public_key(),
            issuer="issuer",
            subject="spiffe://broker",
            audience="runner",
            request_hash="b" * 64,
            now=110,
        )


def test_workspace_archive_rejects_links_and_traversal(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "real.txt").write_text("safe")
    (source / "link.txt").symlink_to(source / "real.txt")
    with pytest.raises(WorkspaceArchiveError, match="symlink"):
        create_archive(source, max_bytes=100_000, max_files=100)

    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w:gz") as archive:
        info = tarfile.TarInfo("../escape")
        info.size = 4
        archive.addfile(info, io.BytesIO(b"evil"))
    payload = stream.getvalue()
    with pytest.raises(WorkspaceArchiveError, match="escapes"):
        extract_archive(
            base64.b64encode(payload).decode(),
            tmp_path / "out",
            expected_sha256=hashlib.sha256(payload).hexdigest(),
            max_bytes=100_000,
            max_files=100,
        )


def test_execution_plane_verifies_identity_policy_and_idempotency(monkeypatch, tmp_path):
    private, public_path = key_pair(tmp_path)
    request = request_for(tmp_path)
    values = {
        "sandbox_workload_identity_public_key_path": str(public_path),
        "sandbox_workload_identity_issuer": "issuer",
        "sandbox_workload_identity_subject": "spiffe://broker",
        "sandbox_workload_identity_audience": "runner",
        "sandbox_workspace_dir": str(tmp_path / "runs"),
        "sandbox_execution_plane_backend": "firecracker",
        "sandbox_node_image": "node:20-alpine",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    monkeypatch.setattr(plane_module, "execution_store", MemoryExecutionStateStore())
    monkeypatch.setattr(
        plane_module,
        "execute_backend",
        lambda _request, _workspace: BackendResult(True, 0, "ok", ""),
    )
    assertion = issue_assertion(
        private_key=private,
        issuer="issuer",
        subject="spiffe://broker",
        audience="runner",
        request_hash=request.binding_hash(),
        ttl_seconds=60,
    )
    headers = {"Authorization": f"Bearer {assertion}"}
    with TestClient(app) as client:
        accepted = client.post("/v1/executions", json=request.model_dump(), headers=headers)
        replayed = client.post("/v1/executions", json=request.model_dump(), headers=headers)
    assert accepted.status_code == 200
    assert accepted.json()["archive_sha256"] == request.archive_sha256
    assert accepted.headers["X-CodeMate-Execution-Plane-Instance"]
    assert replayed.status_code == 200
    assert replayed.headers["X-CodeMate-Idempotent-Replay"] == "true"


def test_firecracker_backend_uses_argv_without_shell(monkeypatch, tmp_path):
    request = request_for(tmp_path)
    monkeypatch.setattr(
        settings,
        "sandbox_firecracker_runner_command_json",
        json.dumps(["launcher", "--workspace", "{workspace}", "--command", "{command}"]),
    )
    captured = {}

    class Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    def run(argv, **kwargs):
        captured.update({"argv": argv, **kwargs})
        return Completed()

    monkeypatch.setattr(backend_module.subprocess, "run", run)
    result = execute_firecracker(request, tmp_path)
    assert result.passed is True
    assert captured["shell"] is False
    assert captured["argv"][0] == "launcher"


def test_execution_client_requires_mtls_and_binds_response(monkeypatch, tmp_path):
    private, _ = key_pair(tmp_path)
    private_path = write_private_key(private, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "package.json").write_text("{}")
    values = {
        "sandbox_execution_plane_url": "https://runner.internal:8443",
        "sandbox_execution_plane_ca_path": "/run/ca.crt",
        "sandbox_execution_plane_cert_path": "/run/client.crt",
        "sandbox_execution_plane_key_path": "/run/client.key",
        "sandbox_workload_identity_private_key_path": str(private_path),
        "sandbox_workload_identity_issuer": "issuer",
        "sandbox_workload_identity_subject": "spiffe://broker",
        "sandbox_workload_identity_audience": "runner",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)
    captured = {}

    class Response:
        status_code = 200
        headers = {}

        def raise_for_status(self):
            return None

        def json(self):
            request = captured["json"]
            return {
                "execution_id": request["execution_id"],
                "backend": "firecracker",
                "passed": True,
                "exit_code": 0,
                "stdout": "ok",
                "stderr": "",
                "timed_out": False,
                "archive_sha256": request["archive_sha256"],
                "workload_subject": "spiffe://broker",
            }

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, url, **kwargs):
            captured.update({"url": url, **kwargs})
            return Response()

    monkeypatch.setattr(client_module.httpx, "Client", Client)
    result = ExecutionPlaneClient().execute(
        workspace=workspace,
        command="npm test",
        shell_command="npm test",
        image="node:20-alpine",
        runtime="docker",
        timeout_seconds=30,
    )
    assert result.passed is True
    assert captured["client"]["verify"] == "/run/ca.crt"
    assert captured["client"]["cert"] == ("/run/client.crt", "/run/client.key")
    assert captured["client"]["trust_env"] is False
    assert captured["headers"]["Authorization"].startswith("Bearer ")


def test_kubernetes_job_is_kata_non_root_and_network_policy_labeled(tmp_path):
    request = request_for(tmp_path)
    manifest = kubernetes_job_manifest(request)
    pod = manifest["spec"]["template"]
    spec = pod["spec"]
    container = spec["containers"][0]
    assert spec["runtimeClassName"] == "kata"
    assert spec["automountServiceAccountToken"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert pod["metadata"]["labels"]["app"] == "codemate-sandbox-job"
    assert spec["nodeSelector"] == {"codemate.io/attested-sandbox-node": "true"}


def test_execution_state_fences_owners_and_returns_cached_result(tmp_path):
    store = MemoryExecutionStateStore()
    request = request_for(tmp_path)
    first = store.claim(
        execution_id=request.execution_id,
        request_hash=request.binding_hash(),
        assertion_jti="jti-1",
        assertion_ttl=60,
        owner="node-a",
        lease_seconds=30,
    )
    competing = store.claim(
        execution_id=request.execution_id,
        request_hash=request.binding_hash(),
        assertion_jti="jti-2",
        assertion_ttl=60,
        owner="node-b",
        lease_seconds=30,
    )
    response = plane_module.ExecutionResponse(
        execution_id=request.execution_id,
        backend="firecracker",
        passed=True,
        exit_code=0,
        stdout="ok",
        stderr="",
        archive_sha256=request.archive_sha256,
        workload_subject="spiffe://broker",
    )
    assert first.status == "acquired"
    assert competing.status == "in_progress"
    assert store.complete(
        execution_id=request.execution_id,
        request_hash=request.binding_hash(),
        owner="node-b",
        attempt=first.attempt,
        response=response,
    ) is False
    assert store.complete(
        execution_id=request.execution_id,
        request_hash=request.binding_hash(),
        owner="node-a",
        attempt=first.attempt + 1,
        response=response,
    ) is False
    assert store.complete(
        execution_id=request.execution_id,
        request_hash=request.binding_hash(),
        owner="node-a",
        attempt=first.attempt,
        response=response,
    ) is True
    cached = store.claim(
        execution_id=request.execution_id,
        request_hash=request.binding_hash(),
        assertion_jti="jti-3",
        assertion_ttl=60,
        owner="node-c",
        lease_seconds=30,
    )
    assert cached.status == "cached"
    assert cached.response and cached.response.stdout == "ok"


def test_redis_execution_keys_share_cluster_slot(monkeypatch):
    captured = {}

    class Redis:
        def eval(self, _script, key_count, *values):
            captured["keys"] = values[:key_count]
            return [b"acquired", b"1", b""]

    monkeypatch.setattr(settings, "sandbox_execution_state_prefix", "codemate:test")
    store = RedisExecutionStateStore(Redis())
    store.claim(
        execution_id="execution",
        request_hash="a" * 64,
        assertion_jti="jti",
        assertion_ttl=60,
        owner="node-a",
        lease_seconds=60,
    )
    assert all("{atomic}" in key for key in captured["keys"])


def test_slsa_source_requires_an_exact_repository_uri():
    statement = {
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "externalParameters": {"source": {"uri": "https://github.com/acme/codemate@main"}}
            }
        },
    }
    payload = base64.b64encode(json.dumps(statement).encode()).decode()
    decoded = _attestation_statements(json.dumps([{"payload": payload}]))
    assert _statement_has_source(decoded[0], "https://github.com/acme/codemate") is True
    assert _statement_has_source(decoded[0], "https://github.com/acme/code") is False


def test_node_attestation_challenge_is_signed_and_bound(monkeypatch, tmp_path):
    private, public_path = key_pair(tmp_path)
    now = int(time.time())
    values = {
        "sandbox_node_attestation_enabled": True,
        "sandbox_node_attestation_public_key_path": str(public_path),
        "sandbox_node_attestation_expected_node_id": "node-a",
        "sandbox_node_attestation_verifier_command_json": '["attest","{node_id}","{nonce}"]',
        "sandbox_node_attestation_allowed_measurements": "abc123",
        "sandbox_node_attestation_allowed_tee_types": "sev-snp",
    }
    for key, value in values.items():
        monkeypatch.setattr(settings, key, value)

    class Completed:
        returncode = 0
        stderr = ""
        stdout = ""

    def run(argv, **_kwargs):
        claims = {
            "node_id": argv[1],
            "nonce": argv[2],
            "issued_at": now,
            "expires_at": now + 60,
            "verdict": "verified",
            "tee_type": "sev-snp",
            "measurement": "abc123",
            "quote_digest": "a" * 64,
            "verifier_id": "attestation.example/v1",
        }
        payload = json.dumps(claims, separators=(",", ":")).encode()
        Completed.stdout = json.dumps(
            {
                "payload": base64.b64encode(payload).decode(),
                "signature": base64.b64encode(private.sign(payload)).decode(),
            }
        )
        return Completed()

    monkeypatch.setattr(attestation_module.subprocess, "run", run)
    evidence = NodeAttestationVerifier().verify(now=now)
    assert evidence["node_attestation"] == "verified"
    assert evidence["attestation_evidence"] == "challenge-response"

    monkeypatch.setattr(attestation_module.secrets, "token_urlsafe", lambda _size: "wrong")
    original_run = run

    def wrong_nonce(argv, **kwargs):
        completed = original_run(argv, **kwargs)
        envelope = json.loads(completed.stdout)
        claims = json.loads(base64.b64decode(envelope["payload"]))
        claims["nonce"] = "not-the-challenge"
        payload = json.dumps(claims, separators=(",", ":")).encode()
        completed.stdout = json.dumps(
            {
                "payload": base64.b64encode(payload).decode(),
                "signature": base64.b64encode(private.sign(payload)).decode(),
            }
        )
        return completed

    monkeypatch.setattr(attestation_module.subprocess, "run", wrong_nonce)
    with pytest.raises(NodeAttestationError, match="challenge"):
        NodeAttestationVerifier().verify(now=now)
