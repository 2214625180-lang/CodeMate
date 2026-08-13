import json
import re
from typing import Any


_SENSITIVE_KEY_MARKERS = (
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)
_CONTENT_KEY_MARKERS = (
    "argument",
    "command",
    "content",
    "diff",
    "error",
    "message",
    "output",
    "patch",
    "prompt",
    "query",
    "result",
    "stderr",
    "stdout",
    "summary",
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|password|secret|token)\s*[:=]|"
    r"(?:gh[pousr]_|sk-|-----BEGIN [A-Z ]*PRIVATE KEY-----)",
    re.IGNORECASE,
)


def redact_timeline_payload(value: Any) -> tuple[dict | list | str | int | float | bool | None, str]:
    """Return a metadata-only Timeline payload and its data classification."""
    state = {"restricted": False}
    return _redact(value, state), "restricted" if state["restricted"] else "metadata"


def safe_exception_code(error: Exception | str) -> str:
    if isinstance(error, Exception):
        name = type(error).__name__
    else:
        name = "error"
    normalized = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return normalized[:64] or "error"


def _redact(value: Any, state: dict[str, bool], *, key: str | None = None) -> Any:
    if isinstance(value, dict):
        if value.get("redacted") is True and set(value) <= {
            "redacted",
            "classification",
            "char_count",
        }:
            return value
        return {
            str(item_key): _redact(item, state, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item, state, key=key) for item in value]
    if value is None or isinstance(value, bool | int | float):
        return value

    normalized_key = (key or "").lower()
    if isinstance(value, str) and _SECRET_VALUE_PATTERN.search(value):
        return _redacted_marker(value, state, "secret")
    if _matches(normalized_key, _SENSITIVE_KEY_MARKERS):
        return _redacted_marker(value, state, "secret")
    if _matches(normalized_key, _CONTENT_KEY_MARKERS):
        return _redacted_marker(value, state, "content")
    if isinstance(value, str):
        return _redacted_marker(value, state, "text")
    return str(value)


def _matches(key: str, markers: tuple[str, ...]) -> bool:
    return any(marker in key for marker in markers)


def _redacted_marker(value: Any, state: dict[str, bool], classification: str) -> dict[str, Any]:
    state["restricted"] = True
    return {
        "redacted": True,
        "classification": classification,
        "char_count": len(json.dumps(value, ensure_ascii=False, default=str)),
    }
