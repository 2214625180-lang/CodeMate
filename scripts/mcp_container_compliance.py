#!/usr/bin/env python3
import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def compose_config(args: argparse.Namespace) -> dict[str, Any]:
    command = ["docker", "compose"]
    if args.env_file:
        command.extend(["--env-file", args.env_file])
    for path in args.compose_file:
        command.extend(["-f", path])
    if args.project_name:
        command.extend(["--project-name", args.project_name])
    command.extend(["config", "--format", "json"])
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(completed.stdout)


def static_controls(config: dict[str, Any]) -> list[dict[str, Any]]:
    services = config.get("services") or {}
    networks = config.get("networks") or {}
    controls = []
    isolated = networks.get("mcp_isolated") or {}
    controls.append(check("MCP-NET-001", "MCP isolation network is internal", isolated.get("internal") is True))
    controls.append(
        check(
            "MCP-NET-002",
            "Code sandbox control network is internal",
            (networks.get("sandbox_control") or {}).get("internal") is True,
        )
    )
    for name in ("mcp-sandbox", "mcp-egress"):
        present = name in services
        service = services.get(name) or {}
        prefix = "MCP-SBX" if name == "mcp-sandbox" else "MCP-EGR"
        max_pids = 128 if name == "mcp-sandbox" else 64
        max_memory = 256 * 1024 * 1024 if name == "mcp-sandbox" else 128 * 1024 * 1024
        controls.extend(
            [
                check(f"{prefix}-CTR-001", f"{name} uses a read-only root filesystem", present and service.get("read_only") is True),
                check(f"{prefix}-CTR-002", f"{name} drops all Linux capabilities", present and "ALL" in (service.get("cap_drop") or [])),
                check(f"{prefix}-CTR-003", f"{name} forbids privilege escalation", present and "no-new-privileges:true" in (service.get("security_opt") or [])),
                check(f"{prefix}-CTR-004", f"{name} runs as a non-root UID", present and non_root(service.get("user"))),
                check(f"{prefix}-CTR-005", f"{name} has no host or persistent mounts", present and not bool(service.get("volumes"))),
                check(f"{prefix}-CTR-006", f"{name} has a bounded PID limit", present and 1 <= safe_int(service.get("pids_limit")) <= max_pids),
                check(f"{prefix}-CTR-007", f"{name} has a bounded memory limit", present and 1 <= safe_int(service.get("mem_limit")) <= max_memory),
                check(f"{prefix}-CTR-008", f"{name} exposes only ephemeral /tmp storage", present and set(service.get("tmpfs") or []) == {"/tmp"}),
            ]
        )
    sandbox_networks = set((services.get("mcp-sandbox") or {}).get("networks") or {})
    controls.append(
        check(
            "MCP-SBX-NET-001",
            "Sandbox broker is attached only to the internal MCP network",
            sandbox_networks == {"mcp_isolated"},
            evidence={"networks": sorted(sandbox_networks)},
        )
    )
    worker = services.get("worker") or {}
    worker_volumes = worker.get("volumes") or []
    controls.append(
        check(
            "MCP-SBX-WRK-001",
            "General worker has no host Docker socket",
            not any(
                str(item.get("source") if isinstance(item, dict) else item)
                == "/var/run/docker.sock"
                for item in worker_volumes
            ),
        )
    )
    code_sandbox = services.get("code-sandbox") or {}
    code_volumes = code_sandbox.get("volumes") or []
    code_environment = code_sandbox.get("environment") or {}
    forbidden_environment = (
        "MCP_",
        "DATABASE_",
        "AWS_",
        "SECURITY_AUDIT_",
        "EVALUATION_",
        "CODEMATE_",
    )
    controls.extend(
        [
            check(
                "MCP-SBX-WRK-002",
                "Code sandbox has no host Docker socket",
                not any(
                    str(item.get("source") if isinstance(item, dict) else item)
                    == "/var/run/docker.sock"
                    for item in code_volumes
                ),
            ),
            check(
                "MCP-SBX-WRK-003",
                "Code sandbox receives no MCP, database, cloud, SIEM or admin credentials",
                not any(
                    key.startswith(forbidden_environment) for key in code_environment
                ),
                evidence={"environment_keys": sorted(code_environment)},
            ),
            check(
                "MCP-SBX-WRK-004",
                "Code sandbox uses only control and dedicated execution-plane egress networks",
                set(code_sandbox.get("networks") or {})
                == {"sandbox_control", "execution_plane_egress"},
            ),
            check(
                "MCP-SBX-WRK-005",
                "Code sandbox uses read-only rootfs and no-new-privileges",
                code_sandbox.get("read_only") is True
                and "ALL" in (code_sandbox.get("cap_drop") or [])
                and "no-new-privileges:true" in (code_sandbox.get("security_opt") or []),
            ),
            check(
                "MCP-SBX-WRK-006",
                "Code sandbox runs as non-root",
                non_root(code_sandbox.get("user")),
            ),
            check(
                "MCP-SBX-WRK-007",
                "Code sandbox requires HTTPS, mTLS and workload identity credentials",
                str(code_environment.get("SANDBOX_EXECUTION_PLANE_URL", "")).startswith("https://")
                and all(
                    code_environment.get(key)
                    for key in (
                        "SANDBOX_EXECUTION_PLANE_CA_PATH",
                        "SANDBOX_EXECUTION_PLANE_CERT_PATH",
                        "SANDBOX_EXECUTION_PLANE_KEY_PATH",
                        "SANDBOX_WORKLOAD_IDENTITY_PRIVATE_KEY_PATH",
                    )
                ),
            ),
        ]
    )
    return controls


def non_root(value: Any) -> bool:
    user = str(value or "").split(":", 1)[0]
    return bool(user and user not in {"0", "root"})


def safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def check(
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate MCP sandbox container boundaries")
    parser.add_argument("--compose-file", action="append", default=[])
    parser.add_argument("--env-file")
    parser.add_argument("--project-name")
    parser.add_argument("--output")
    args = parser.parse_args()
    controls = static_controls(compose_config(args))
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "compliant" if all(item["status"] == "passed" for item in controls) else "non_compliant",
        "controls": controls,
    }
    canonical = json.dumps(report, separators=(",", ":"), sort_keys=True)
    report["report_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if report["status"] != "compliant":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
