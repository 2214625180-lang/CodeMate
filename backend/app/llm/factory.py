from app.core.config import settings
from app.llm.base import BaseLLMProvider
from app.llm.mock_provider import MockLLMProvider
from app.llm.openai_compatible_provider import OpenAICompatibleLLMProvider


def get_llm_provider() -> BaseLLMProvider:
    provider_name = _normalize(settings.llm_provider)

    if provider_name == "mock":
        return MockLLMProvider()

    if provider_name == "openai":
        return OpenAICompatibleLLMProvider(
            provider_label="OpenAI",
            api_key=_required(
                _first(settings.llm_api_key, settings.openai_api_key),
                "OPENAI_API_KEY or LLM_API_KEY",
            ),
            base_url=(
                _first(settings.llm_base_url, settings.openai_base_url)
                or settings.openai_base_url
            ),
            model=_first(settings.llm_model, "gpt-4o-mini") or "gpt-4o-mini",
        )

    if provider_name == "deepseek":
        return OpenAICompatibleLLMProvider(
            provider_label="DeepSeek",
            api_key=_required(
                _first(settings.llm_api_key, settings.deepseek_api_key),
                "DEEPSEEK_API_KEY or LLM_API_KEY",
            ),
            base_url=(
                _first(settings.llm_base_url, settings.deepseek_base_url)
                or settings.deepseek_base_url
            ),
            model=_first(settings.llm_model, "deepseek-chat") or "deepseek-chat",
        )

    if provider_name == "openai-compatible":
        return OpenAICompatibleLLMProvider(
            api_key=_required(settings.llm_api_key, "LLM_API_KEY"),
            base_url=_required(settings.llm_base_url, "LLM_BASE_URL"),
            model=_required(settings.llm_model, "LLM_MODEL"),
        )

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")


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
        raise ValueError(f"{env_name} is required for the configured LLM provider.")
    return normalized
