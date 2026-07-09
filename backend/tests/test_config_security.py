import pytest

from app.core.config import Settings


def test_production_requires_explicit_signed_browser_identity_setting(monkeypatch):
    monkeypatch.delenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", raising=False)
    settings = Settings(_env_file=None, app_env="production")

    with pytest.raises(RuntimeError, match="CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY"):
        settings.validate_security_config()


def test_production_accepts_explicit_signed_browser_identity_false(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "false")
    settings = Settings(_env_file=None, app_env="production")

    settings.validate_security_config()
    assert settings.signed_browser_identity_required is False


def test_production_accepts_explicit_signed_browser_identity_true(monkeypatch):
    monkeypatch.setenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", "true")
    settings = Settings(_env_file=None, app_env="production")

    settings.validate_security_config()
    assert settings.signed_browser_identity_required is True


def test_local_defaults_signed_browser_identity_to_false(monkeypatch):
    monkeypatch.delenv("CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY", raising=False)
    settings = Settings(_env_file=None, app_env="local")

    settings.validate_security_config()
    assert settings.signed_browser_identity_required is False
