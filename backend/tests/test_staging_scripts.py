import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.sandbox.qualification_controls import rejected
from app.sandbox.runner import SandboxService
from app.sandbox.supply_chain import SupplyChainVerificationError
from app.sandbox.workspace_archive import extract_archive
from scripts.mcp_fault_injection import service_is_running
from scripts.mcp_container_compliance import static_controls
from scripts.run_sandbox_ha_qualification import parse_argv, ready_pods, release_qualified
from scripts.run_staging_qualification import run_gate, write_manifest
from scripts.sandbox_execution_probe import build_archive, percentile


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_fault_evidence_detects_service_state_in_array_and_json_lines():
    rows = [
        {"Service": "backend", "State": "running"},
        {"Service": "worker", "State": "exited"},
    ]
    assert service_is_running(json.dumps(rows), "backend") is True
    assert service_is_running("\n".join(json.dumps(row) for row in rows), "worker") is False
    assert service_is_running(json.dumps(rows), "missing") is False


def test_qualification_gate_failure_still_produces_integrity_artifacts(tmp_path):
    gate = run_gate(
        "missing-command",
        ["/definitely/not/a/command"],
        output_dir=tmp_path,
        env={},
    )
    (tmp_path / "report.json").write_text("{}", encoding="utf-8")
    write_manifest(tmp_path)

    assert gate["status"] == "failed"
    assert gate["exit_code"] == 127
    assert (tmp_path / "missing-command.stderr.log").exists()
    assert "report.json" in (tmp_path / "manifest.sha256").read_text(encoding="utf-8")


def test_container_compliance_fails_open_network_or_privileged_sandbox():
    config = {
        "networks": {"mcp_isolated": {"internal": False}},
        "services": {
            "mcp-sandbox": {
                "read_only": False,
                "cap_drop": [],
                "security_opt": [],
                "user": "0:0",
                "volumes": [{"source": "/var/run/docker.sock"}],
                "networks": {"default": None},
            },
            "mcp-egress": {},
        },
    }

    controls = static_controls(config)

    assert controls
    statuses = {item["id"]: item["status"] for item in controls}
    assert statuses["MCP-NET-001"] == "failed"
    assert statuses["MCP-SBX-CTR-004"] == "failed"
    assert statuses["MCP-SBX-CTR-005"] == "failed"
    assert statuses["MCP-SBX-NET-001"] == "failed"


def test_sandbox_qualification_helpers_are_strict_and_deterministic(tmp_path):
    assert parse_argv('["cmctl", "renew"]', "command") == ["cmctl", "renew"]
    with pytest.raises(ValueError, match="JSON argv"):
        parse_argv("cmctl renew", "command")
    with pytest.raises(ValueError, match="non-empty"):
        parse_argv("[]", "command")
    assert percentile([4, 1, 2, 3], 0.95) == 4
    archive, digest = build_archive(0)
    assert archive
    assert len(digest) == 64
    workspace = tmp_path / "workspace"
    extract_archive(
        archive,
        workspace,
        expected_sha256=digest,
        max_bytes=1024 * 1024,
        max_files=10,
    )
    service = SandboxService()
    dependency = service._dependency_install_command(workspace=workspace, command="npm test")
    assert dependency is None
    assert (
        service._test_shell_command(dependency_command=dependency, command="npm test")
        == "npm test"
    )


def test_sandbox_inventory_only_counts_ready_non_terminating_pods():
    pods = {
        "items": [
            {
                "metadata": {"name": "ready"},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            },
            {
                "metadata": {"name": "terminating", "deletionTimestamp": "now"},
                "status": {"conditions": [{"type": "Ready", "status": "True"}]},
            },
            {
                "metadata": {"name": "unready"},
                "status": {"conditions": [{"type": "Ready", "status": "False"}]},
            },
        ]
    }
    assert [pod["metadata"]["name"] for pod in ready_pods(pods)] == ["ready"]


def test_sandbox_release_requires_every_gate_and_signed_non_rehearsal_evidence():
    passed = [{"name": "ha", "status": "passed"}]
    assert release_qualified(passed, rehearsal=False, evidence_signed=True) is True
    assert release_qualified([], rehearsal=False, evidence_signed=True) is False
    assert release_qualified(passed, rehearsal=True, evidence_signed=True) is False
    assert release_qualified(passed, rehearsal=False, evidence_signed=False) is False
    assert release_qualified(
        [*passed, {"name": "redis", "status": "incomplete"}],
        rehearsal=False,
        evidence_signed=True,
    ) is False


def test_negative_control_must_observe_a_rejection():
    result = rejected(
        "expected",
        lambda: (_ for _ in ()).throw(SupplyChainVerificationError("rejected")),
    )
    assert result["status"] == "passed"
    with pytest.raises(RuntimeError, match="unexpectedly accepted"):
        rejected("accepted", lambda: None)


def test_sandbox_qualification_refuses_mutation_without_execute(tmp_path):
    completed = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts/run_sandbox_ha_qualification.py"),
            "--output-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode != 0
    assert "without --execute" in completed.stderr
    assert list(tmp_path.iterdir()) == []
