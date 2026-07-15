import base64
import json
import re
import secrets
import subprocess
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature

from app.core.config import settings
from app.sandbox.workload_identity import load_public_key


class NodeAttestationError(RuntimeError):
    pass


class NodeAttestationVerifier:
    """Validate a signed, normalized verdict from a TPM/TEE attestation authority.

    In production the configured command receives a fresh nonce and must obtain a
    quote from the local node, validate it with the deployment's attestation
    service, and print the authority-signed envelope. The file mode exists for
    local development and for CSI drivers that continuously project fresh
    attestation verdicts.
    """

    def verify(self, *, now: int | None = None, node_id: str | None = None) -> dict[str, str]:
        if not settings.sandbox_node_attestation_enabled:
            return {"node_attestation": "disabled"}
        public_key_path = settings.sandbox_node_attestation_public_key_path
        expected_node = node_id or settings.sandbox_node_attestation_expected_node_id or ""
        if not public_key_path or not expected_node:
            raise NodeAttestationError("Node attestation verifier is not configured")

        nonce = secrets.token_urlsafe(32)
        command = settings.sandbox_node_attestation_verifier_command_json
        if command:
            envelope = self._run_verifier(command, nonce=nonce, node_id=expected_node)
            expected_nonce = nonce
            evidence_source = "challenge-response"
        else:
            document_path = settings.sandbox_node_attestation_document_path
            if not document_path:
                raise NodeAttestationError("Node attestation document is not configured")
            try:
                envelope = json.loads(Path(document_path).read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise NodeAttestationError("Node attestation document is invalid") from exc
            expected_nonce = None
            evidence_source = "projected-verdict"

        claims = self._verify_envelope(envelope, public_key_path)
        current = int(time.time()) if now is None else now
        issued_at = _integer_claim(claims, "issued_at")
        expires_at = _integer_claim(claims, "expires_at")
        if issued_at > current + 5 or current - issued_at > settings.sandbox_node_attestation_max_age_seconds:
            raise NodeAttestationError("Node attestation is stale or not active")
        if expires_at < current or expires_at < issued_at:
            raise NodeAttestationError("Node attestation expired")
        if not secrets.compare_digest(str(claims.get("node_id", "")), expected_node):
            raise NodeAttestationError("Node attestation identity mismatch")
        if expected_nonce is not None and not secrets.compare_digest(
            str(claims.get("nonce", "")), expected_nonce
        ):
            raise NodeAttestationError("Node attestation challenge mismatch")
        if str(claims.get("verdict", "")).lower() != "verified":
            raise NodeAttestationError("Node attestation authority did not return a verified verdict")

        tee_type = str(claims.get("tee_type", "")).lower()
        measurement = str(claims.get("measurement", "")).lower()
        if tee_type not in settings.sandbox_node_attestation_tee_allowlist:
            raise NodeAttestationError("Node TEE type is not allowed")
        if measurement not in settings.sandbox_node_attestation_measurement_allowlist:
            raise NodeAttestationError("Node measurement is not allowed")
        quote_digest = str(claims.get("quote_digest", "")).lower()
        if not re.fullmatch(r"[a-f0-9]{64}", quote_digest):
            raise NodeAttestationError("Node attestation has no valid TPM/TEE quote digest")
        verifier_id = str(claims.get("verifier_id", ""))
        if not verifier_id:
            raise NodeAttestationError("Node attestation has no verifier identity")
        return {
            "node_attestation": "verified",
            "node_id": expected_node,
            "tee_type": tee_type,
            "measurement": measurement,
            "quote_digest": quote_digest,
            "attestation_verifier": verifier_id,
            "attestation_evidence": evidence_source,
        }

    def _run_verifier(self, configured: str, *, nonce: str, node_id: str) -> dict:
        try:
            template = json.loads(configured)
        except json.JSONDecodeError as exc:
            raise NodeAttestationError("Node attestation verifier command is not valid JSON") from exc
        if not isinstance(template, list) or not template or not all(
            isinstance(value, str) for value in template
        ):
            raise NodeAttestationError("Node attestation verifier command must be a JSON argv array")
        document = settings.sandbox_node_attestation_document_path or ""
        try:
            argv = [
                value.format(nonce=nonce, node_id=node_id, document=document)
                for value in template
            ]
            completed = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=settings.sandbox_node_attestation_verifier_timeout_seconds,
                check=False,
                shell=False,
            )
        except (KeyError, OSError, subprocess.TimeoutExpired) as exc:
            raise NodeAttestationError(f"Node attestation verifier could not run: {exc}") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout)[-1000:]
            raise NodeAttestationError(f"Node attestation verifier rejected the node: {detail}")
        if len(completed.stdout) > 1024 * 1024:
            raise NodeAttestationError("Node attestation verifier response is too large")
        try:
            value = json.loads(completed.stdout)
        except (ValueError, json.JSONDecodeError) as exc:
            raise NodeAttestationError("Node attestation verifier returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise NodeAttestationError("Node attestation verifier returned an invalid envelope")
        return value

    @staticmethod
    def _verify_envelope(envelope: dict, public_key_path: str) -> dict:
        try:
            payload_bytes = base64.b64decode(envelope["payload"], validate=True)
            signature = base64.b64decode(envelope["signature"], validate=True)
            load_public_key(public_key_path).verify(signature, payload_bytes)
            claims = json.loads(payload_bytes)
        except (
            OSError,
            KeyError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
            InvalidSignature,
        ) as exc:
            raise NodeAttestationError("Node attestation document is invalid") from exc
        if not isinstance(claims, dict):
            raise NodeAttestationError("Node attestation payload is invalid")
        return claims


def _integer_claim(claims: dict, name: str) -> int:
    try:
        return int(claims[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise NodeAttestationError(f"Node attestation has no valid {name}") from exc
