import hashlib
import logging
import time
from threading import Lock

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings

logger = logging.getLogger("codemate.security")


class ReplayNonceStoreUnavailable(RuntimeError):
    pass


class InMemoryReplayNonceStore:
    def __init__(self) -> None:
        self._nonces: dict[str, float] = {}
        self._lock = Lock()

    def consume(self, nonce: str, ttl_seconds: int) -> bool:
        now = time.time()
        expires_at = now + ttl_seconds
        with self._lock:
            self._prune(now)
            if nonce in self._nonces:
                return False
            self._nonces[nonce] = expires_at
            return True

    def _prune(self, now: float) -> None:
        expired = [nonce for nonce, expires_at in self._nonces.items() if expires_at <= now]
        for nonce in expired:
            del self._nonces[nonce]


_memory_store = InMemoryReplayNonceStore()
_redis_client: Redis | None = None


def consume_proxy_identity_nonce(nonce: str, ttl_seconds: int) -> bool:
    store = (settings.codemate_proxy_identity_nonce_store or "memory").strip().lower()
    ttl_seconds = max(1, ttl_seconds)
    if store == "redis":
        return consume_redis_nonce(nonce, ttl_seconds)
    if store != "memory":
        logger.warning("Unknown proxy identity nonce store %r; falling back to memory", store)
    return _memory_store.consume(nonce, ttl_seconds)


def consume_redis_nonce(nonce: str, ttl_seconds: int) -> bool:
    try:
        client = redis_client()
        nonce_hash = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
        return bool(
            client.set(
                f"codemate:proxy-identity-nonce:{nonce_hash}",
                "1",
                ex=ttl_seconds,
                nx=True,
            )
        )
    except RedisError as exc:
        raise ReplayNonceStoreUnavailable("Proxy identity nonce store is unavailable") from exc


def redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client
