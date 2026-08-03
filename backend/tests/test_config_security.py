import pytest

from app.core.config import Settings


def secure_audit_config():
    return {
        "security_audit_export_required": True,
        "security_audit_fail_closed": True,
        "security_audit_sinks": "http,s3",
        "security_audit_siem_url": "https://siem.example/events",
        "security_audit_siem_hmac_secret": "s" * 32,
        "security_audit_ingest_token": "i" * 32,
        "security_audit_s3_bucket": "codemate-audit",
        "aws_region": "ap-southeast-1",
        "codemate_proxy_identity_secret": "p" * 32,
        "rq_worker_readiness_required": True,
        "mcp_registry_allowed_hosts": "mcp.example.com,oauth.example.com",
        "evaluation_admin_token": "a" * 32,
        "product_api_token": "p" * 32,
        "repository_allowed_hosts": "github.com,gitlab.com",
        "mcp_allowed_repo_ids": "repo-production",
        "mcp_compliance_enabled": True,
        "mcp_sandbox_enabled": True,
        "mcp_sandbox_broker_url": "http://mcp-sandbox:8090",
        "mcp_sandbox_broker_token": "b" * 32,
        "mcp_egress_proxy_url": "http://mcp-egress:8080",
        "mcp_egress_proxy_token": "e" * 32,
        "sandbox_execution_broker_url": "http://code-sandbox:8070",
        "sandbox_execution_broker_token": "x" * 32,
    }


def test_production_requires_explicit_signed_browser_identity_setting(monkeypatch):
    monkeypatch.delenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", raising=False)
    settings = Settings(_env_file=None, app_env="production", **secure_audit_config())

    with pytest.raises(RuntimeError, match="CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY"):
        settings.validate_security_config()


