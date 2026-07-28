import base64
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


ENVELOPE_PREFIX = "codemate:kms:v2:"
ENVELOPE_AAD = b"codemate-mcp-credential-v2"
KMS_CONTEXT = {"application": "codemate", "purpose": "mcp-credential"}


class KMSConfigurationError(RuntimeError):
    pass


class KMSDecryptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class DataKey:
    plaintext: bytes
    encrypted: bytes
    key_id: str
    provider: str


class EnvelopeKMS(Protocol):
    provider: str

    def generate_data_key(self, context: dict[str, str] | None = None) -> DataKey: ...

    def decrypt_data_key(
        self, encrypted: bytes, *, key_id: str, context: dict[str, str] | None = None
    ) -> bytes: ...

    def verify(self) -> dict[str, str]: ...


class LocalEnvelopeKMS:
    provider = "local"

    def generate_data_key(self, context: dict[str, str] | None = None) -> DataKey:
        data_key = os.urandom(32)
        nonce = os.urandom(12)
        wrapped = nonce + AESGCM(self._master_key()).encrypt(
            nonce, data_key, _local_wrap_aad(context)
        )
        return DataKey(data_key, wrapped, "local-derived-key", self.provider)

    def decrypt_data_key(
        self, encrypted: bytes, *, key_id: str, context: dict[str, str] | None = None
    ) -> bytes:
        del key_id
        last_error: Exception | None = None
        for secret in (
            settings.mcp_registry_master_key,
            settings.mcp_registry_previous_master_key,
        ):
            if not (secret or "").strip():
                continue
            try:
                return AESGCM(self._master_key(secret)).decrypt(
                    encrypted[:12],
                    encrypted[12:],
                    _local_wrap_aad(context),
                )
            except Exception as exc:  # noqa: BLE001 - key rotation fallback.
                last_error = exc
        raise KMSDecryptionError("Local envelope data key could not be unwrapped") from last_error

    def verify(self) -> dict[str, str]:
        generated = self.generate_data_key()
        restored = self.decrypt_data_key(generated.encrypted, key_id=generated.key_id)
        if not _constant_time_equal(generated.plaintext, restored):
            raise KMSDecryptionError("Local KMS round-trip verification failed")
        return {"provider": self.provider, "key_id": generated.key_id, "status": "verified"}

    @staticmethod
    def _master_key(secret: str | None = None) -> bytes:
        value = (secret if secret is not None else settings.mcp_registry_master_key or "").strip()
        if len(value) < 16:
            raise KMSConfigurationError("MCP_REGISTRY_MASTER_KEY is required for local KMS")
        return hashlib.sha256(value.encode()).digest()


class AWSKMS:
    provider = "aws"

    def __init__(self):
        key_id = (settings.mcp_registry_kms_key_id or "").strip()
        if not key_id:
            raise KMSConfigurationError("MCP_REGISTRY_KMS_KEY_ID is required for AWS KMS")
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - dependency is installed in production.
            raise KMSConfigurationError("boto3 is required for AWS KMS") from exc
        self.key_id = key_id
        self.client = boto3.client(
            "kms",
            region_name=settings.aws_region or None,
            endpoint_url=settings.aws_endpoint_url or None,
        )

    def generate_data_key(self, context: dict[str, str] | None = None) -> DataKey:
        response = self.client.generate_data_key(
            KeyId=self.key_id,
            KeySpec="AES_256",
            EncryptionContext=context or KMS_CONTEXT,
        )
        return DataKey(
            plaintext=bytes(response["Plaintext"]),
            encrypted=bytes(response["CiphertextBlob"]),
            key_id=str(response.get("KeyId") or self.key_id),
            provider=self.provider,
        )

    def decrypt_data_key(
        self, encrypted: bytes, *, key_id: str, context: dict[str, str] | None = None
    ) -> bytes:
        del key_id  # The ciphertext blob records the AWS KMS key version.
        response = self.client.decrypt(
            CiphertextBlob=encrypted,
            EncryptionContext=context or KMS_CONTEXT,
        )
        return bytes(response["Plaintext"])

    def verify(self) -> dict[str, str]:
        generated = self.generate_data_key()
        restored = self.decrypt_data_key(generated.encrypted, key_id=generated.key_id)
        if not _constant_time_equal(generated.plaintext, restored):
            raise KMSDecryptionError("AWS KMS round-trip verification failed")
        return {"provider": self.provider, "key_id": generated.key_id, "status": "verified"}


