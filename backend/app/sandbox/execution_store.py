import json
import threading
import time
from dataclasses import dataclass
from typing import Literal, Protocol

from redis import Redis

from app.core.config import settings
from app.sandbox.execution_protocol import ExecutionResponse


ClaimStatus = Literal["acquired", "cached", "in_progress", "conflict", "replayed"]


@dataclass(slots=True)
class ExecutionClaim:
    status: ClaimStatus
    response: ExecutionResponse | None = None
    attempt: int = 0


class ExecutionStateStore(Protocol):
    def claim(
        self,
        *,
        execution_id: str,
        request_hash: str,
        assertion_jti: str,
        assertion_ttl: int,
        owner: str,
        lease_seconds: int,
    ) -> ExecutionClaim: ...

    def complete(
        self,
        *,
        execution_id: str,
        request_hash: str,
        owner: str,
        attempt: int,
        response: ExecutionResponse,
    ) -> bool: ...

    def health(self) -> bool: ...


class MemoryExecutionStateStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._replays: dict[str, tuple[float, str]] = {}
        self._executions: dict[str, dict] = {}

    def claim(
        self,
        *,
        execution_id: str,
        request_hash: str,
        assertion_jti: str,
        assertion_ttl: int,
        owner: str,
        lease_seconds: int,
    ) -> ExecutionClaim:
        now = time.time()
        with self._lock:
            self._replays = {
                key: value for key, value in self._replays.items() if value[0] >= now
            }
            row = self._executions.get(execution_id)
            if row and row["request_hash"] != request_hash:
                return ExecutionClaim("conflict")
            if row and row["state"] == "completed":
                return ExecutionClaim(
                    "cached", ExecutionResponse.model_validate(row["response"]), row["attempt"]
                )
            replay = self._replays.get(assertion_jti)
            if replay:
                if replay[1] == execution_id and row and row["state"] == "running":
                    return ExecutionClaim("in_progress", attempt=row["attempt"])
                return ExecutionClaim("replayed")
            self._replays[assertion_jti] = (now + assertion_ttl, execution_id)
            if row and row["lease_until"] > now:
                return ExecutionClaim("in_progress", attempt=row["attempt"])
            attempt = int(row["attempt"] if row else 0) + 1
            self._executions[execution_id] = {
                "request_hash": request_hash,
                "state": "running",
                "owner": owner,
                "lease_until": now + lease_seconds,
                "attempt": attempt,
            }
            return ExecutionClaim("acquired", attempt=attempt)

    def complete(
        self,
        *,
        execution_id: str,
        request_hash: str,
        owner: str,
        attempt: int,
        response: ExecutionResponse,
    ) -> bool:
        with self._lock:
            row = self._executions.get(execution_id)
            if (
                not row
                or row["state"] != "running"
                or row["request_hash"] != request_hash
                or row["owner"] != owner
                or row["attempt"] != attempt
                or row["lease_until"] <= time.time()
            ):
                return False
            row.update(state="completed", response=response.model_dump(), lease_until=0)
            return True

    def health(self) -> bool:
        return True


CLAIM_SCRIPT = """
local request_hash = redis.call('HGET', KEYS[2], 'request_hash')
if request_hash and request_hash ~= ARGV[1] then return {'conflict', '0', ''} end
local state = redis.call('HGET', KEYS[2], 'state')
if state == 'completed' then
  return {'cached', redis.call('HGET', KEYS[2], 'attempt') or '0', redis.call('HGET', KEYS[2], 'response') or ''}
end
local replay_execution = redis.call('GET', KEYS[1])
if replay_execution then
  if replay_execution == ARGV[2] and state == 'running' then
    return {'in_progress', redis.call('HGET', KEYS[2], 'attempt') or '0', ''}
  end
  return {'replayed', '0', ''}
end
redis.call('SET', KEYS[1], ARGV[2], 'EX', ARGV[4], 'NX')
local lease_until = tonumber(redis.call('HGET', KEYS[2], 'lease_until') or '0')
if state == 'running' and lease_until > tonumber(ARGV[5]) then
  return {'in_progress', redis.call('HGET', KEYS[2], 'attempt') or '0', ''}
end
local attempt = redis.call('HINCRBY', KEYS[2], 'attempt', 1)
redis.call('HSET', KEYS[2], 'request_hash', ARGV[1], 'state', 'running', 'owner', ARGV[3], 'lease_until', ARGV[6])
redis.call('EXPIRE', KEYS[2], ARGV[7])
return {'acquired', tostring(attempt), ''}
"""

