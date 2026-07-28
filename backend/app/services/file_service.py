from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.code_file import CodeFile
from app.models.repository import Repository


class FileService:
    def __init__(self, db: Session):
        self.db = db

    def list_files(self, repo_id: str) -> list[CodeFile]:
        return list(
            self.db.execute(
                select(CodeFile)
                .where(CodeFile.repo_id == repo_id)
                .order_by(CodeFile.file_path.asc())
            )
            .scalars()
            .all()
        )

    def read_content(
        self,
        *,
        repo_id: str,
        file_path: str,
        start_line: int | None = None,
        end_line: int | None = None,
    ) -> tuple[CodeFile | None, int, int, str]:
        repository = self.db.get(Repository, repo_id)
        if repository is None or repository.local_path is None:
            raise FileNotFoundError("Repository workspace is not available")

        code_file = self.db.execute(
            select(CodeFile)
            .where(CodeFile.repo_id == repo_id)
            .where(CodeFile.file_path == file_path)
        ).scalar_one_or_none()
        if code_file is None:
            raise FileNotFoundError("File not found in repository index")

        root = Path(repository.local_path).resolve()
        absolute_path = (root / file_path).resolve()
        try:
            absolute_path.relative_to(root)
        except ValueError as exc:
            raise PermissionError("Invalid file path") from exc

        lines = absolute_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        safe_start = max(start_line or 1, 1)
        safe_end = min(end_line or len(lines), len(lines))
        if safe_end < safe_start:
            safe_end = safe_start

        content = "\n".join(lines[safe_start - 1 : safe_end])
        return code_file, safe_start, safe_end, content
