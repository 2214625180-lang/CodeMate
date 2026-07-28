import base64
import hashlib
import json
import socket
from uuid import uuid4
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core.config import settings


def assess_mcp_compliance(*, include_runtime: bool = False) -> dict[str, Any]:
    controls = [
        control("MCP-SBX-001", "Sandbox broker isolation enabled", settings.mcp_sandbox_enabled),
        control(
            "MCP-SBX-002",
            "Main process delegates MCP protocol calls to broker",
            settings.mcp_sandbox_enabled
            and not settings.mcp_sandbox_broker_mode
            and bool((settings.mcp_sandbox_broker_url or "").strip()),
        ),
        control(
            "MCP-SBX-003",
            "Broker authentication configured",
            len((settings.mcp_sandbox_broker_token or "").strip()) >= 32,
        ),
        control(
            "MCP-SBX-004",
            "General worker delegates sandbox execution to a credential-isolated broker",
            bool((settings.sandbox_execution_broker_url or "").strip())
            and len((settings.sandbox_execution_broker_token or "").strip()) >= 32,
        ),
        control(
            "MCP-EGR-001",
            "Egress proxy configured",
            bool((settings.mcp_egress_proxy_url or "").strip()),
        ),
        control(
            "MCP-EGR-002",
            "Egress proxy authentication configured",
            len((settings.mcp_egress_proxy_token or "").strip()) >= 32,
        ),
        control(
            "MCP-EGR-003",
            "Only TLS port 443 is allowed",
            settings.mcp_egress_port_allowlist == {443},
            evidence={"ports": sorted(settings.mcp_egress_port_allowlist)},
        ),
        control(
            "MCP-EGR-004",
            "Explicit egress host allowlist configured",
            bool(settings.mcp_registry_host_allowlist),
            evidence={"host_count": len(settings.mcp_registry_host_allowlist)},
        ),
        control(
            "MCP-EGR-005",
            "Private networks denied and HTTPS required",
            not settings.mcp_registry_allow_private_networks
            and settings.mcp_registry_require_https,
        ),
        control(
            "MCP-CMP-001",
            "Continuous compliance scheduling enabled",
            settings.mcp_compliance_enabled,
            evidence={"interval_seconds": settings.mcp_compliance_interval_seconds},
        ),
    ]
    if include_runtime:
        controls.extend(runtime_controls())
    generated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": 1,
        "generated_at": generated_at,
        "environment": settings.app_env,
        "status": "compliant" if all(item["status"] == "passed" for item in controls) else "non_compliant",
        "controls": controls,
    }
    report["report_sha256"] = report_sha256(report)
    return report


