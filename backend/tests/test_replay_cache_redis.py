import hashlib
import os
from secrets import token_urlsafe

import pytest
from redis import Redis
from redis.exceptions import RedisError

from app.core import replay_cache
from app.core.config import settings
from app.sandbox.execution_protocol import ExecutionResponse
from app.sandbox.execution_store import RedisExecutionStateStore


def test_redis_nonce_store_consumes_nonce_once_with_ttl(monkeypatch):
    redis_url = os.environ.get("CODEMATE_TEST_REDIS_URL") or os.environ.get("REDIS_URL") or settings.redis_url
    client = redis_client_or_skip(redis_url)
    nonce = f"pytest.{token_urlsafe(24)}"
    key = nonce_key(nonce)

    monkeypatch.setattr(settings, "redis_url", redis_url)
    monkeypatch.setattr(settings, "codemate_proxy_identity_nonce_store", "redis")
    monkeypatch.setattr(replay_cache, "_redis_client", None)
    client.delete(key)
    try:
        assert replay_cache.consume_proxy_identity_nonce(nonce, ttl_seconds=30) is True
        assert replay_cache.consume_proxy_identity_nonce(nonce, ttl_seconds=30) is False
        assert client.ttl(key) > 0
    finally:
        client.delete(key)
        monkeypatch.setattr(replay_cache, "_redis_client", None)


def redis_client_or_skip(redis_url: str) -> Redis:
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        client.ping()
    except (OSError, RedisError) as exc:
        pytest.skip(f"Redis is not available for integration test: {exc}")
    return client


def nonce_key(nonce: str) -> str:
    nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    return f"codemate:proxy-identity-nonce:{nonce_hash}"


def test_execution_state_is_shared_and_fenced_across_instances(monkeypatch):
    redis_url = os.environ.get("CODEMATE_TEST_REDIS_URL") or os.environ.get("REDIS_URL") or settings.redis_url
    client = redis_client_or_skip(redis_url)
    prefix = f"codemate:pytest:sandbox:{token_urlsafe(12)}"
    monkeypatch.setattr(settings, "sandbox_execution_state_prefix", prefix)
    first_store = RedisExecutionStateStore(client)
    second_store = RedisExecutionStateStore(client)
    execution_id = "12345678-1234-1234-1234-123456789012"
    request_hash = "a" * 64
    try:
        first = first_store.claim(
            execution_id=execution_id,
            request_hash=request_hash,
            assertion_jti="jti-a",
            assertion_ttl=60,
            owner="node-a",
            lease_seconds=60,
        )
        second = second_store.claim(
            execution_id=execution_id,
            request_hash=request_hash,
            assertion_jti="jti-b",
            assertion_ttl=60,
            owner="node-b",
            lease_seconds=60,
        )
        response = ExecutionResponse(
            execution_id=execution_id,
            backend="firecracker",
            passed=True,
            exit_code=0,
            stdout="ok",
            stderr="",
            archive_sha256="b" * 64,
            workload_subject="spiffe://broker",
        )
        assert first.status == "acquired"
        assert second.status == "in_progress"
        assert second_store.complete(
            execution_id=execution_id,
            request_hash=request_hash,
            owner="node-b",
            attempt=first.attempt,
            response=response,
        ) is False
        assert first_store.complete(
            execution_id=execution_id,
            request_hash=request_hash,
            owner="node-a",
            attempt=first.attempt,
            response=response,
        ) is True
        cached = second_store.claim(
            execution_id=execution_id,
            request_hash=request_hash,
            assertion_jti="jti-c",
            assertion_ttl=60,
            owner="node-b",
            lease_seconds=60,
        )
        assert cached.status == "cached"
        assert cached.response and cached.response.stdout == "ok"
    finally:
        keys = list(client.scan_iter(match=f"{prefix}:*"))
        if keys:
            client.delete(*keys)
