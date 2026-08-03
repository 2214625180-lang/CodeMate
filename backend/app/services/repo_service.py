import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.repositories.repository_repository import (
    create_repository,
    get_repository,
    get_repository_for_owner,
    list_repositories,
    list_repositories_for_owner,
)
from app.core.config import settings


SCP_GIT_URL_PATTERN = re.compile(r"^git@(?P<host>[^:/\s]+):(?P<path>[^\s]+)$")


@dataclass(frozen=True)
class ValidatedGitUrl:
    normalized_url: str
    host: str


def validate_git_url(repo_url: str, *, resolve_host: bool = True) -> ValidatedGitUrl:
    """Validate a remote before it reaches the Git transport.

    The validation is repeated immediately before cloning because initial URL
    validation alone cannot protect against a hostname whose DNS answer changes.
    Network egress policy remains the final enforcement point in managed deployments.
    """
    normalized_url = repo_url.strip()
    if not normalized_url or any(character.isspace() for character in normalized_url):
        raise ValueError("Repository URL must not contain whitespace.")

    scp_match = SCP_GIT_URL_PATTERN.fullmatch(normalized_url)
    if scp_match:
        host = validate_git_host(scp_match.group("host"))
        path = scp_match.group("path")
        if not path or path.startswith("-"):
            raise ValueError("Repository URL has an invalid path.")
        validated = ValidatedGitUrl(
            normalized_url=f"git@{host}:{path}",
            host=host,
        )
    else:
        parsed = urlparse(normalized_url)
        scheme = parsed.scheme.lower()
        allowed_schemes = {"https", "ssh"}
        if settings.repository_allow_http:
            allowed_schemes.add("http")
        if scheme not in allowed_schemes:
            raise ValueError("Only HTTPS and SSH Git URLs are supported.")
        if parsed.username or parsed.password:
            raise ValueError("Repository URLs must not contain userinfo or credentials.")
        if parsed.query or parsed.fragment:
            raise ValueError("Repository URLs must not contain query parameters or fragments.")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Repository URL has an invalid port.") from exc
        if not parsed.hostname or not parsed.path or parsed.path == "/":
            raise ValueError("Repository URL must include a host and repository path.")
        if port not in {None, 443 if scheme in {"http", "https"} else 22}:
            raise ValueError("Repository URL uses a disallowed port.")
        host = validate_git_host(parsed.hostname)
        validated = ValidatedGitUrl(normalized_url=normalized_url, host=host)

    if resolve_host:
        resolve_public_git_host(validated.host)
    return validated


def validate_git_host(host: str) -> str:
    normalized_host = host.rstrip(".").lower()
    if not normalized_host or len(normalized_host) > 253:
        raise ValueError("Repository URL has an invalid host.")
    if settings.repository_host_allowlist and normalized_host not in settings.repository_host_allowlist:
        raise ValueError("Repository host is not allowlisted.")
    return normalized_host


def resolve_public_git_host(host: str) -> tuple[str, ...]:
    try:
        addresses = {
            record[4][0]
            for record in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise ValueError("Repository host could not be resolved.") from exc
    if not addresses:
        raise ValueError("Repository host could not be resolved.")

    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("Repository host resolved to an invalid address.") from exc
        if not parsed.is_global:
            raise ValueError("Repository host must resolve to public network addresses.")
    return tuple(sorted(addresses))


class RepoService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, repo_url: str, *, owner_id: str):
        validated_url = validate_git_url(repo_url)
        name = self._derive_name(validated_url.normalized_url)
        repository = create_repository(
            self.db,
            name=name,
            repo_url=validated_url.normalized_url,
            owner_id=owner_id,
        )
        from app.services.mcp_tenancy_service import MCPTenancyService

        repository.tenant_id = MCPTenancyService(self.db).default_tenant().id
        self.db.add(repository)
        self.db.commit()
        self.db.refresh(repository)
        return repository

    def list(self):
        return list_repositories(self.db)

    def list_for_owner(self, owner_id: str):
        return list_repositories_for_owner(self.db, owner_id)

    def get(self, repo_id: str):
        return get_repository(self.db, repo_id)

    def get_for_owner(self, repo_id: str, owner_id: str):
        return get_repository_for_owner(self.db, repo_id, owner_id)

    @staticmethod
    def _derive_name(repo_url: str) -> str:
        if repo_url.startswith("git@"):
            name = repo_url.rsplit(":", 1)[-1].rstrip("/")
        else:
            parsed = urlparse(repo_url)
            name = parsed.path.rstrip("/").split("/")[-1]
        return name.removesuffix(".git") or "repository"
