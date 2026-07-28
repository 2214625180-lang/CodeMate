#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def parse_argv(value: str | None, name: str) -> list[str]:
    if not value:
        raise ValueError(f"{name} is required")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be a JSON argv array") from exc
    if not isinstance(parsed, list) or not parsed or not all(isinstance(item, str) for item in parsed):
        raise ValueError(f"{name} must be a non-empty JSON argv array")
    return parsed


def run_logged(
    name: str,
    command: list[str],
    *,
    output_dir: Path,
    timeout: float = 600,
) -> dict[str, Any]:
    started = time.perf_counter()
    stdout_path = output_dir / f"{name}.stdout.log"
    stderr_path = output_dir / f"{name}.stderr.log"
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        stdout, stderr, exit_code = completed.stdout, completed.stderr, completed.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        stdout, stderr, exit_code = "", f"{type(exc).__name__}: {exc}", 124
    stdout_path.write_text(stdout, encoding="utf-8")
    stderr_path.write_text(stderr, encoding="utf-8")
    return {
        "name": name,
        "status": "passed" if exit_code == 0 else "failed",
        "exit_code": exit_code,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "stdout": stdout_path.name,
        "stderr": stderr_path.name,
    }


def kubectl(args: argparse.Namespace, *values: str, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    command = ["kubectl", "--context", args.context]
    if args.namespace:
        command.extend(["-n", args.namespace])
    command.extend(values)
    return subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def kubectl_json(args: argparse.Namespace, *values: str) -> dict[str, Any]:
    completed = kubectl(args, *values, "-o", "json")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr[-1000:])
    value = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise RuntimeError("kubectl returned a non-object document")
    return value


