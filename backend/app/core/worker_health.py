from collections.abc import Iterator
from typing import Any


def worker_heartbeat_pattern(prefix: str) -> str:
    return f"{prefix}:*"


def active_worker_count(connection: Any, prefix: str, *, limit: int = 1000) -> int:
    keys: Iterator[Any] = connection.scan_iter(
        match=worker_heartbeat_pattern(prefix),
        count=100,
    )
    count = 0
    for _key in keys:
        count += 1
        if count >= limit:
            break
    return count