COMPLETE_SCRIPT = """
if redis.call('HGET', KEYS[1], 'request_hash') ~= ARGV[1] then return 0 end
if redis.call('HGET', KEYS[1], 'owner') ~= ARGV[2] then return 0 end
if redis.call('HGET', KEYS[1], 'attempt') ~= ARGV[3] then return 0 end
if redis.call('HGET', KEYS[1], 'state') ~= 'running' then return 0 end
if tonumber(redis.call('HGET', KEYS[1], 'lease_until') or '0') <= tonumber(ARGV[5]) then return 0 end
redis.call('HSET', KEYS[1], 'state', 'completed', 'response', ARGV[4], 'lease_until', '0')
redis.call('EXPIRE', KEYS[1], ARGV[6])
return 1
"""


class RedisExecutionStateStore:
    def __init__(self, client: Redis) -> None:
        self.client = client
        self.prefix = settings.sandbox_execution_state_prefix.rstrip(":")

    def _key(self, suffix: str) -> str:
        # Both keys touched by CLAIM_SCRIPT must share a Redis Cluster slot. A
        # single slot also preserves global JTI replay detection across execution
        # IDs; sharding by execution ID would make the same assertion reusable.
        return f"{self.prefix}:{{atomic}}:{suffix}"

    def claim(
        self,
        *,
        execution_id: str,
        request_hash: str,
        assertion_jti: str,
        assertion_ttl: int,
        owner: str,
        lease_seconds: int,
    ) -> ExecutionClaim:
        now = int(time.time())
        result = self.client.eval(
            CLAIM_SCRIPT,
            2,
            self._key(f"replay:{assertion_jti}"),
            self._key(f"execution:{execution_id}"),
            request_hash,
            execution_id,
            owner,
            max(1, assertion_ttl),
            now,
            now + lease_seconds,
            settings.sandbox_execution_state_retention_seconds,
        )
        status = _decode(result[0])
        attempt = int(_decode(result[1]))
        payload = _decode(result[2])
        response = ExecutionResponse.model_validate(json.loads(payload)) if payload else None
        return ExecutionClaim(status=status, response=response, attempt=attempt)

    def complete(
        self,
        *,
        execution_id: str,
        request_hash: str,
        owner: str,
        attempt: int,
        response: ExecutionResponse,
    ) -> bool:
        result = self.client.eval(
            COMPLETE_SCRIPT,
            1,
            self._key(f"execution:{execution_id}"),
            request_hash,
            owner,
            attempt,
            response.model_dump_json(),
            int(time.time()),
            settings.sandbox_execution_state_retention_seconds,
        )
        return bool(result)

    def health(self) -> bool:
        return bool(self.client.ping())


def build_execution_state_store() -> ExecutionStateStore:
    backend = settings.sandbox_execution_state_backend.strip().lower()
    if backend == "redis":
        url = settings.sandbox_execution_state_redis_url or settings.redis_url
        return RedisExecutionStateStore(
            Redis.from_url(
                url,
                decode_responses=False,
                socket_connect_timeout=2,
                socket_timeout=5,
                health_check_interval=15,
                retry_on_timeout=True,
            )
        )
    if backend == "memory":
        return MemoryExecutionStateStore()
    raise RuntimeError(f"Unsupported sandbox execution state backend: {backend}")


def _decode(value) -> str:
    return value.decode() if isinstance(value, bytes) else str(value)
