from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.core.config import settings
from app.llm.mock_provider import MockLLMProvider


PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = PROJECT_ROOT / "examples" / "demo-cart-bug"


def load_start_demo_module():
    script_path = PROJECT_ROOT / "scripts" / "start_demo.py"
    spec = importlib.util.spec_from_file_location("codemate_start_demo", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_seed_demo_module():
    script_path = PROJECT_ROOT / "scripts" / "seed_demo.py"
    spec = importlib.util.spec_from_file_location("codemate_seed_demo", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_main_demo_rejects_mock_provider() -> None:
    launcher = load_start_demo_module()

    with pytest.raises(RuntimeError, match="LLM_PROVIDER=mock"):
        launcher.validate_real_llm({"LLM_PROVIDER": "mock"})


def test_main_demo_requires_explicit_model_and_provider_credential() -> None:
    launcher = load_start_demo_module()

    with pytest.raises(RuntimeError, match="explicit LLM_MODEL"):
        launcher.validate_real_llm({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-key"})
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        launcher.validate_real_llm({"LLM_PROVIDER": "openai", "LLM_MODEL": "test-model"})

    assert launcher.validate_real_llm(
        {
            "LLM_PROVIDER": "openai",
            "LLM_MODEL": "test-model",
            "OPENAI_API_KEY": "test-key",
        }
    ) == ("openai", "test-model")


def test_demo_fixture_is_multi_file_and_not_supported_by_mock_patch_rules() -> None:
    manifest = json.loads((FIXTURE_ROOT / "demo.json").read_text(encoding="utf-8"))
    files = {
        relative_path: (FIXTURE_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in manifest["allowed_changed_files"]
    }

    assert len(files) >= 2
    assert manifest["target_test_command"] == "npm run test:targeted"
    assert manifest["regression_test_command"] == "npm test"
    assert manifest["target_test_command"] in settings.allowed_test_commands
    assert (
        MockLLMProvider().generate_patch(
            issue=manifest["issue"],
            diagnosis="fixture contract check",
            files=files,
        )
        == ""
    )


def test_seed_demo_forwards_repository_owner_to_agent_run(monkeypatch) -> None:
    seed = load_seed_demo_module()
    database = MagicMock()
    session_context = MagicMock()
    session_context.__enter__.return_value = database
    service = MagicMock()
    service.create_fix_run.return_value = SimpleNamespace(id="demo-run")
    enqueue = MagicMock()

    monkeypatch.setattr(seed, "SessionLocal", MagicMock(return_value=session_context))
    monkeypatch.setattr(seed, "AgentService", MagicMock(return_value=service))
    monkeypatch.setattr(seed, "enqueue_agent_run", enqueue)

    run_id = seed.start_agent_run(
        {
            "repo_id": "demo-repository",
            "issue": "repair the checkout calculation",
            "target_test_command": "npm run test:targeted",
        },
        owner_id="local:demo-owner",
    )

    assert run_id == "demo-run"
    service.create_fix_run.assert_called_once_with(
        repo_id="demo-repository",
        owner_id="local:demo-owner",
        issue="repair the checkout calculation",
        test_command="npm run test:targeted",
    )
    enqueue.assert_called_once_with("demo-run")


def test_demo_import_clones_generated_fixture_without_relaxing_public_imports(
    monkeypatch, tmp_path: Path
) -> None:
    seed = load_seed_demo_module()
    monkeypatch.setattr(settings, "workspace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "app_env", "local")
    repository_path, commit_sha = seed.materialize_fixture_repository(FIXTURE_ROOT)
    workspace = tmp_path / "indexed-checkout"
    service = seed.DemoIndexService(MagicMock())

    service._clone_repository(str(repository_path), workspace)

    assert seed.run_git(["rev-parse", "HEAD"], cwd=workspace) == commit_sha
    assert (workspace / "src" / "cart.js").read_text() == (
        FIXTURE_ROOT / "src" / "cart.js"
    ).read_text()
    with pytest.raises(ValueError, match="Only HTTPS and SSH"):
        seed.IndexService(MagicMock())._clone_repository(
            str(repository_path), tmp_path / "public-checkout"
        )

    with pytest.raises(ValueError, match="generated local fixture"):
        service._clone_repository(str(tmp_path / "other.git"), tmp_path / "other-checkout")

    monkeypatch.setattr(settings, "app_env", "production")
    with pytest.raises(ValueError, match="generated local fixture"):
        service._clone_repository(str(repository_path), tmp_path / "production-checkout")


def test_demo_import_rejects_fixture_symlink(monkeypatch, tmp_path: Path) -> None:
    seed = load_seed_demo_module()
    monkeypatch.setattr(settings, "workspace_dir", str(tmp_path))
    monkeypatch.setattr(settings, "app_env", "local")
    fixture_store = tmp_path / ".demo-fixtures"
    fixture_store.mkdir()
    outside = tmp_path / "outside.git"
    outside.mkdir()
    repository_path = fixture_store / "demo-cart-bug.git"
    repository_path.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="generated local fixture"):
        seed.DemoIndexService(MagicMock())._clone_repository(
            str(repository_path), tmp_path / "checkout"
        )
