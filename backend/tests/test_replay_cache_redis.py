import hashlib
import os
from secrets import token_urlsafe

import pytest
from redis import Redis
from redis.exceptions import RedisError

from app.core import replay_cache
from app.core.config import settings


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
