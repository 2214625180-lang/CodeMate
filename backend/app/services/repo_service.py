import re
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.repositories.repository_repository import (
    create_repository,
    get_repository,
    list_repositories,
)


SUPPORTED_GIT_URL_PATTERN = re.compile(
    r"^(https?://[^ ]+|ssh://[^ ]+|git@[^:]+:[^ ]+)$",
    re.IGNORECASE,
)


class RepoService:
    def __init__(self, db: Session):
        self.db = db

    def create(self, repo_url: str):
        normalized_url = repo_url.strip()
        if not SUPPORTED_GIT_URL_PATTERN.match(normalized_url):
            raise ValueError("Only http(s), ssh, and git@ Git URLs are supported.")

        name = self._derive_name(normalized_url)
        return create_repository(self.db, name=name, repo_url=normalized_url)

    def list(self):
        return list_repositories(self.db)

    def get(self, repo_id: str):
        return get_repository(self.db, repo_id)

    @staticmethod
    def _derive_name(repo_url: str) -> str:
        if repo_url.startswith("git@"):
            name = repo_url.rsplit(":", 1)[-1].rstrip("/")
        else:
            parsed = urlparse(repo_url)
            name = parsed.path.rstrip("/").split("/")[-1]
        return name.removesuffix(".git") or "repository"