def test_production_accepts_explicit_signed_browser_identity_false(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(_env_file=None, app_env="production", **secure_audit_config())

    settings.validate_security_config()
    assert settings.signed_browser_identity_required is False


def test_production_accepts_explicit_signed_browser_identity_true(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "true")
    settings = Settings(_env_file=None, app_env="production", **secure_audit_config())

    settings.validate_security_config()
    assert settings.signed_browser_identity_required is True


def test_production_never_allows_open_admin_mode(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    config = secure_audit_config()
    config["evaluation_admin_token"] = None

    with pytest.raises(RuntimeError, match="EVALUATION_ADMIN_TOKEN"):
        Settings(_env_file=None, app_env="production", **config).validate_security_config()


def test_local_defaults_signed_browser_identity_to_false(monkeypatch):
    monkeypatch.delenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", raising=False)
    settings = Settings(_env_file=None, app_env="local")

    settings.validate_security_config()
    assert settings.signed_browser_identity_required is False


def test_production_requires_product_token_and_git_host_allowlist(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    missing_token = secure_audit_config()
    missing_token["product_api_token"] = None
    with pytest.raises(RuntimeError, match="PRODUCT_API_TOKEN"):
        Settings(_env_file=None, app_env="production", **missing_token).validate_security_config()

    missing_hosts = secure_audit_config()
    missing_hosts["repository_allowed_hosts"] = ""
    with pytest.raises(RuntimeError, match="REPOSITORY_ALLOWED_HOSTS"):
        Settings(_env_file=None, app_env="production", **missing_hosts).validate_security_config()


def test_agent_loop_budgets_must_be_positive():
    settings = Settings(_env_file=None, app_env="local", agent_max_local_tool_calls=0)

    with pytest.raises(RuntimeError, match="AGENT_MAX_LOCAL_TOOL_CALLS"):
        settings.validate_security_config()


def test_staging_requires_kms_and_dual_remote_audit_sinks(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "true")
    with pytest.raises(RuntimeError, match="MCP_REGISTRY_KMS_PROVIDER"):
        Settings(_env_file=None, app_env="staging", mcp_registry_enabled=True).validate_security_config()
    with pytest.raises(RuntimeError, match="SECURITY_AUDIT_EXPORT_REQUIRED"):
        Settings(
            _env_file=None,
            app_env="staging",
            codemate_proxy_identity_secret="p" * 32,
        ).validate_security_config()


def test_staging_rejects_placeholder_secrets(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    config = secure_audit_config()
    config["security_audit_ingest_token"] = "replace-with-32-plus-character-secret"
    with pytest.raises(RuntimeError, match="SECURITY_AUDIT_INGEST_TOKEN"):
        Settings(_env_file=None, app_env="staging", **config).validate_security_config()


def test_production_requires_worker_readiness(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    config = secure_audit_config()
    config["rq_worker_readiness_required"] = False

    with pytest.raises(RuntimeError, match="RQ_WORKER_READINESS_REQUIRED"):
        Settings(_env_file=None, app_env="production", **config).validate_security_config()


def test_opentelemetry_requires_exporter_endpoint():
    settings = Settings(
        _env_file=None,
        app_env="local",
        otel_enabled=True,
        otel_exporter_otlp_endpoint=None,
    )

    with pytest.raises(RuntimeError, match="OTEL_EXPORTER_OTLP_ENDPOINT"):
        settings.validate_security_config()


def test_production_dynamic_registry_requires_aws_kms(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_registry_enabled=True,
        mcp_registry_kms_provider="local",
    )

    with pytest.raises(RuntimeError, match="MCP_REGISTRY_KMS_PROVIDER"):
        settings.validate_security_config()


def test_production_dynamic_registry_rejects_private_network_mode(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_registry_enabled=True,
        mcp_registry_kms_provider="aws",
        mcp_registry_kms_key_id="alias/codemate-production",
        mcp_registry_allow_private_networks=True,
    )

    with pytest.raises(RuntimeError, match="ALLOW_PRIVATE_NETWORKS"):
        settings.validate_security_config()


def test_production_dynamic_registry_requires_host_allowlist(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    config = secure_audit_config()
    config["mcp_registry_allowed_hosts"] = ""
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_registry_enabled=True,
        mcp_registry_kms_provider="aws",
        mcp_registry_kms_key_id="alias/codemate-production",
        **config,
    )

    with pytest.raises(RuntimeError, match="MCP_REGISTRY_ALLOWED_HOSTS"):
        settings.validate_security_config()


def test_production_tenant_authorization_requires_dynamic_registry(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_tenant_authorization_enabled=True,
        mcp_registry_enabled=False,
    )

    with pytest.raises(RuntimeError, match="MCP_REGISTRY_ENABLED"):
        settings.validate_security_config()


def test_production_quota_requires_tenant_auth_redis_and_fail_closed(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    base = {
        "_env_file": None,
        "app_env": "production",
        "mcp_quota_enabled": True,
        "mcp_registry_enabled": True,
        "mcp_registry_kms_provider": "aws",
        "mcp_registry_kms_key_id": "alias/codemate-production",
        "mcp_registry_allowed_hosts": "mcp.example.com",
    }
    with pytest.raises(RuntimeError, match="MCP_TENANT_AUTHORIZATION_ENABLED"):
        Settings(**base).validate_security_config()
    with pytest.raises(RuntimeError, match="MCP_QUOTA_BACKEND"):
        Settings(
            **base,
            mcp_tenant_authorization_enabled=True,
            mcp_quota_backend="database",
        ).validate_security_config()
    with pytest.raises(RuntimeError, match="MCP_QUOTA_FAIL_CLOSED"):
        Settings(
            **base,
            mcp_tenant_authorization_enabled=True,
            mcp_quota_backend="redis",
            mcp_quota_fail_closed=False,
        ).validate_security_config()


def test_production_mcp_requires_long_auth_token(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_enabled=True,
        mcp_auth_token="too-short",
    )

    with pytest.raises(RuntimeError, match="MCP_AUTH_TOKEN"):
        settings.validate_security_config()


def test_production_mcp_accepts_long_auth_token(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_enabled=True,
        mcp_auth_token="a" * 32,
        **secure_audit_config(),
    )

    settings.validate_security_config()


def test_production_mcp_requires_explicit_repository_scope(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    config = secure_audit_config()
    config["mcp_allowed_repo_ids"] = ""
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_enabled=True,
        mcp_auth_token="a" * 32,
        **config,
    )

    with pytest.raises(RuntimeError, match="MCP_ALLOWED_REPO_IDS"):
        settings.validate_security_config()


def test_production_mcp_client_requires_long_api_token(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_client_enabled=True,
        mcp_client_api_token="short",
    )

    with pytest.raises(RuntimeError, match="MCP_CLIENT_API_TOKEN"):
        settings.validate_security_config()


def test_production_mcp_client_accepts_long_api_token(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_client_enabled=True,
        mcp_client_api_token="b" * 32,
        **secure_audit_config(),
    )

    settings.validate_security_config()


def test_production_mcp_approval_requires_admin_token(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    config = secure_audit_config()
    config["evaluation_admin_token"] = None
    settings = Settings(
        _env_file=None,
        app_env="production",
        mcp_client_enabled=True,
        mcp_client_api_token="b" * 32,
        mcp_approval_enabled=True,
        **config,
    )

    with pytest.raises(RuntimeError, match="EVALUATION_ADMIN_TOKEN"):
        settings.validate_security_config()


def test_managed_execution_plane_requires_https_mtls_and_workload_key():
    configured = Settings(
        _env_file=None,
        sandbox_execution_plane_url="https://runner.internal:8443",
        sandbox_execution_plane_backend="firecracker",
        sandbox_execution_plane_ca_path="/run/ca.crt",
        sandbox_execution_plane_cert_path="/run/client.crt",
        sandbox_execution_plane_key_path="/run/client.key",
        sandbox_workload_identity_private_key_path="/run/workload.key",
        sandbox_workload_identity_ttl_seconds=60,
    )
    configured._validate_execution_plane_config()

    configured.sandbox_execution_plane_url = "http://runner.internal:8443"
    with pytest.raises(RuntimeError, match="must use HTTPS"):
        configured._validate_execution_plane_config()

    configured.sandbox_execution_plane_url = "https://runner.internal:8443"
    configured.sandbox_execution_plane_cert_path = None
    with pytest.raises(RuntimeError, match="SANDBOX_EXECUTION_PLANE_CERT_PATH"):
        configured._validate_execution_plane_config()


def test_production_execution_server_requires_shared_state_supply_chain_and_attestation():
    server = Settings(
        _env_file=None,
        app_env="production",
        sandbox_execution_plane_backend="kubernetes",
        sandbox_workload_identity_public_key_path="/run/workload.pub",
    )
    with pytest.raises(RuntimeError, match="STATE_BACKEND must be redis"):
        server.validate_execution_plane_server_config()

    server.sandbox_execution_state_backend = "redis"
    server.sandbox_execution_state_redis_url = "rediss://redis.internal/0"
    with pytest.raises(RuntimeError, match="SUPPLY_CHAIN_ENABLED"):
        server.validate_execution_plane_server_config()

    server.sandbox_supply_chain_enabled = True
    server.sandbox_supply_chain_public_key_path = "/run/cosign.pub"
    server.sandbox_supply_chain_slsa_source = "https://github.com/acme/codemate"
    with pytest.raises(RuntimeError, match="NODE_ATTESTATION_ENABLED"):
        server.validate_execution_plane_server_config()

    server.sandbox_node_attestation_enabled = True
    server.sandbox_node_attestation_public_key_path = "/run/attestation.pub"
    server.sandbox_node_attestation_expected_node_id = "node-a"
    server.sandbox_node_attestation_verifier_command_json = '["attest","{nonce}"]'
    server.sandbox_node_attestation_allowed_measurements = "approved"
    server.validate_execution_plane_server_config()