def ready_pods(document: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for pod in document.get("items") or []:
        conditions = (pod.get("status") or {}).get("conditions") or []
        ready = any(
            value.get("type") == "Ready" and value.get("status") == "True"
            for value in conditions
        )
        if ready and not (pod.get("metadata") or {}).get("deletionTimestamp"):
            result.append(pod)
    return result


def collect_inventory(args: argparse.Namespace) -> dict[str, Any]:
    pods_document = kubectl_json(args, "get", "pods", "-l", f"app={args.app_label}")
    pods = ready_pods(pods_document)
    hpa = kubectl_json(args, "get", "hpa", args.hpa)
    pdb = kubectl_json(args, "get", "pdb", args.pdb)
    certificate = kubectl_json(args, "get", "certificate", args.certificate)
    nodes = sorted(
        {
            str((pod.get("spec") or {}).get("nodeName"))
            for pod in pods
            if (pod.get("spec") or {}).get("nodeName")
        }
    )
    zones = sorted(
        {
            str(
                ((pod.get("metadata") or {}).get("labels") or {}).get(
                    "topology.kubernetes.io/zone"
                )
            )
            for pod in pods
            if ((pod.get("metadata") or {}).get("labels") or {}).get(
                "topology.kubernetes.io/zone"
            )
        }
    )
    # Pod labels do not normally inherit node zones, so query nodes when needed.
    if len(zones) < args.min_zones:
        node_zones = []
        for node in nodes:
            node_doc = kubectl_json(args, "get", "node", node)
            zone = ((node_doc.get("metadata") or {}).get("labels") or {}).get(
                "topology.kubernetes.io/zone"
            )
            if zone:
                node_zones.append(str(zone))
        zones = sorted(set(node_zones))
    hpa_spec = hpa.get("spec") or {}
    pdb_spec = pdb.get("spec") or {}
    certificate_ready = any(
        value.get("type") == "Ready" and value.get("status") == "True"
        for value in (certificate.get("status") or {}).get("conditions") or []
    )
    passed = bool(
        len(pods) >= args.min_replicas
        and len(nodes) >= args.min_nodes
        and len(zones) >= args.min_zones
        and int(hpa_spec.get("minReplicas") or 0) >= args.min_replicas
        and int(hpa_spec.get("maxReplicas") or 0) > int(hpa_spec.get("minReplicas") or 0)
        and int(pdb_spec.get("minAvailable") or 0) >= 2
        and certificate_ready
    )
    return {
        "status": "passed" if passed else "failed",
        "ready_replicas": len(pods),
        "pod_uids": sorted(str((pod.get("metadata") or {}).get("uid")) for pod in pods),
        "nodes": nodes,
        "zones": zones,
        "hpa": {
            "min_replicas": hpa_spec.get("minReplicas"),
            "max_replicas": hpa_spec.get("maxReplicas"),
            "current_replicas": (hpa.get("status") or {}).get("currentReplicas"),
            "desired_replicas": (hpa.get("status") or {}).get("desiredReplicas"),
        },
        "pdb": {
            "min_available": pdb_spec.get("minAvailable"),
            "disruptions_allowed": (pdb.get("status") or {}).get("disruptionsAllowed"),
        },
        "certificate": {
            "ready": certificate_ready,
            "not_after": (certificate.get("status") or {}).get("notAfter"),
            "renewal_time": (certificate.get("status") or {}).get("renewalTime"),
        },
    }


def inventory_gate(args: argparse.Namespace, output_dir: Path, name: str) -> dict[str, Any]:
    started = time.perf_counter()
    artifact = output_dir / f"{name}.json"
    try:
        inventory = collect_inventory(args)
        status = inventory["status"]
    except Exception as exc:  # noqa: BLE001 - preserve diagnostic evidence.
        inventory = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        status = "failed"
    artifact.write_text(json.dumps(inventory, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "name": name,
        "status": status,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "artifact": artifact.name,
    }


def health_gate(args: argparse.Namespace, output_dir: Path, name: str) -> dict[str, Any]:
    started = time.perf_counter()
    artifact = output_dir / f"{name}.json"
    try:
        with httpx.Client(
            verify=args.ca,
            cert=(args.cert, args.key),
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = client.get(f"{args.url.rstrip('/')}/health")
        body = response.json()
        status = "passed" if response.status_code == 200 and body.get("status") == "ok" else "failed"
        evidence = {
            "status": status,
            "status_code": response.status_code,
            "instance": response.headers.get("X-CodeMate-Execution-Plane-Instance"),
            "body": body,
        }
    except Exception as exc:  # noqa: BLE001
        status = "failed"
        evidence = {"status": status, "error": f"{type(exc).__name__}: {exc}"}
    artifact.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "name": name,
        "status": status,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "artifact": artifact.name,
    }


def permission_gate(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    required = (
        ("get", "pods"),
        ("delete", "pods"),
        ("create", "pods/exec"),
        ("get", "pods/log"),
        ("get", "deployments.apps"),
        ("watch", "deployments.apps"),
        ("patch", "horizontalpodautoscalers.autoscaling"),
        ("get", "poddisruptionbudgets.policy"),
        ("get", "certificates.cert-manager.io"),
        ("patch", "certificates.cert-manager.io"),
        ("get", "events"),
        ("list", "events"),
        ("get", "nodes"),
    )
    evidence = []
    for verb, resource in required:
        completed = kubectl(args, "auth", "can-i", verb, resource)
        allowed = completed.returncode == 0 and completed.stdout.strip().lower() == "yes"
        evidence.append({"verb": verb, "resource": resource, "allowed": allowed})
    passed = all(value["allowed"] for value in evidence)
    artifact = output_dir / "kubernetes-permissions.json"
    artifact.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "name": "kubernetes-permissions",
        "status": "passed" if passed else "failed",
        "duration_seconds": 0,
        "artifact": artifact.name,
    }


def probe_command(
    args: argparse.Namespace,
    mode: str,
    output: Path,
    *,
    requests: int | None = None,
    sleep_seconds: float | None = None,
    min_success_rate: float | None = None,
) -> list[str]:
    command = [
        sys.executable,
        "scripts/sandbox_execution_probe.py",
        mode,
        "--url",
        args.url,
        "--ca",
        args.ca,
        "--cert",
        args.cert,
        "--key",
        args.key,
        "--workload-key",
        args.workload_key,
        "--image",
        args.image,
        "--issuer",
        args.issuer,
        "--subject",
        args.subject,
        "--audience",
        args.audience,
        "--runtime",
        args.runtime,
        "--requests",
        str(requests or args.requests),
        "--concurrency",
        str(args.concurrency),
        "--fanout",
        str(args.fanout),
        "--min-instances",
        str(args.min_instances),
        "--sleep-seconds",
        str(args.sleep_seconds if sleep_seconds is None else sleep_seconds),
        "--min-success-rate",
        str(args.min_success_rate if min_success_rate is None else min_success_rate),
        "--max-p95-ms",
        str(args.max_p95_ms),
        "--retry-timeout-seconds",
        str(args.execution_retry_timeout_seconds),
        "--output",
        str(output),
    ]
    return command


def disruptive_load_gate(
    args: argparse.Namespace,
    output_dir: Path,
    name: str,
    injection: list[str],
    *,
    requests: int | None = None,
    settle_seconds: float = 2,
) -> dict[str, Any]:
    started = time.perf_counter()
    probe_output = output_dir / f"{name}.json"
    stdout_path = output_dir / f"{name}.stdout.log"
    stderr_path = output_dir / f"{name}.stderr.log"
    command = probe_command(
        args,
        "load",
        probe_output,
        requests=max(requests or args.requests, args.concurrency * 4),
        sleep_seconds=max(5.0, args.sleep_seconds),
        min_success_rate=args.fault_min_success_rate,
    )
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open(
        "w", encoding="utf-8"
    ) as stderr:
        process = subprocess.Popen(command, cwd=ROOT, stdout=stdout, stderr=stderr, env=os.environ)
        time.sleep(max(0.1, settle_seconds))
        injection_result = subprocess.run(
            injection,
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
        try:
            probe_exit = process.wait(timeout=args.drill_timeout_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            probe_exit = 124
    injection_artifact = output_dir / f"{name}-injection.json"
    injection_artifact.write_text(
        json.dumps(
            {
                "command_sha256": sha256_text("\0".join(injection)),
                "exit_code": injection_result.returncode,
                "stdout": injection_result.stdout[-2000:],
                "stderr": injection_result.stderr[-2000:],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    passed = probe_exit == 0 and injection_result.returncode == 0
    return {
        "name": name,
        "status": "passed" if passed else "failed",
        "exit_code": probe_exit,
        "injection_exit_code": injection_result.returncode,
        "duration_seconds": round(time.perf_counter() - started, 3),
        "artifact": probe_output.name,
        "injection_artifact": injection_artifact.name,
        "stdout": stdout_path.name,
        "stderr": stderr_path.name,
    }


def pod_failure_gate(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    pods = ready_pods(kubectl_json(args, "get", "pods", "-l", f"app={args.app_label}"))
    if not pods:
        return {"name": "pod-failure", "status": "failed", "detail": "No ready pod"}
    pod = str((pods[0].get("metadata") or {}).get("name"))
    injection = [
        "kubectl",
        "--context",
        args.context,
        "-n",
        args.namespace,
        "delete",
        "pod",
        pod,
        "--wait=false",
    ]
    result = disruptive_load_gate(args, output_dir, "pod-failure", injection)
    rollout = kubectl(
        args,
        "rollout",
        "status",
        f"deployment/{args.deployment}",
        f"--timeout={int(args.recovery_timeout_seconds)}s",
        timeout=args.recovery_timeout_seconds + 10,
    )
    (output_dir / "pod-failure-rollout.log").write_text(
        rollout.stdout + rollout.stderr, encoding="utf-8"
    )
    if rollout.returncode != 0:
        result["status"] = "failed"
    result["rollout_exit_code"] = rollout.returncode
    return result


def scale_gate(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    started = time.perf_counter()
    hpa = kubectl_json(args, "get", "hpa", args.hpa)
    original = int((hpa.get("spec") or {}).get("minReplicas") or args.min_replicas)
    target = max(args.scale_replicas, original + 1)
    evidence: dict[str, Any] = {"original_replicas": original, "target_replicas": target}
    failed = False
    try:
        scaled = kubectl(
            args,
            "patch",
            "hpa",
            args.hpa,
            "--type=merge",
            "-p",
            json.dumps({"spec": {"minReplicas": target}}),
        )
        evidence["scale_exit_code"] = scaled.returncode
        deadline = time.monotonic() + args.recovery_timeout_seconds
        observed = collect_inventory(args)
        while observed["ready_replicas"] < target and time.monotonic() < deadline:
            time.sleep(2)
            observed = collect_inventory(args)
        evidence["observed"] = observed
        if scaled.returncode != 0 or observed["ready_replicas"] < target:
            failed = True
    except Exception as exc:  # noqa: BLE001
        failed = True
        evidence["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        restored = kubectl(
            args,
            "patch",
            "hpa",
            args.hpa,
            "--type=merge",
            "-p",
            json.dumps({"spec": {"minReplicas": original}}),
        )
        evidence["restore_exit_code"] = restored.returncode
        if restored.returncode != 0:
            failed = True
    artifact = output_dir / "scale-out.json"
    artifact.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    return {
        "name": "scale-out",
        "status": "failed" if failed else "passed",
        "duration_seconds": round(time.perf_counter() - started, 3),
        "artifact": artifact.name,
    }


def certificate_rotation_gate(args: argparse.Namespace, output_dir: Path) -> dict[str, Any]:
    certificate = kubectl_json(args, "get", "certificate", args.certificate)
    secret_name = str((certificate.get("spec") or {}).get("secretName") or "")
    before_revision = (certificate.get("status") or {}).get("revision")
    before_inventory = collect_inventory(args)
    command = parse_argv(args.certificate_renew_command_json, "certificate renew command")
    result = disruptive_load_gate(
        args,
        output_dir,
        "certificate-rotation-load",
        command,
        requests=max(60, args.requests),
        settle_seconds=1,
    )
    deadline = time.monotonic() + args.recovery_timeout_seconds
    after_certificate = certificate
    after_inventory = before_inventory
    while time.monotonic() < deadline:
        after_certificate = kubectl_json(args, "get", "certificate", args.certificate)
        after_inventory = collect_inventory(args)
        secret_changed = (after_certificate.get("status") or {}).get("revision") != before_revision
        pods_changed = set(after_inventory.get("pod_uids") or []) != set(
            before_inventory.get("pod_uids") or []
        )
        if secret_changed and pods_changed and after_inventory.get("status") == "passed":
            break
        time.sleep(2)
    evidence = {
        "secret_name": secret_name,
        "certificate_revision_before": before_revision,
        "certificate_revision_after": (after_certificate.get("status") or {}).get("revision"),
        "secret_rotated": (after_certificate.get("status") or {}).get("revision")
        != before_revision,
        "pods_rolled": set(after_inventory.get("pod_uids") or [])
        != set(before_inventory.get("pod_uids") or []),
        "before": before_inventory,
        "after": after_inventory,
    }
    artifact = output_dir / "certificate-rotation.json"
    artifact.write_text(json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8")
    if not all((evidence["secret_rotated"], evidence["pods_rolled"], after_inventory["status"] == "passed")):
        result["status"] = "failed"
    result["name"] = "certificate-rotation"
    result["rotation_artifact"] = artifact.name
    return result


def negative_control_gates(
    args: argparse.Namespace, output_dir: Path, backend: str
) -> list[dict[str, Any]]:
    pods = ready_pods(kubectl_json(args, "get", "pods", "-l", f"app={args.app_label}"))
    if not pods:
        return [{"name": "negative-controls", "status": "failed", "detail": "No ready pod"}]
    pod = str((pods[0].get("metadata") or {}).get("name"))
    controls = [
        ("wrong-slsa-source", ["--image", args.image]),
        ("unsigned-image", ["--image", args.unsigned_image]),
        ("wrong-node", []),
    ]
    if backend == "firecracker":
        controls.append(("tampered-rootfs", []))
    gates = []
    for control, extra in controls:
        command = [
            "kubectl",
            "--context",
            args.context,
            "-n",
            args.namespace,
            "exec",
            pod,
            "--",
            "python",
            "-m",
            "app.sandbox.qualification_controls",
            control,
            *extra,
        ]
        gates.append(
            run_logged(
                f"negative-{control}",
                command,
                output_dir=output_dir,
                timeout=180,
            )
        )
    return gates


def diagnostics(args: argparse.Namespace, output_dir: Path) -> None:
    commands = {
        "kubectl-pods-wide": ["get", "pods", "-l", f"app={args.app_label}", "-o", "wide"],
        "kubectl-deployment": ["describe", "deployment", args.deployment],
        "kubectl-hpa": ["describe", "hpa", args.hpa],
        "kubectl-pdb": ["describe", "pdb", args.pdb],
        "kubectl-certificate": ["describe", "certificate", args.certificate],
        "kubectl-events": ["get", "events", "--sort-by=.lastTimestamp"],
        "execution-plane-logs": ["logs", "-l", f"app={args.app_label}", "--prefix", "--tail=2000"],
    }
    for name, values in commands.items():
        result = kubectl(args, *values, timeout=180)
        (output_dir / f"{name}.log").write_text(
            result.stdout + result.stderr, encoding="utf-8"
        )


def write_manifest(output_dir: Path) -> Path:
    entries = []
    for path in sorted(output_dir.iterdir()):
        if path.is_file() and path.name not in {"manifest.sha256", "manifest.bundle.json"}:
            entries.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}")
    manifest = output_dir / "manifest.sha256"
    manifest.write_text("\n".join(entries) + "\n", encoding="utf-8")
    return manifest


def write_markdown(report: dict[str, Any], output_dir: Path) -> None:
    rows = [
        "# Sandbox HA Staging Qualification",
        "",
        f"- Decision: **{report['decision'].upper()}**",
        f"- Cluster context: `{report['cluster_context']}`",
        f"- Namespace: `{report['namespace']}`",
        f"- Started: `{report['started_at']}`",
        f"- Finished: `{report['finished_at']}`",
        "",
        "| Gate | Result | Duration |",
        "|---|---|---:|",
    ]
    rows.extend(
        f"| {gate['name']} | {gate['status']} | {gate.get('duration_seconds', 0)}s |"
        for gate in report["gates"]
    )
    rows.extend(["", "## Notes", ""])
    rows.extend(f"- {note}" for note in report.get("notes") or ["None"])
    rows.extend(["", "Artifacts are integrity-bound by `manifest.sha256`.", ""])
    (output_dir / "qualification.md").write_text("\n".join(rows), encoding="utf-8")


def skipped(name: str, reason: str) -> dict[str, Any]:
    return {"name": name, "status": "incomplete", "duration_seconds": 0, "detail": reason}


def release_qualified(
    gates: list[dict[str, Any]], *, rehearsal: bool, evidence_signed: bool
) -> bool:
    return bool(
        gates
        and all(gate.get("status") == "passed" for gate in gates)
        and not rehearsal
        and evidence_signed
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Run Sandbox HA staging qualification and evidence capture")
    value.add_argument("--execute", action="store_true")
    value.add_argument("--context", default=os.getenv("SANDBOX_QUALIFICATION_KUBE_CONTEXT"))
    value.add_argument("--namespace", default=os.getenv("SANDBOX_QUALIFICATION_NAMESPACE", "codemate-sandbox"))
    value.add_argument("--url", default=os.getenv("SANDBOX_QUALIFICATION_URL"))
    value.add_argument("--ca", default=os.getenv("SANDBOX_QUALIFICATION_CA_PATH"))
    value.add_argument("--cert", default=os.getenv("SANDBOX_QUALIFICATION_CERT_PATH"))
    value.add_argument("--key", default=os.getenv("SANDBOX_QUALIFICATION_KEY_PATH"))
    value.add_argument("--workload-key", default=os.getenv("SANDBOX_QUALIFICATION_WORKLOAD_KEY_PATH"))
    value.add_argument("--issuer", default=os.getenv("SANDBOX_WORKLOAD_IDENTITY_ISSUER", "codemate-staging"))
    value.add_argument("--subject", default=os.getenv("SANDBOX_WORKLOAD_IDENTITY_SUBJECT", "spiffe://codemate/staging/code-sandbox"))
    value.add_argument("--audience", default=os.getenv("SANDBOX_WORKLOAD_IDENTITY_AUDIENCE", "codemate-sandbox-execution-plane"))
    value.add_argument("--image", default=os.getenv("SANDBOX_NODE_IMAGE"))
    value.add_argument("--unsigned-image", default=os.getenv("SANDBOX_QUALIFICATION_UNSIGNED_IMAGE"))
    value.add_argument("--runtime", choices=("docker", "gvisor", "firecracker"), default="docker")
    value.add_argument("--deployment", default="sandbox-execution-plane")
    value.add_argument("--app-label", default="sandbox-execution-plane")
    value.add_argument("--hpa", default="sandbox-execution-plane")
    value.add_argument("--pdb", default="sandbox-execution-plane")
    value.add_argument("--certificate", default="sandbox-execution-plane-mtls")
    value.add_argument("--requests", type=int, default=60)
    value.add_argument("--concurrency", type=int, default=15)
    value.add_argument("--fanout", type=int, default=15)
    value.add_argument("--sleep-seconds", type=float, default=0.2)
    value.add_argument("--min-success-rate", type=float, default=0.99)
    value.add_argument("--fault-min-success-rate", type=float, default=0.95)
    value.add_argument("--max-p95-ms", type=float, default=15000)
    value.add_argument("--min-replicas", type=int, default=3)
    value.add_argument("--min-instances", type=int, default=2)
    value.add_argument("--min-nodes", type=int, default=2)
    value.add_argument("--min-zones", type=int, default=2)
    value.add_argument("--scale-replicas", type=int, default=5)
    value.add_argument("--drill-timeout-seconds", type=float, default=600)
    value.add_argument("--recovery-timeout-seconds", type=float, default=300)
    value.add_argument("--execution-retry-timeout-seconds", type=float, default=180)
    value.add_argument("--redis-failover-command-json", default=os.getenv("SANDBOX_REDIS_FAILOVER_COMMAND_JSON"))
    value.add_argument(
        "--certificate-renew-command-json",
        default=os.getenv("SANDBOX_CERTIFICATE_RENEW_COMMAND_JSON"),
    )
    value.add_argument("--skip-faults", action="store_true")
    value.add_argument("--skip-certificate-rotation", action="store_true")
    value.add_argument("--skip-negative-controls", action="store_true")
    value.add_argument("--rehearsal", action="store_true")
    value.add_argument("--sign-evidence", action="store_true")
    value.add_argument(
        "--output-dir",
        default=f"artifacts/sandbox-ha-qualification/{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
    )
    return value


def main() -> None:
    args = parser().parse_args()
    if not args.execute:
        raise SystemExit("Refusing to run destructive Sandbox HA drills without --execute")
    missing = [
        name
        for name in ("context", "url", "ca", "cert", "key", "workload_key", "image")
        if not getattr(args, name)
    ]
    if missing:
        raise SystemExit(f"Missing Sandbox HA qualification settings: {', '.join(missing)}")
    if not args.rehearsal and not args.url.startswith("https://"):
        raise SystemExit("A qualifying execution plane must use HTTPS")
    current_context = subprocess.run(
        ["kubectl", "config", "current-context"], capture_output=True, text=True, check=False
    ).stdout.strip()
    if current_context != args.context:
        raise SystemExit(
            f"Refusing cluster mutation: current context {current_context!r} != expected {args.context!r}"
        )
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    started_at = utc_now()
    gates: list[dict[str, Any]] = []
    notes: list[str] = []
    try:
        gates.append(inventory_gate(args, output_dir, "inventory-before"))
        gates.append(permission_gate(args, output_dir))
        gates.append(health_gate(args, output_dir, "health-before"))
        preflight_ok = all(gate["status"] == "passed" for gate in gates)
        if preflight_ok:
            gates.append(
                run_logged(
                    "idempotency",
                    probe_command(args, "idempotency", output_dir / "idempotency.json"),
                    output_dir=output_dir,
                )
            )
            gates.append(
                run_logged(
                    "baseline-load",
                    probe_command(args, "load", output_dir / "baseline-load.json"),
                    output_dir=output_dir,
                )
            )
            baseline_ok = gates[-1]["status"] == "passed" and gates[-2]["status"] == "passed"
            if not baseline_ok:
                gates.extend(
                    [
                        skipped("pod-failure", "Idempotency or baseline load gate failed"),
                        skipped("redis-failover", "Idempotency or baseline load gate failed"),
                        skipped("post-redis-idempotency", "Idempotency or baseline load gate failed"),
                        skipped("scale-out", "Idempotency or baseline load gate failed"),
                        skipped("certificate-rotation", "Idempotency or baseline load gate failed"),
                    ]
                )
            elif args.skip_faults:
                gates.extend(
                    [
                        skipped("pod-failure", "Fault drills explicitly skipped"),
                        skipped("redis-failover", "Fault drills explicitly skipped"),
                        skipped("post-redis-idempotency", "Fault drills explicitly skipped"),
                        skipped("scale-out", "Fault drills explicitly skipped"),
                    ]
                )
            else:
                gates.append(pod_failure_gate(args, output_dir))
                if gates[-1]["status"] == "passed":
                    try:
                        redis_command = parse_argv(
                            args.redis_failover_command_json,
                            "SANDBOX_REDIS_FAILOVER_COMMAND_JSON",
                        )
                        gates.append(
                            disruptive_load_gate(
                                args,
                                output_dir,
                                "redis-failover",
                                redis_command,
                                requests=max(60, args.requests),
                                settle_seconds=1,
                            )
                        )
                    except ValueError as exc:
                        gates.append(skipped("redis-failover", str(exc)))
                else:
                    gates.append(skipped("redis-failover", "Pod failure drill failed"))
                if gates[-1]["status"] == "passed":
                    gates.append(
                        run_logged(
                            "post-redis-idempotency",
                            probe_command(
                                args,
                                "idempotency",
                                output_dir / "post-redis-idempotency.json",
                            ),
                            output_dir=output_dir,
                        )
                    )
                else:
                    gates.append(
                        skipped("post-redis-idempotency", "Redis failover drill failed")
                    )
                if gates[-1]["status"] == "passed":
                    gates.append(scale_gate(args, output_dir))
                else:
                    gates.append(skipped("scale-out", "Previous HA fault drill failed"))
            if not baseline_ok:
                pass
            elif args.skip_certificate_rotation:
                gates.append(skipped("certificate-rotation", "Certificate rotation skipped"))
            else:
                try:
                    gates.append(certificate_rotation_gate(args, output_dir))
                except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
                    gates.append(
                        {
                            "name": "certificate-rotation",
                            "status": "failed",
                            "detail": f"{type(exc).__name__}: {exc}",
                        }
                    )
            health = read_json(output_dir / "health-before.json").get("body") or {}
            backend = str(health.get("backend") or "unknown")
            if args.skip_negative_controls:
                gates.append(skipped("negative-controls", "Negative controls skipped"))
            elif not args.unsigned_image:
                gates.append(skipped("negative-controls", "SANDBOX_QUALIFICATION_UNSIGNED_IMAGE is required"))
            else:
                gates.extend(negative_control_gates(args, output_dir, backend))
            gates.append(health_gate(args, output_dir, "health-after"))
            gates.append(inventory_gate(args, output_dir, "inventory-after"))
        else:
            gates.append(skipped("execution-drills", "Preflight failed"))
    finally:
        try:
            diagnostics(args, output_dir)
        except Exception as exc:  # noqa: BLE001
            notes.append(f"Diagnostic collection failed: {type(exc).__name__}: {exc}")

    qualified = release_qualified(
        gates,
        rehearsal=args.rehearsal,
        evidence_signed=args.sign_evidence,
    )
    if args.rehearsal:
        notes.append("Rehearsal evidence cannot qualify a release.")
    if not args.sign_evidence:
        notes.append("Unsigned evidence cannot qualify a release; use --sign-evidence.")
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = "unknown"
    report = {
        "schema_version": 1,
        "decision": "qualified" if qualified else "hold",
        "started_at": started_at,
        "finished_at": utc_now(),
        "cluster_context": args.context,
        "namespace": args.namespace,
        "git_commit": commit,
        "execution_plane_url_sha256": sha256_text(args.url),
        "workload_image": args.image,
        "gates": gates,
        "notes": notes,
    }
    (output_dir / "qualification.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    write_markdown(report, output_dir)
    manifest = write_manifest(output_dir)
    if args.sign_evidence:
        sign_command = [
            "cosign",
            "sign-blob",
            "--yes",
            "--bundle",
            str(output_dir / "manifest.bundle.json"),
        ]
        if os.getenv("COSIGN_KEY"):
            sign_command.extend(["--key", os.environ["COSIGN_KEY"]])
        sign_command.append(str(manifest))
        sign_result = subprocess.run(sign_command, cwd=ROOT, check=False)
        if sign_result.returncode != 0:
            qualified = False
            report["decision"] = "hold"
            report["notes"].append("Evidence manifest signing failed.")
            (output_dir / "qualification.json").write_text(
                json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
            )
            write_markdown(report, output_dir)
            write_manifest(output_dir)
    print(json.dumps(report, indent=2, sort_keys=True))
    if not qualified:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
