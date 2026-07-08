import json
from collections.abc import Iterable
from typing import Any

import httpx

from app.core.config import settings
from app.embeddings.base import BaseEmbeddingProvider


class OpenAICompatibleEmbeddingProvider(BaseEmbeddingProvider):
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        dimension: int,
        provider_label: str = "OpenAI-compatible",
        batch_size: int | None = None,
        timeout_seconds: float | None = None,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._dimension = dimension
        self.provider_label = provider_label
        self.batch_size = max(batch_size or settings.embedding_batch_size, 1)
        self.timeout_seconds = timeout_seconds or settings.embedding_timeout_seconds

    @property
    def dimension(self) -> int:
        return self._dimension

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        with httpx.Client(timeout=self.timeout_seconds) as client:
            for batch in self._batches(texts, self.batch_size):
                vectors.extend(self._embed_batch(client, batch))
        return vectors

    @property
    def _embeddings_url(self) -> str:
        return f"{self.base_url}/embeddings"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _embed_batch(self, client: httpx.Client, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": [text if text.strip() else " " for text in texts],
        }
        if self._supports_dimensions_parameter:
            payload["dimensions"] = self.dimension

        try:
            response = client.post(self._embeddings_url, headers=self._headers, json=payload)
            self._raise_for_status(response)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"{self.provider_label} embeddings request failed: {exc}") from exc

        data = response.json().get("data") or []
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors = [self._coerce_vector(item.get("embedding")) for item in ordered]
        if len(vectors) != len(texts):
            raise RuntimeError(
                f"{self.provider_label} returned {len(vectors)} embeddings for {len(texts)} texts."
            )
        return vectors

    @property
    def _supports_dimensions_parameter(self) -> bool:
        return self.model.startswith("text-embedding-3")

    def _coerce_vector(self, embedding: Any) -> list[float]:
        if not isinstance(embedding, list):
            raise RuntimeError(f"{self.provider_label} returned an invalid embedding payload.")
        vector = [float(value) for value in embedding]
        if len(vector) != self.dimension:
            raise ValueError(
                f"{self.provider_label} model {self.model} returned {len(vector)} dimensions, "
                f"but EMBEDDING_DIMENSION is {self.dimension}. Update EMBEDDING_DIMENSION "
                "or choose a model that supports the configured dimension."
            )
        return vector

    def _raise_for_status(self, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = self._response_error_detail(response)
            raise RuntimeError(
                f"{self.provider_label} API error {response.status_code}: {detail}"
            ) from exc

    def _response_error_detail(self, response: httpx.Response) -> str:
        try:
            body = response.json()
        except json.JSONDecodeError:
            return response.text[:1000]
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
        return json.dumps(body, ensure_ascii=False)[:1000]

    def _batches(self, texts: list[str], size: int) -> Iterable[list[str]]:
        for start in range(0, len(texts), size):
            yield texts[start : start + size]
