import base64
import hashlib
import json
import re
import subprocess
from pathlib import Path

from app.core.config import settings


class SupplyChainVerificationError(RuntimeError):
    pass


class SupplyChainVerifier:
    def verify(self, *, image: str, backend: str) -> dict[str, str]:
        if not settings.sandbox_supply_chain_enabled:
            return {"supply_chain": "disabled"}
        digest = _image_digest(image)
        if settings.sandbox_supply_chain_require_image_digest and not digest:
            raise SupplyChainVerificationError("Sandbox image must be pinned by sha256 digest")
        self._run(["verify", *self._identity_arguments(), image])
        evidence = {
            "supply_chain": "verified",
            "image": image,
            "image_digest": digest or "unavailable",
        }
        if settings.sandbox_supply_chain_require_slsa:
            completed = self._run(
                [
                    "verify-attestation",
                    "--type",
                    "slsaprovenance",
                    *self._identity_arguments(),
                    image,
                ]
            )
            source = (settings.sandbox_supply_chain_slsa_source or "").strip()
            statements = _attestation_statements(completed.stdout)
            if not statements:
                raise SupplyChainVerificationError("Cosign returned no decodable SLSA provenance")
            if source and not any(_statement_has_source(value, source) for value in statements):
                raise SupplyChainVerificationError(
                    "SLSA provenance does not contain the trusted source repository"
                )
            builder = (settings.sandbox_supply_chain_slsa_builder_id or "").strip()
            if builder and not any(_statement_builder_id(value) == builder for value in statements):
                raise SupplyChainVerificationError(
                    "SLSA provenance was not produced by the trusted builder"
                )
            evidence["slsa_provenance"] = "verified"
            evidence["slsa_source"] = source
            if builder:
                evidence["slsa_builder"] = builder
        if backend == "firecracker":
            evidence.update(self._verify_rootfs())
        return evidence

    def _verify_rootfs(self) -> dict[str, str]:
        rootfs = Path(settings.sandbox_firecracker_rootfs_path or "")
        bundle = settings.sandbox_firecracker_rootfs_bundle_path
        expected = (settings.sandbox_firecracker_rootfs_sha256 or "").lower()
        if not rootfs.is_file() or not bundle or not expected:
            raise SupplyChainVerificationError("Firecracker rootfs verification is not configured")
        actual = _sha256(rootfs)
        if not re.fullmatch(r"[a-f0-9]{64}", expected) or actual != expected:
            raise SupplyChainVerificationError("Firecracker rootfs SHA-256 mismatch")
        self._run(
            [
                "verify-blob",
                "--bundle",
                bundle,
                *self._identity_arguments(),
                str(rootfs),
            ]
        )
        return {"rootfs_sha256": actual, "rootfs_signature": "verified"}

    def _identity_arguments(self) -> list[str]:
        if settings.sandbox_supply_chain_public_key_path:
            return ["--key", settings.sandbox_supply_chain_public_key_path]
        return [
            "--certificate-identity-regexp",
            settings.sandbox_supply_chain_certificate_identity_regexp or "",
            "--certificate-oidc-issuer",
            settings.sandbox_supply_chain_certificate_oidc_issuer or "",
        ]

    def _run(self, arguments: list[str]) -> subprocess.CompletedProcess[str]:
        command = [settings.sandbox_supply_chain_cosign_path, *arguments, "--output", "json"]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
                shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SupplyChainVerificationError(f"Cosign verification could not run: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-1000:]
            raise SupplyChainVerificationError(f"Cosign verification failed: {detail}")
        return completed


def _image_digest(image: str) -> str | None:
    match = re.search(r"@sha256:([a-f0-9]{64})$", image)
    return match.group(1) if match else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _attestation_statements(output: str) -> list[dict]:
    """Decode cosign JSON, including its newline-delimited verify output."""
    documents: list = []
    try:
        documents.append(json.loads(output))
    except json.JSONDecodeError:
        for line in output.splitlines():
            try:
                documents.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    statements: list[dict] = []

    def visit(value) -> None:
        if isinstance(value, dict):
            payload = value.get("payload")
            if isinstance(payload, str):
                try:
                    decoded = json.loads(base64.b64decode(payload, validate=True))
                except (ValueError, json.JSONDecodeError):
                    decoded = None
                if isinstance(decoded, dict):
                    statements.append(decoded)
            if value.get("predicateType") and isinstance(value.get("predicate"), dict):
                statements.append(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for document in documents:
        visit(document)
    return statements


def _statement_has_source(statement: dict, expected: str) -> bool:
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        return False
    candidates: set[str] = set()
    invocation = predicate.get("invocation")
    if isinstance(invocation, dict):
        config_source = invocation.get("configSource")
        if isinstance(config_source, dict) and isinstance(config_source.get("uri"), str):
            candidates.add(config_source["uri"])
    build_definition = predicate.get("buildDefinition")
    if isinstance(build_definition, dict):
        external = build_definition.get("externalParameters")
        if isinstance(external, dict):
            source = external.get("source")
            if isinstance(source, dict) and isinstance(source.get("uri"), str):
                candidates.add(source["uri"])
            elif isinstance(source, str):
                candidates.add(source)
        dependencies = build_definition.get("resolvedDependencies")
        if isinstance(dependencies, list):
            candidates.update(
                value["uri"]
                for value in dependencies
                if isinstance(value, dict) and isinstance(value.get("uri"), str)
            )
    materials = predicate.get("materials")
    if isinstance(materials, list):
        candidates.update(
            value["uri"]
            for value in materials
            if isinstance(value, dict) and isinstance(value.get("uri"), str)
        )
    normalized = expected.rstrip("/")
    return any(
        candidate.rstrip("/") == normalized
        or candidate.startswith(f"{normalized}@")
        or candidate.startswith(f"{normalized}#")
        for candidate in candidates
    )


def _statement_builder_id(statement: dict) -> str | None:
    predicate = statement.get("predicate")
    if not isinstance(predicate, dict):
        return None
    builder = predicate.get("builder")
    if isinstance(builder, dict) and isinstance(builder.get("id"), str):
        return builder["id"]
    run_details = predicate.get("runDetails")
    if isinstance(run_details, dict):
        builder = run_details.get("builder")
        if isinstance(builder, dict) and isinstance(builder.get("id"), str):
            return builder["id"]
    return None
