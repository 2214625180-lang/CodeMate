import base64
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class WorkloadIdentityError(ValueError):
    pass


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def load_private_key(path: str) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise WorkloadIdentityError("Workload identity key must be Ed25519")
    return key


def load_public_key(path: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise WorkloadIdentityError("Workload identity key must be Ed25519")
    return key


def issue_assertion(
    *,
    private_key: Ed25519PrivateKey,
    issuer: str,
    subject: str,
    audience: str,
    request_hash: str,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    issued_at = int(time.time()) if now is None else now
    header = {"alg": "EdDSA", "typ": "JWT"}
    claims = {
        "iss": issuer,
        "sub": subject,
        "aud": audience,
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
        "jti": str(uuid.uuid4()),
        "request_hash": request_hash,
    }
    signing_input = f"{_b64(_json(header))}.{_b64(_json(claims))}".encode()
    return f"{signing_input.decode()}.{_b64(private_key.sign(signing_input))}"


def verify_assertion(
    token: str,
    *,
    public_key: Ed25519PublicKey,
    issuer: str,
    subject: str,
    audience: str,
    request_hash: str,
    now: int | None = None,
    clock_skew_seconds: int = 5,
) -> dict:
    try:
        encoded_header, encoded_claims, encoded_signature = token.split(".")
        signing_input = f"{encoded_header}.{encoded_claims}".encode()
        public_key.verify(_unb64(encoded_signature), signing_input)
        header = json.loads(_unb64(encoded_header))
        claims = json.loads(_unb64(encoded_claims))
    except Exception as exc:  # noqa: BLE001 - normalize identity failures.
        raise WorkloadIdentityError("Invalid workload identity assertion") from exc
    current = int(time.time()) if now is None else now
    if header != {"alg": "EdDSA", "typ": "JWT"}:
        raise WorkloadIdentityError("Unsupported workload identity algorithm")
    expected = {"iss": issuer, "sub": subject, "aud": audience}
    if any(not secrets.compare_digest(str(claims.get(key, "")), value) for key, value in expected.items()):
        raise WorkloadIdentityError("Workload identity scope mismatch")
    if int(claims.get("iat", 0)) > current + clock_skew_seconds:
        raise WorkloadIdentityError("Workload identity is not active")
    if int(claims.get("exp", 0)) < current - clock_skew_seconds:
        raise WorkloadIdentityError("Workload identity expired")
    if not secrets.compare_digest(str(claims.get("request_hash", "")), request_hash):
        raise WorkloadIdentityError("Workload identity request binding mismatch")
    if not claims.get("jti"):
        raise WorkloadIdentityError("Workload identity has no replay identifier")
    return claims


@dataclass
class ReplayCache:
    entries: dict[str, int]

    def consume(self, jti: str, expires_at: int, *, now: int | None = None) -> None:
        current = int(time.time()) if now is None else now
        self.entries = {key: expiry for key, expiry in self.entries.items() if expiry >= current}
        if jti in self.entries:
            raise WorkloadIdentityError("Workload identity assertion was replayed")
        self.entries[jti] = expires_at