def scan_and_persist(*, include_runtime: bool = True) -> dict[str, Any]:
    report = assess_mcp_compliance(include_runtime=include_runtime)
    destination = Path(settings.mcp_compliance_report_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(destination)
    history = destination.parent / "history"
    history.mkdir(parents=True, exist_ok=True)
    history_name = (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        + f"-{report['report_sha256']}.json"
    )
    (history / history_name).write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    purge_compliance_history(history)
    from app.core.audit import emit_security_audit_record

    emit_security_audit_record(
        {
            "id": str(uuid4()),
            "timestamp": report["generated_at"],
            "eventType": "mcp_continuous_compliance_scan",
            "outcome": "success" if report["status"] == "compliant" else "failure",
            "actor": {"provider": "system", "login": "compliance-worker", "role": "service"},
            "status": report["status"],
            "metadata": {
                "reportSha256": report["report_sha256"],
                "failedControls": [
                    item["id"] for item in report["controls"] if item["status"] == "failed"
                ],
            },
        }
    )
    return report


def latest_compliance_report() -> dict[str, Any] | None:
    path = Path(settings.mcp_compliance_report_path)
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    stored_hash = report.get("report_sha256")
    if not stored_hash or stored_hash != report_sha256(report):
        return None
    return report


def compliance_readiness() -> dict[str, Any]:
    report = latest_compliance_report()
    if report is None:
        return {"status": "failed", "detail": "No integrity-valid compliance report"}
    try:
        generated = datetime.fromisoformat(str(report["generated_at"]))
        age = max(0.0, (datetime.now(timezone.utc) - generated).total_seconds())
    except (KeyError, TypeError, ValueError):
        return {"status": "failed", "detail": "Compliance report timestamp is invalid"}
    ok = report.get("status") == "compliant" and age <= max(
        60, settings.mcp_compliance_stale_seconds
    )
    return {
        "status": "ok" if ok else "failed",
        "compliance_status": report.get("status"),
        "age_seconds": round(age, 3),
        "report_sha256": report.get("report_sha256"),
    }


def runtime_controls() -> list[dict[str, Any]]:
    broker_ok = False
    broker_detail = "not configured"
    broker_url = (settings.mcp_sandbox_broker_url or "").rstrip("/")
    if broker_url:
        try:
            response = httpx.get(
                f"{broker_url}/health",
                timeout=5,
                follow_redirects=False,
                trust_env=False,
            )
            payload = response.json()
            broker_ok = (
                response.status_code == 200
                and payload.get("isolation") == "sandbox-broker"
                and payload.get("egress") == "proxy-enforced"
            )
            broker_detail = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001 - report dependency failure.
            broker_detail = f"{type(exc).__name__}: {exc}"[:300]
    gateway_ok = False
    denial_ok = False
    gateway_detail = "not configured"
    proxy = urlsplit(settings.mcp_egress_proxy_url or "")
    if proxy.hostname:
        try:
            with socket.create_connection(
                (proxy.hostname, proxy.port or 8080),
                timeout=max(1.0, settings.mcp_egress_connect_timeout_seconds),
            ):
                gateway_ok = True
                gateway_detail = "TCP reachable"
            denial_ok = gateway_denies_unapproved_target(proxy.hostname, proxy.port or 8080)
        except OSError as exc:
            gateway_detail = f"{type(exc).__name__}: {exc}"[:300]
    code_broker_ok = False
    code_broker_detail = "not configured"
    code_broker_url = (settings.sandbox_execution_broker_url or "").rstrip("/")
    if code_broker_url:
        try:
            response = httpx.get(
                f"{code_broker_url}/health",
                timeout=5,
                follow_redirects=False,
                trust_env=False,
            )
            payload = response.json()
            code_broker_ok = (
                response.status_code == 200
                and payload.get("isolation") == "managed-remote-execution"
                and payload.get("transport") == "mutual-tls"
                and payload.get("workload_identity") == "ed25519-request-bound"
            )
            code_broker_detail = f"HTTP {response.status_code}"
        except Exception as exc:  # noqa: BLE001 - report dependency failure.
            code_broker_detail = f"{type(exc).__name__}: {exc}"[:300]
    return [
        control(
            "MCP-SBX-RT-001",
            "Sandbox broker runtime attestation",
            broker_ok,
            evidence={"detail": broker_detail},
        ),
        control(
            "MCP-EGR-RT-001",
            "Egress gateway runtime reachability",
            gateway_ok,
            evidence={"detail": gateway_detail},
        ),
        control(
            "MCP-EGR-RT-002",
            "Egress gateway denies an unapproved private target",
            denial_ok,
        ),
        control(
            "MCP-SBX-RT-002",
            "Managed remote code sandbox runtime attestation",
            code_broker_ok,
            evidence={"detail": code_broker_detail},
        ),
    ]


def gateway_denies_unapproved_target(host: str, port: int) -> bool:
    credentials = base64.b64encode(
        f"codemate:{settings.mcp_egress_proxy_token or ''}".encode()
    ).decode()
    request = (
        "CONNECT 127.0.0.1:443 HTTP/1.1\r\n"
        "Host: 127.0.0.1:443\r\n"
        f"Proxy-Authorization: Basic {credentials}\r\n\r\n"
    ).encode()
    try:
        with socket.create_connection(
            (host, port), timeout=max(1.0, settings.mcp_egress_connect_timeout_seconds)
        ) as connection:
            connection.sendall(request)
            response = connection.recv(512)
        return response.startswith(b"HTTP/1.1 403")
    except OSError:
        return False


def purge_compliance_history(directory: Path) -> None:
    cutoff = datetime.now(timezone.utc).timestamp() - max(
        1, settings.mcp_compliance_retention_days
    ) * 86400
    for path in directory.glob("*.json"):
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            continue


def control(
    control_id: str,
    title: str,
    passed: bool,
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": control_id,
        "title": title,
        "status": "passed" if passed else "failed",
        "evidence": evidence or {},
    }


def report_sha256(report: dict[str, Any]) -> str:
    canonical = {key: value for key, value in report.items() if key != "report_sha256"}
    serialized = json.dumps(canonical, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(serialized.encode()).hexdigest()