def kms_provider(name: str | None = None) -> EnvelopeKMS:
    provider = (name or settings.mcp_registry_kms_provider).strip().lower()
    if provider == "local":
        return LocalEnvelopeKMS()
    if provider == "aws":
        return AWSKMS()
    raise KMSConfigurationError(f"Unsupported MCP registry KMS provider: {provider}")


def encrypt_envelope(plaintext: bytes, *, binding: str | None = None) -> str:
    provider = kms_provider()
    binding_sha256 = _binding_sha256(binding)
    context = {**KMS_CONTEXT, "binding": binding_sha256}
    generated = provider.generate_data_key(context)
    nonce = os.urandom(12)
    ciphertext = AESGCM(generated.plaintext).encrypt(
        nonce, plaintext, ENVELOPE_AAD + binding_sha256.encode()
    )
    envelope = {
        "version": 2,
        "algorithm": "AES-256-GCM",
        "kms_provider": generated.provider,
        "kms_key_id": generated.key_id,
        "binding_sha256": binding_sha256,
        "encrypted_data_key": _b64(generated.encrypted),
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
    }
    encoded = base64.urlsafe_b64encode(
        json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode()
    ).decode()
    return f"{ENVELOPE_PREFIX}{encoded}"


def decrypt_envelope(value: str, *, binding: str | None = None) -> bytes:
    if not value.startswith(ENVELOPE_PREFIX):
        raise KMSDecryptionError("Credential is not a KMS envelope")
    try:
        envelope = json.loads(
            base64.urlsafe_b64decode(value.removeprefix(ENVELOPE_PREFIX).encode())
        )
        if envelope.get("version") != 2 or envelope.get("algorithm") != "AES-256-GCM":
            raise ValueError("unsupported envelope version")
        stored_binding = str(envelope.get("binding_sha256") or _binding_sha256(None))
        if binding is not None and not _constant_time_equal(
            stored_binding.encode(), _binding_sha256(binding).encode()
        ):
            raise KMSDecryptionError("KMS credential binding does not match its database owner")
        provider = kms_provider(str(envelope["kms_provider"]))
        data_key = provider.decrypt_data_key(
            _unb64(envelope["encrypted_data_key"]),
            key_id=str(envelope["kms_key_id"]),
            context={**KMS_CONTEXT, "binding": stored_binding},
        )
        return AESGCM(data_key).decrypt(
            _unb64(envelope["nonce"]),
            _unb64(envelope["ciphertext"]),
            ENVELOPE_AAD + stored_binding.encode(),
        )
    except KMSConfigurationError:
        raise
    except Exception as exc:
        raise KMSDecryptionError("KMS credential envelope could not be decrypted") from exc


def envelope_metadata(value: str) -> dict[str, str]:
    if not value.startswith(ENVELOPE_PREFIX):
        return {"provider": "legacy", "key_id": "application-master-key"}
    try:
        envelope = json.loads(
            base64.urlsafe_b64decode(value.removeprefix(ENVELOPE_PREFIX).encode())
        )
        return {
            "provider": str(envelope.get("kms_provider") or "unknown"),
            "key_id": str(envelope.get("kms_key_id") or "unknown"),
        }
    except Exception:
        return {"provider": "invalid", "key_id": "invalid"}


def envelope_is_unbound(value: str) -> bool:
    if not value.startswith(ENVELOPE_PREFIX):
        return True
    try:
        envelope = json.loads(
            base64.urlsafe_b64decode(value.removeprefix(ENVELOPE_PREFIX).encode())
        )
        return str(envelope.get("binding_sha256") or _binding_sha256(None)) == (
            _binding_sha256(None)
        )
    except Exception:
        return False


def verify_kms() -> dict[str, str]:
    return kms_provider().verify()


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode()


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value.encode())


def _constant_time_equal(left: bytes, right: bytes) -> bool:
    import hmac

    return hmac.compare_digest(left, right)


def _binding_sha256(binding: str | None) -> str:
    return hashlib.sha256((binding or "unbound").encode()).hexdigest()


def _local_wrap_aad(context: dict[str, str] | None) -> bytes:
    return b"codemate-local-envelope-key-v1:" + json.dumps(
        context or KMS_CONTEXT, separators=(",", ":"), sort_keys=True
    ).encode()


if __name__ == "__main__":
    print(json.dumps(verify_kms(), sort_keys=True))
