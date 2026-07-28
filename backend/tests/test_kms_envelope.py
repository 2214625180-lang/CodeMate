import sys
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.core.kms import (
    KMSDecryptionError,
    decrypt_envelope,
    encrypt_envelope,
    envelope_metadata,
    verify_kms,
)


def configure_local(monkeypatch, key="local-envelope-master-key-32-characters"):
    monkeypatch.setattr(settings, "mcp_registry_kms_provider", "local")
    monkeypatch.setattr(settings, "mcp_registry_master_key", key)
    monkeypatch.setattr(settings, "mcp_registry_previous_master_key", None)


def test_local_kms_envelope_round_trip_tamper_and_rotation(monkeypatch):
    configure_local(monkeypatch)
    encrypted = encrypt_envelope(b"credential-secret")

    assert b"credential-secret" not in encrypted.encode()
    assert decrypt_envelope(encrypted) == b"credential-secret"
    assert envelope_metadata(encrypted)["provider"] == "local"
    assert verify_kms()["status"] == "verified"

    old_key = settings.mcp_registry_master_key
    monkeypatch.setattr(settings, "mcp_registry_master_key", "new-envelope-master-key-32-characters")
    monkeypatch.setattr(settings, "mcp_registry_previous_master_key", old_key)
    assert decrypt_envelope(encrypted) == b"credential-secret"

    tampered = f"{encrypted[:-2]}AA"
    with pytest.raises(KMSDecryptionError):
        decrypt_envelope(tampered)


def test_aws_kms_envelope_uses_generate_and_decrypt_context(monkeypatch):
    calls = []

    class FakeKMSClient:
        def generate_data_key(self, **kwargs):
            calls.append(("generate", kwargs))
            plaintext = b"k" * 32
            return {
                "Plaintext": plaintext,
                "CiphertextBlob": b"wrapped:" + plaintext,
                "KeyId": "arn:aws:kms:region:account:key/test",
            }

        def decrypt(self, **kwargs):
            calls.append(("decrypt", kwargs))
            return {"Plaintext": bytes(kwargs["CiphertextBlob"]).removeprefix(b"wrapped:")}

    fake_boto3 = SimpleNamespace(client=lambda *args, **kwargs: FakeKMSClient())
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setattr(settings, "mcp_registry_kms_provider", "aws")
    monkeypatch.setattr(settings, "mcp_registry_kms_key_id", "alias/codemate-test")
    monkeypatch.setattr(settings, "aws_region", "ap-southeast-1")
    monkeypatch.setattr(settings, "aws_endpoint_url", None)

    encrypted = encrypt_envelope(b"aws-kms-secret")
    assert decrypt_envelope(encrypted) == b"aws-kms-secret"
    assert envelope_metadata(encrypted) == {
        "provider": "aws",
        "key_id": "arn:aws:kms:region:account:key/test",
    }
    assert calls[0][1]["EncryptionContext"]["purpose"] == "mcp-credential"
    assert calls[1][1]["EncryptionContext"]["application"] == "codemate"
