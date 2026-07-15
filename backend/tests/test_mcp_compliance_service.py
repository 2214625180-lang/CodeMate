import json

from app.core.config import settings
from app.services.mcp_compliance_service import (
    assess_mcp_compliance,
    compliance_readiness,
    latest_compliance_report,
    scan_and_persist,
)


def configure_compliant(monkeypatch, tmp_path):
    values = {
        "app_env": "staging",
        "mcp_sandbox_enabled": True,
        "mcp_sandbox_broker_mode": False,
        "mcp_sandbox_broker_url": "http://mcp-sandbox:8090",
        "mcp_sandbox_broker_token": "b" * 32,
        "mcp_egress_proxy_url": "http://mcp-egress:8080",
        "mcp_egress_proxy_token": "e" * 32,
        "mcp_egress_allowed_ports": "443",
        "mcp_registry_allowed_hosts": "mcp.example.com",
        "mcp_registry_allow_private_networks": False,
        "mcp_registry_require_https": True,
        "mcp_compliance_enabled": True,
        "sandbox_execution_broker_url": "http://code-sandbox:8070",
        "sandbox_execution_broker_token": "x" * 32,
        "mcp_compliance_report_path": str(tmp_path / "compliance.json"),
        "mcp_compliance_stale_seconds": 900,
        "security_audit_log_path": str(tmp_path / "security.jsonl"),
    }
    for name, value in values.items():
        monkeypatch.setattr(settings, name, value)


def test_compliance_report_is_integrity_bound_and_readiness_aware(monkeypatch, tmp_path):
    configure_compliant(monkeypatch, tmp_path)

    report = scan_and_persist(include_runtime=False)

    assert report["status"] == "compliant"
    assert latest_compliance_report()["report_sha256"] == report["report_sha256"]
    assert compliance_readiness()["status"] == "ok"
    assert len(list((tmp_path / "history").glob("*.json"))) == 1

    path = tmp_path / "compliance.json"
    tampered = json.loads(path.read_text())
    tampered["status"] = "compliant-after-tamper"
    path.write_text(json.dumps(tampered))
    assert latest_compliance_report() is None
    assert compliance_readiness()["status"] == "failed"


def test_compliance_default_denies_missing_egress_controls(monkeypatch, tmp_path):
    configure_compliant(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "mcp_registry_allowed_hosts", "")

    report = assess_mcp_compliance(include_runtime=False)

    assert report["status"] == "non_compliant"
    assert next(item for item in report["controls"] if item["id"] == "MCP-EGR-004")[
        "status"
    ] == "failed"
