from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "local"
    database_url: str = "postgresql+psycopg://codemate:codemate@localhost:5432/codemate"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "codemate_chunks"
    frontend_url: str = "http://localhost:3000"
    api_cors_origins: str = "http://localhost:3000"
    workspace_dir: str = "./workspaces"
    rq_queue_name: str = "codemate-index"
    clone_timeout_seconds: int = 120
    max_file_size_bytes: int = 500 * 1024
    embedding_provider: str = "mock"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = 384
    embedding_api_key: str | None = None
    embedding_base_url: str | None = None
    embedding_batch_size: int = 64
    embedding_timeout_seconds: float = 60.0
    llm_provider: str = "mock"
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_temperature: float = 0.2
    llm_timeout_seconds: float = 60.0
    llm_max_context_chars: int = 24_000
    llm_max_output_tokens: int = 4096
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    retrieval_top_k: int = 8
    retrieval_min_vector_score: float = 0.72
    retrieval_candidate_multiplier: int = 4
    retrieval_rerank_enabled: bool = True
    retrieval_context_expansion_enabled: bool = True
    retrieval_context_window: int = 1
    retrieval_context_max_extra: int = 4
    multi_repo_top_k: int = 12
    multi_repo_max_repos: int = 8
    review_context_top_k: int = 10
    review_max_diff_chars: int = 60_000
    repo_memory_max_files: int = 12
    repo_memory_max_symbols: int = 30
    ci_workflow_filename: str = "codemate-ci.yml"
    max_agent_iterations: int = 3
    sandbox_workspace_dir: str = "/tmp/codemate-runs"
    sandbox_timeout_seconds: int = 120
    sandbox_network_disabled: bool = True
    sandbox_runtime: str = "docker"
    sandbox_gvisor_docker_runtime: str = "runsc"
    sandbox_firecracker_command_template: str | None = None
    sandbox_node_image: str = "node:20-alpine"
    sandbox_python_image: str = "python:3.11-slim"
    sandbox_allowed_commands: str = "npm test,pnpm test,yarn test,pytest,python -m pytest"
    evaluation_admin_token: str | None = None
    evaluation_ci_token: str | None = None
    evaluation_read_token: str | None = None
    codemate_proxy_identity_secret: str | None = None
    codemate_proxy_identity_previous_secret: str | None = None
    codemate_proxy_identity_ttl_seconds: int = 300
    codemate_proxy_identity_nonce_store: str = "memory"
    codemate_require_signed_browser_identity: bool | None = None
    security_audit_log_path: str | None = "artifacts/security/events.jsonl"

    @cached_property
    def workspace_path(self) -> Path:
        return Path(self.workspace_dir).resolve()

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.api_cors_origins.split(",") if origin.strip()]

    @property
    def allowed_test_commands(self) -> set[str]:
        return {
            command.strip()
            for command in self.sandbox_allowed_commands.split(",")
            if command.strip()
        }

    @property
    def signed_browser_identity_required(self) -> bool:
        return bool(self.codemate_require_signed_browser_identity)

    def validate_security_config(self) -> None:
        if (
            self.app_env.strip().lower() == "production"
            and self.codemate_require_signed_browser_identity is None
        ):
            raise RuntimeError(
                "CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY must be explicitly set "
                "when APP_ENV=production."
            )


settings = Settings()
