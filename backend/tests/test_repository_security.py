import socket
import subprocess

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.core.time import utc_now
from app.models.repository import Repository
from app.schemas.repos import RepositoryRead
from app.services import index_service, repo_service
from app.services.index_service import IndexService


def public_address_info(_host: str, *_args, **_kwargs):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]


def make_index_service(tmp_path) -> IndexService:
    engine = create_engine(f"sqlite:///{tmp_path / 'repository-security.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    return IndexService(db)


def test_git_url_rejects_credentials_private_targets_and_untrusted_hosts(monkeypatch):
    monkeypatch.setattr(repo_service.socket, "getaddrinfo", public_address_info)
    monkeypatch.setattr(repo_service.settings, "repository_allowed_hosts", "github.com")

    with pytest.raises(ValueError, match="userinfo"):
        repo_service.validate_git_url("https://token:secret@github.com/acme/repo.git")
    with pytest.raises(ValueError, match="allowlisted"):
        repo_service.validate_git_url("https://gitlab.com/acme/repo.git")

    monkeypatch.setattr(repo_service.settings, "repository_allowed_hosts", "")
    monkeypatch.setattr(
        repo_service.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))
        ],
    )
    with pytest.raises(ValueError, match="public network"):
        repo_service.resolve_public_git_host("127.0.0.1")
    with pytest.raises(ValueError, match="Only HTTPS and SSH"):
        repo_service.validate_git_url("file:///tmp/repository.git")


def test_git_url_accepts_public_https_and_rechecks_dns_at_clone_time(monkeypatch, tmp_path):
    monkeypatch.setattr(repo_service.socket, "getaddrinfo", public_address_info)
    validated = repo_service.validate_git_url("https://github.com/acme/repo.git")
    assert validated.host == "github.com"

    service = make_index_service(tmp_path)
    clone_validation_calls: list[str] = []

    def record_validation(url: str, *, resolve_host: bool):
        clone_validation_calls.append(url)
        return validated

    monkeypatch.setattr(index_service, "validate_git_url", record_validation)
    monkeypatch.setattr(
        index_service.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "clone"],
            returncode=1,
            stdout="",
            stderr="fatal: https://token:secret@github.com/acme/repo.git denied",
        ),
    )

    with pytest.raises(RuntimeError, match="Repository clone failed") as exc_info:
        service._clone_repository("https://github.com/acme/repo.git", tmp_path / "workspace")

    assert "token" not in str(exc_info.value)
    assert clone_validation_calls == ["https://github.com/acme/repo.git"]


def test_checkout_budget_rejects_large_repositories_and_submodules(monkeypatch, tmp_path):
    service = make_index_service(tmp_path)
    monkeypatch.setattr(index_service.settings, "repository_max_clone_bytes", 8)
    monkeypatch.setattr(index_service.settings, "repository_max_clone_files", 2)

    monkeypatch.setattr(
        service,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "ls-tree"],
            returncode=0,
            stdout="100644 blob abc 9\tsrc/main.py\0",
            stderr="",
        ),
    )
    with pytest.raises(RuntimeError, match="clone budget"):
        service._assert_checkout_budget(tmp_path)

    monkeypatch.setattr(
        service,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=["git", "ls-tree"],
            returncode=0,
            stdout="160000 commit abc -\tvendor/module\0",
            stderr="",
        ),
    )
    with pytest.raises(RuntimeError, match="submodules"):
        service._assert_checkout_budget(tmp_path)


def test_indexer_skips_symlinks_that_escape_the_workspace(tmp_path):
    service = make_index_service(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "safe.py").write_text("def safe():\n    return True\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("secret = 'host-file'\n", encoding="utf-8")
    (workspace / "escape.py").symlink_to(outside)

    scanned = service._scan_source_files(workspace)

    assert [item.relative_path for item in scanned] == ["safe.py"]


def test_repository_response_redacts_legacy_url_userinfo():
    response = RepositoryRead(
        id="legacy-repository",
        name="legacy",
        repo_url="https://token:secret@example.com/acme/repo.git",
        status="pending",
        error_message=None,
        language_summary={},
        last_commit_hash=None,
        file_count=0,
        chunk_count=0,
        indexed_at=None,
        created_at=utc_now(),
        updated_at=utc_now(),
    )

    serialized = response.model_dump()

    assert serialized["repo_url"] == "https://example.com/acme/repo.git"


def test_index_status_does_not_persist_provider_exception_details(monkeypatch, tmp_path):
    service = make_index_service(tmp_path)
    repository = Repository(
        id="provider-error-repository",
        name="provider-error",
        repo_url="https://example.com/acme/repo.git",
    )
    service.db.add(repository)
    service.db.commit()

    def raise_provider_error(_repository):
        raise RuntimeError("provider rejected Authorization: Bearer secret-token")

    monkeypatch.setattr(service, "_index_full", raise_provider_error)
    service.index_repository(repository.id, full=True)
    service.db.refresh(repository)

    assert repository.status == "failed"
    assert repository.error_message == (
        "Repository indexing failed. Check repository contents and configuration."
    )
