from app.core.config import settings
from app.embeddings.base import BaseEmbeddingProvider
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.embeddings.openai_compatible_provider import OpenAICompatibleEmbeddingProvider


def get_embedding_provider() -> BaseEmbeddingProvider:
    provider_name = _normalize(settings.embedding_provider)

    if provider_name == "mock":
        return MockEmbeddingProvider()

    if provider_name == "openai":
        return OpenAICompatibleEmbeddingProvider(
            provider_label="OpenAI",
            api_key=_required(
                _first(settings.embedding_api_key, settings.openai_api_key),
                "OPENAI_API_KEY or EMBEDDING_API_KEY",
            ),
            base_url=(
                _first(settings.embedding_base_url, settings.openai_base_url)
                or settings.openai_base_url
            ),
            model=_first(settings.embedding_model, "text-embedding-3-small")
            or "text-embedding-3-small",
            dimension=settings.embedding_dimension,
        )

    if provider_name == "openai-compatible":
        return OpenAICompatibleEmbeddingProvider(
            api_key=_required(
                _first(settings.embedding_api_key, settings.openai_api_key),
                "EMBEDDING_API_KEY or OPENAI_API_KEY",
            ),
            base_url=_required(settings.embedding_base_url, "EMBEDDING_BASE_URL"),
            model=_first(settings.embedding_model, "text-embedding-3-small")
            or "text-embedding-3-small",
            dimension=settings.embedding_dimension,
        )

    raise ValueError(f"Unsupported embedding provider: {settings.embedding_provider}")


def _normalize(value: str) -> str:
    return value.strip().lower().replace("_", "-")


def _first(*values: str | None) -> str | None:
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return None


def _required(value: str | None, env_name: str) -> str:
    normalized = _first(value)
    if normalized is None:
        raise ValueError(f"{env_name} is required for the configured embedding provider.")
    return normalized
