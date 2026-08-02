import json
from functools import cached_property
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_env: str = "local"
    database_url: str = "postgresql+psycopg://codemate:codemate@localhost:5432/codemate"
    database_migrations_enabled: bool = True
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "codemate_chunks"
    frontend_url: str = "http://localhost:3000"
    api_cors_origins: str = "http://localhost:3000"
    workspace_dir: str = "./workspaces"
    rq_queue_name: str = "codemate-index"
    rq_worker_readiness_required: bool = False
    rq_worker_heartbeat_interval_seconds: int = 5
    rq_worker_heartbeat_ttl_seconds: int = 20
    rq_worker_heartbeat_prefix: str = "codemate:rq:worker:heartbeat"
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
    retrieval_strategy: str = "hybrid"
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
    mcp_enabled: bool = False
    mcp_auth_token: str | None = None
    mcp_allowed_repo_ids: str = ""
    mcp_max_file_lines: int = 500
    mcp_client_enabled: bool = False
    mcp_client_api_token: str | None = None
    mcp_client_servers_json: str = "[]"
    mcp_client_timeout_seconds: float = 20.0
    mcp_client_max_result_chars: int = 50_000
    mcp_tool_router_enabled: bool = True
    mcp_tool_router_max_rounds: int = 2
    mcp_tool_router_max_calls_per_run: int = 4
    mcp_tool_router_max_catalog_tools: int = 64
    mcp_approval_enabled: bool = True
    mcp_approval_ttl_seconds: int = 1800
    mcp_approval_resume_stale_seconds: int = 300
    mcp_approval_max_checkpoint_chars: int = 2_000_000
    mcp_execution_lease_seconds: int = 60
    mcp_execution_max_attempts: int = 3
    mcp_execution_max_checkpoint_chars: int = 2_000_000
    mcp_observability_window_minutes: int = 60
    mcp_health_monitor_enabled: bool = True
    mcp_health_probe_interval_seconds: int = 60
    mcp_health_stale_seconds: int = 180
    mcp_circuit_breaker_enabled: bool = True
    mcp_circuit_failure_threshold: int = 3
    mcp_circuit_cooldown_seconds: int = 60
    mcp_circuit_half_open_lease_seconds: int = 30
    mcp_alert_unknown_age_seconds: int = 300
    mcp_alert_error_rate_threshold: float = 0.5
    mcp_alert_minimum_calls: int = 5
    mcp_registry_enabled: bool = False
    mcp_registry_kms_provider: str = "local"
    mcp_registry_kms_key_id: str | None = None
    mcp_registry_master_key: str | None = None
    mcp_registry_previous_master_key: str | None = None
    mcp_registry_key_version: int = 1
    mcp_registry_max_servers: int = 64
    mcp_registry_allowed_hosts: str = ""
    mcp_registry_allow_private_networks: bool = False
    mcp_registry_require_https: bool = True
    mcp_oauth_token_expiry_skew_seconds: int = 60
    mcp_sandbox_enabled: bool = False
    mcp_sandbox_broker_mode: bool = False
    mcp_sandbox_broker_url: str | None = None
    mcp_sandbox_broker_token: str | None = None
    mcp_egress_proxy_url: str | None = None
    mcp_egress_proxy_token: str | None = None
    mcp_egress_allowed_ports: str = "443"
    mcp_egress_connect_timeout_seconds: float = 10.0
    mcp_compliance_enabled: bool = False
    mcp_compliance_interval_seconds: int = 300
    mcp_compliance_stale_seconds: int = 900
    mcp_compliance_report_path: str = "artifacts/compliance/mcp-compliance-latest.json"
    mcp_compliance_retention_days: int = 90
    mcp_tenant_authorization_enabled: bool = False
    mcp_default_tenant_slug: str = "default"
    mcp_delegated_oauth_state_ttl_seconds: int = 600
    mcp_quota_enabled: bool = False
    mcp_quota_backend: str = "redis"
    mcp_quota_fail_closed: bool = True
    mcp_quota_redis_prefix: str = "codemate:mcp:quota"
    mcp_quota_concurrency_lease_seconds: int = 180
    mcp_quota_max_policies_per_tenant: int = 64
    mcp_quota_default_call_cost_units: float = 1.0
    mcp_quota_rejection_alert_threshold: int = 5
    mcp_quota_retention_days: int = 90
    mcp_quota_reconciliation_interval_seconds: int = 300
    otel_enabled: bool = False
    otel_service_name: str = "codemate-backend"
    otel_exporter_otlp_endpoint: str | None = None
    max_agent_iterations: int = 3
    agent_planner_mode: str = "adaptive"
    agent_max_local_tool_calls: int = 12
    agent_max_planner_calls: int = 16
    agent_max_planner_tokens: int = 24_000
    agent_max_loop_seconds: int = 600
    agent_max_no_progress_steps: int = 3
    agent_max_read_lines: int = 800
    agent_max_evidence_items: int = 40
    agent_max_action_history: int = 64
    evaluation_llm_cost_per_million_tokens_usd: float | None = None
    sandbox_workspace_dir: str = "/tmp/codemate-runs"
    sandbox_timeout_seconds: int = 120
    sandbox_network_disabled: bool = True
    sandbox_runtime: str = "docker"
    sandbox_gvisor_docker_runtime: str = "runsc"
    sandbox_firecracker_command_template: str | None = None
    sandbox_node_image: str = "node:20-alpine"
    sandbox_python_image: str = "python:3.11-slim"
    sandbox_allowed_commands: str = (
        "npm test,npm run test:health,pnpm test,yarn test,pytest,python -m pytest,"
        "python -m unittest discover,python -m unittest tests.test_health"
    )
    sandbox_execution_broker_url: str | None = None
    sandbox_execution_broker_token: str | None = None
    sandbox_docker_workspace_volume: str | None = None
    sandbox_execution_plane_enabled: bool = False
    sandbox_execution_plane_url: str | None = None
    sandbox_execution_plane_backend: str = "firecracker"
    sandbox_execution_plane_ca_path: str | None = None
    sandbox_execution_plane_cert_path: str | None = None
    sandbox_execution_plane_key_path: str | None = None
    sandbox_execution_plane_proxy_url: str | None = None
    sandbox_workload_identity_issuer: str = "codemate"
    sandbox_workload_identity_subject: str = "spiffe://codemate/code-sandbox"
    sandbox_workload_identity_audience: str = "codemate-sandbox-execution-plane"
    sandbox_workload_identity_private_key_path: str | None = None
    sandbox_workload_identity_public_key_path: str | None = None
    sandbox_workload_identity_ttl_seconds: int = 60
    sandbox_workspace_archive_max_bytes: int = 16 * 1024 * 1024
    sandbox_workspace_archive_max_files: int = 10_000
    sandbox_execution_output_max_chars: int = 200_000
    sandbox_firecracker_runner_command_json: str | None = None
    sandbox_kubernetes_namespace: str = "codemate-sandbox"
    sandbox_kubernetes_workspace_root: str = "/var/lib/codemate/workspaces"
    sandbox_kubernetes_pvc_name: str = "codemate-sandbox-workspaces"
    sandbox_kubectl_path: str = "kubectl"
    sandbox_kubernetes_node_selector_json: str = '{"codemate.io/attested-sandbox-node":"true"}'
    sandbox_execution_state_backend: str = "memory"
    sandbox_execution_state_redis_url: str | None = None
    sandbox_execution_state_prefix: str = "codemate:sandbox:execution"
    sandbox_execution_state_retention_seconds: int = 86_400
    sandbox_execution_lease_grace_seconds: int = 60
    sandbox_execution_client_max_attempts: int = 3
    sandbox_supply_chain_enabled: bool = False
    sandbox_supply_chain_cosign_path: str = "cosign"
    sandbox_supply_chain_public_key_path: str | None = None
    sandbox_supply_chain_certificate_identity_regexp: str | None = None
    sandbox_supply_chain_certificate_oidc_issuer: str | None = None
    sandbox_supply_chain_require_image_digest: bool = True
    sandbox_supply_chain_require_slsa: bool = True
    sandbox_supply_chain_slsa_source: str | None = None
    sandbox_supply_chain_slsa_builder_id: str | None = None
    sandbox_firecracker_rootfs_path: str | None = None
    sandbox_firecracker_rootfs_bundle_path: str | None = None
    sandbox_firecracker_rootfs_sha256: str | None = None
    sandbox_node_attestation_enabled: bool = False
    sandbox_node_attestation_document_path: str | None = None
    sandbox_node_attestation_public_key_path: str | None = None
    sandbox_node_attestation_expected_node_id: str | None = None
    sandbox_node_attestation_verifier_command_json: str | None = None
    sandbox_node_attestation_verifier_timeout_seconds: int = 15
    sandbox_node_attestation_allowed_tee_types: str = "tpm2,sev-snp,tdx,nitro"
    sandbox_node_attestation_allowed_measurements: str = ""
    sandbox_node_attestation_max_age_seconds: int = 300
    evaluation_admin_token: str | None = None
    evaluation_ci_token: str | None = None
    evaluation_read_token: str | None = None
    codemate_proxy_identity_secret: str | None = None
    codemate_proxy_identity_previous_secret: str | None = None
    codemate_proxy_identity_ttl_seconds: int = 300
    codemate_proxy_identity_nonce_store: str = "memory"
    codemate_require_signed_browser_identity: bool | None = None
    security_audit_log_path: str | None = "artifacts/security/events.jsonl"
    security_audit_ingest_token: str | None = None
    security_audit_export_required: bool | None = None
    security_audit_fail_closed: bool = False
    security_audit_sinks: str = ""
    security_audit_siem_url: str | None = None
    security_audit_siem_hmac_secret: str | None = None
    security_audit_s3_bucket: str | None = None
    security_audit_s3_prefix: str = "codemate/security-audit"
    security_audit_s3_retention_days: int = 365
    security_audit_delivery_interval_seconds: int = 15
    security_audit_delivery_batch_size: int = 100
    security_audit_delivery_max_attempts: int = 12
    security_audit_delivery_lease_seconds: int = 60
    security_audit_outbox_retention_days: int = 90
    aws_region: str | None = None
    aws_endpoint_url: str | None = None

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

    @property
    def mcp_repository_scope(self) -> set[str]:
        return {
            repo_id.strip()
            for repo_id in self.mcp_allowed_repo_ids.split(",")
            if repo_id.strip()
        }

    @property
    def mcp_registry_host_allowlist(self) -> set[str]:
        return {
            host.strip().lower()
            for host in self.mcp_registry_allowed_hosts.split(",")
            if host.strip()
        }

    @property
    def mcp_egress_port_allowlist(self) -> set[int]:
        try:
            return {
                int(port.strip())
                for port in self.mcp_egress_allowed_ports.split(",")
                if port.strip()
            }
        except ValueError as exc:
            raise RuntimeError("MCP_EGRESS_ALLOWED_PORTS must contain integer ports.") from exc

    @property
    def security_audit_sink_set(self) -> set[str]:
        return {sink.strip().lower() for sink in self.security_audit_sinks.split(",") if sink.strip()}

    @property
    def sandbox_node_attestation_tee_allowlist(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.sandbox_node_attestation_allowed_tee_types.split(",")
            if value.strip()
        }

    @property
    def sandbox_node_attestation_measurement_allowlist(self) -> set[str]:
        return {
            value.strip().lower()
            for value in self.sandbox_node_attestation_allowed_measurements.split(",")
            if value.strip()
        }

    @property
    def sandbox_kubernetes_node_selector(self) -> dict[str, str]:
        try:
            value = json.loads(self.sandbox_kubernetes_node_selector_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("SANDBOX_KUBERNETES_NODE_SELECTOR_JSON must be valid JSON.") from exc
        if not isinstance(value, dict) or not value or not all(
            isinstance(key, str) and isinstance(nested, str)
            for key, nested in value.items()
        ):
            raise RuntimeError(
                "SANDBOX_KUBERNETES_NODE_SELECTOR_JSON must be a non-empty string map."
            )
        return value

    def validate_security_config(self) -> None:
        normalized_env = self.app_env.strip().lower()
        agent_limits = {
            "MAX_AGENT_ITERATIONS": self.max_agent_iterations,
            "AGENT_MAX_LOCAL_TOOL_CALLS": self.agent_max_local_tool_calls,
            "AGENT_MAX_PLANNER_CALLS": self.agent_max_planner_calls,
            "AGENT_MAX_PLANNER_TOKENS": self.agent_max_planner_tokens,
            "AGENT_MAX_LOOP_SECONDS": self.agent_max_loop_seconds,
            "AGENT_MAX_NO_PROGRESS_STEPS": self.agent_max_no_progress_steps,
            "AGENT_MAX_READ_LINES": self.agent_max_read_lines,
            "AGENT_MAX_EVIDENCE_ITEMS": self.agent_max_evidence_items,
            "AGENT_MAX_ACTION_HISTORY": self.agent_max_action_history,
        }
        invalid_agent_limits = [name for name, value in agent_limits.items() if value < 1]
        if invalid_agent_limits:
            raise RuntimeError(
                f"{', '.join(invalid_agent_limits)} must be positive integers."
            )
        if self.otel_enabled and not (self.otel_exporter_otlp_endpoint or "").strip():
            raise RuntimeError(
                "OTEL_EXPORTER_OTLP_ENDPOINT is required when OTEL_ENABLED=true."
            )
        secure_env = normalized_env in {"staging", "production"}
        if self.rq_worker_heartbeat_interval_seconds < 1:
            raise RuntimeError("RQ_WORKER_HEARTBEAT_INTERVAL_SECONDS must be at least 1.")
        if (
            self.rq_worker_heartbeat_ttl_seconds
            <= self.rq_worker_heartbeat_interval_seconds * 2
        ):
            raise RuntimeError(
                "RQ_WORKER_HEARTBEAT_TTL_SECONDS must be more than twice the heartbeat interval."
            )
        if secure_env and contains_secret_placeholder(self.database_url):
            raise RuntimeError("DATABASE_URL contains a placeholder credential.")
        if secure_env and (self.aws_endpoint_url or "").strip():
            raise RuntimeError(
                "AWS_ENDPOINT_URL must be empty in staging and production; emulators cannot qualify a release."
            )
        if secure_env and self.mcp_registry_enabled:
            if self.mcp_registry_kms_provider.strip().lower() != "aws":
                raise RuntimeError(
                    "MCP_REGISTRY_KMS_PROVIDER must be aws in staging and production."
                )
            if not (self.mcp_registry_kms_key_id or "").strip():
                raise RuntimeError(
                    "MCP_REGISTRY_KMS_KEY_ID is required in staging and production."
                )
            if not self.mcp_registry_require_https:
                raise RuntimeError(
                    "MCP_REGISTRY_REQUIRE_HTTPS must be true in staging and production."
                )
            if self.mcp_registry_allow_private_networks:
                raise RuntimeError(
                    "MCP_REGISTRY_ALLOW_PRIVATE_NETWORKS must be false in staging and production."
                )
            if not self.mcp_registry_host_allowlist:
                raise RuntimeError(
                    "MCP_REGISTRY_ALLOWED_HOSTS must explicitly list trusted MCP and OAuth hosts "
                    "in staging and production."
                )
        if self.mcp_sandbox_enabled:
            if self.mcp_sandbox_broker_mode:
                if not (self.mcp_egress_proxy_url or "").strip():
                    raise RuntimeError(
                        "MCP_EGRESS_PROXY_URL is required inside the MCP sandbox broker."
                    )
                if insecure_secret(self.mcp_egress_proxy_token):
                    raise RuntimeError(
                        "MCP_EGRESS_PROXY_TOKEN must contain a non-placeholder secret of at least 32 characters."
                    )
            else:
                if not (self.mcp_sandbox_broker_url or "").startswith(("http://", "https://")):
                    raise RuntimeError(
                        "MCP_SANDBOX_BROKER_URL is required when MCP sandbox isolation is enabled."
                    )
                if not (self.mcp_egress_proxy_url or "").strip():
                    raise RuntimeError(
                        "MCP_EGRESS_PROXY_URL is required when MCP sandbox isolation is enabled."
                    )
                if insecure_secret(self.mcp_egress_proxy_token):
                    raise RuntimeError(
                        "MCP_EGRESS_PROXY_TOKEN must contain a non-placeholder secret of at least 32 characters."
                    )
            if insecure_secret(self.mcp_sandbox_broker_token):
                raise RuntimeError(
                    "MCP_SANDBOX_BROKER_TOKEN must contain a non-placeholder secret of at least 32 characters."
                )
            ports = self.mcp_egress_port_allowlist
            if not ports or any(port < 1 or port > 65535 for port in ports):
                raise RuntimeError("MCP_EGRESS_ALLOWED_PORTS contains an invalid port.")
        if secure_env and self.mcp_sandbox_enabled and self.mcp_egress_port_allowlist != {443}:
            raise RuntimeError(
                "MCP_EGRESS_ALLOWED_PORTS must be exactly 443 in staging and production."
            )
        if not secure_env and self.mcp_registry_enabled:
            provider = self.mcp_registry_kms_provider.strip().lower()
            if provider == "local" and len((self.mcp_registry_master_key or "").strip()) < 32:
                raise RuntimeError(
                    "MCP_REGISTRY_MASTER_KEY must contain at least 32 characters for local KMS."
                )
            if provider not in {"local", "aws"}:
                raise RuntimeError("MCP_REGISTRY_KMS_PROVIDER must be local or aws.")
        if secure_env and self.mcp_tenant_authorization_enabled:
            if not self.mcp_registry_enabled:
                raise RuntimeError(
                    "MCP_REGISTRY_ENABLED must be true when tenant MCP authorization is enabled."
                )
        if secure_env and self.mcp_quota_enabled:
            if not self.mcp_tenant_authorization_enabled:
                raise RuntimeError(
                    "MCP_TENANT_AUTHORIZATION_ENABLED must be true when MCP quotas are enabled."
                )
            if self.mcp_quota_backend.strip().lower() != "redis":
                raise RuntimeError("MCP_QUOTA_BACKEND must be redis in staging and production.")
            if not self.mcp_quota_fail_closed:
                raise RuntimeError("MCP_QUOTA_FAIL_CLOSED must be true in staging and production.")
        if secure_env and self.codemate_require_signed_browser_identity is None:
            raise RuntimeError(
                "CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY must be explicitly set "
                "when APP_ENV=staging or production."
            )
        if secure_env and self.codemate_require_signed_browser_identity:
            if insecure_secret(self.codemate_proxy_identity_secret):
                raise RuntimeError(
                    "CODEMATE_PROXY_IDENTITY_SECRET must contain a non-placeholder secret of at least 32 characters."
                )
        if secure_env and self.mcp_enabled:
            token = (self.mcp_auth_token or "").strip()
            if insecure_secret(token):
                raise RuntimeError(
                    "MCP_AUTH_TOKEN must contain at least 32 characters when MCP is enabled "
                    "in production."
                )
            if not self.mcp_repository_scope or contains_secret_placeholder(
                self.mcp_allowed_repo_ids
            ):
                raise RuntimeError(
                    "MCP_ALLOWED_REPO_IDS must explicitly scope the read-only MCP server "
                    "in staging and production."
                )
        if secure_env and self.mcp_client_enabled:
            token = (self.mcp_client_api_token or "").strip()
            if insecure_secret(token):
                raise RuntimeError(
                    "MCP_CLIENT_API_TOKEN must contain at least 32 characters when the MCP "
                    "client API is enabled in production."
                )
            if not self.mcp_sandbox_enabled:
                raise RuntimeError(
                    "MCP_SANDBOX_ENABLED must be true when the MCP client is enabled in staging and production."
                )
        if secure_env:
            if self.security_audit_export_required is not True:
                raise RuntimeError(
                    "SECURITY_AUDIT_EXPORT_REQUIRED must be true in staging and production."
                )
            if not self.security_audit_fail_closed:
                raise RuntimeError(
                    "SECURITY_AUDIT_FAIL_CLOSED must be true in staging and production."
                )
            sinks = self.security_audit_sink_set
            if not {"http", "s3"}.issubset(sinks):
                raise RuntimeError(
                    "SECURITY_AUDIT_SINKS must include http and s3 in staging and production."
                )
            if not (self.security_audit_siem_url or "").startswith("https://"):
                raise RuntimeError("SECURITY_AUDIT_SIEM_URL must use HTTPS.")
            if insecure_secret(self.security_audit_siem_hmac_secret):
                raise RuntimeError(
                    "SECURITY_AUDIT_SIEM_HMAC_SECRET must contain at least 32 characters."
                )
            if insecure_secret(self.security_audit_ingest_token):
                raise RuntimeError(
                    "SECURITY_AUDIT_INGEST_TOKEN must contain at least 32 characters."
                )
            if not (self.security_audit_s3_bucket or "").strip():
                raise RuntimeError("SECURITY_AUDIT_S3_BUCKET is required.")
            if self.security_audit_s3_retention_days < 30:
                raise RuntimeError("SECURITY_AUDIT_S3_RETENTION_DAYS must be at least 30.")
            if not (self.aws_region or "").strip():
                raise RuntimeError("AWS_REGION is required in staging and production.")
            if insecure_secret(self.evaluation_admin_token):
                raise RuntimeError(
                    "EVALUATION_ADMIN_TOKEN must contain a non-placeholder secret of at least "
                    "32 characters in staging and production."
                )
            if not self.rq_worker_readiness_required:
                raise RuntimeError(
                    "RQ_WORKER_READINESS_REQUIRED must be true in staging and production."
                )
            if not self.mcp_compliance_enabled:
                raise RuntimeError(
                    "MCP_COMPLIANCE_ENABLED must be true in staging and production."
                )
            if self.sandbox_runtime in {"docker", "gvisor"}:
                if not (self.sandbox_execution_broker_url or "").startswith(
                    ("http://", "https://")
                ):
                    raise RuntimeError(
                        "SANDBOX_EXECUTION_BROKER_URL is required for container sandboxes in staging and production."
                    )
                if insecure_secret(self.sandbox_execution_broker_token):
                    raise RuntimeError(
                        "SANDBOX_EXECUTION_BROKER_TOKEN must contain a non-placeholder secret of at least 32 characters."
                    )
            if self.sandbox_execution_plane_enabled:
                self._validate_execution_plane_config()

    def _validate_execution_plane_config(self) -> None:
        if not (self.sandbox_execution_plane_url or "").startswith("https://"):
            raise RuntimeError("SANDBOX_EXECUTION_PLANE_URL must use HTTPS.")
        backend = self.sandbox_execution_plane_backend.strip().lower()
        if backend not in {"firecracker", "kubernetes"}:
            raise RuntimeError(
                "SANDBOX_EXECUTION_PLANE_BACKEND must be firecracker or kubernetes."
            )
        required_paths = {
            "SANDBOX_EXECUTION_PLANE_CA_PATH": self.sandbox_execution_plane_ca_path,
            "SANDBOX_EXECUTION_PLANE_CERT_PATH": self.sandbox_execution_plane_cert_path,
            "SANDBOX_EXECUTION_PLANE_KEY_PATH": self.sandbox_execution_plane_key_path,
            "SANDBOX_WORKLOAD_IDENTITY_PRIVATE_KEY_PATH": (
                self.sandbox_workload_identity_private_key_path
            ),
        }
        missing = [name for name, value in required_paths.items() if not (value or "").strip()]
        if missing:
            raise RuntimeError(f"Missing sandbox execution plane credentials: {', '.join(missing)}")
        if not 10 <= self.sandbox_workload_identity_ttl_seconds <= 300:
            raise RuntimeError("SANDBOX_WORKLOAD_IDENTITY_TTL_SECONDS must be between 10 and 300.")

    def validate_execution_plane_server_config(
        self, *, require_workload_public_key: bool = True
    ) -> None:
        backend = self.sandbox_execution_plane_backend.strip().lower()
        if backend not in {"firecracker", "kubernetes"}:
            raise RuntimeError(
                "SANDBOX_EXECUTION_PLANE_BACKEND must be firecracker or kubernetes."
            )
        if require_workload_public_key and not (
            self.sandbox_workload_identity_public_key_path or ""
        ).strip():
            raise RuntimeError("SANDBOX_WORKLOAD_IDENTITY_PUBLIC_KEY_PATH is required.")
        state_backend = self.sandbox_execution_state_backend.strip().lower()
        if state_backend not in {"memory", "redis"}:
            raise RuntimeError("SANDBOX_EXECUTION_STATE_BACKEND must be memory or redis.")
        if self.app_env.strip().lower() in {"staging", "production"} and state_backend != "redis":
            raise RuntimeError(
                "SANDBOX_EXECUTION_STATE_BACKEND must be redis in staging and production."
            )
        if state_backend == "redis" and not (
            self.sandbox_execution_state_redis_url or self.redis_url
        ):
            raise RuntimeError("A Redis URL is required for shared sandbox execution state.")
        minimum_retention = 3600 + self.sandbox_execution_lease_grace_seconds
        if self.sandbox_execution_state_retention_seconds < minimum_retention:
            raise RuntimeError(
                "SANDBOX_EXECUTION_STATE_RETENTION_SECONDS must cover the maximum execution lease."
            )
        secure_env = self.app_env.strip().lower() in {"staging", "production"}
        if secure_env and not self.sandbox_supply_chain_enabled:
            raise RuntimeError(
                "SANDBOX_SUPPLY_CHAIN_ENABLED must be true in staging and production."
            )
        if secure_env and not self.sandbox_node_attestation_enabled:
            raise RuntimeError(
                "SANDBOX_NODE_ATTESTATION_ENABLED must be true in staging and production."
            )
        if self.sandbox_supply_chain_enabled:
            if not (self.sandbox_supply_chain_public_key_path or "").strip() and not (
                self.sandbox_supply_chain_certificate_identity_regexp
                and self.sandbox_supply_chain_certificate_oidc_issuer
            ):
                raise RuntimeError(
                    "Sandbox supply-chain verification requires a Cosign public key or keyless identity policy."
                )
            if self.sandbox_supply_chain_require_slsa and not (
                self.sandbox_supply_chain_slsa_source or ""
            ).strip():
                raise RuntimeError("SANDBOX_SUPPLY_CHAIN_SLSA_SOURCE is required.")
            if backend == "firecracker" and not all(
                (
                    self.sandbox_firecracker_rootfs_path,
                    self.sandbox_firecracker_rootfs_bundle_path,
                    self.sandbox_firecracker_rootfs_sha256,
                )
            ):
                raise RuntimeError(
                    "Firecracker supply-chain verification requires rootfs path, bundle and SHA-256."
                )
        if self.sandbox_node_attestation_enabled:
            if not (self.sandbox_node_attestation_public_key_path or "").strip():
                raise RuntimeError(
                    "A node attestation authority public key path is required."
                )
            if not (
                (self.sandbox_node_attestation_document_path or "").strip()
                or (self.sandbox_node_attestation_verifier_command_json or "").strip()
            ):
                raise RuntimeError("A node attestation document or verifier command is required.")
            if not (self.sandbox_node_attestation_expected_node_id or "").strip():
                raise RuntimeError("SANDBOX_NODE_ATTESTATION_EXPECTED_NODE_ID is required.")
            if not self.sandbox_node_attestation_measurement_allowlist:
                raise RuntimeError("A node attestation measurement allowlist is required.")
            if self.sandbox_node_attestation_verifier_timeout_seconds < 1:
                raise RuntimeError(
                    "SANDBOX_NODE_ATTESTATION_VERIFIER_TIMEOUT_SECONDS must be at least 1."
                )
            if (
                self.app_env.strip().lower() in {"staging", "production"}
                and not (self.sandbox_node_attestation_verifier_command_json or "").strip()
            ):
                raise RuntimeError(
                    "Challenge-response node attestation is required in staging and production."
                )


settings = Settings()


def insecure_secret(value: str | None) -> bool:
    normalized = (value or "").strip()
    if len(normalized) < 32:
        return True
    return contains_secret_placeholder(normalized)


def contains_secret_placeholder(value: str | None) -> bool:
    lowered = (value or "").lower()
    return any(marker in lowered for marker in ("replace-with", "change-me", "changeme"))
