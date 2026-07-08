import re
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.llm import LLMContext, get_llm_provider
from app.models.repository import Repository
from app.schemas.reviews import ReviewCitation, ReviewFinding, ReviewRequest, ReviewResponse
from app.services.retrieval_service import RetrievalResult, RetrievalService


class ReviewService:
    def __init__(self, db: Session):
        self.db = db
        self.llm = get_llm_provider()

    def review(self, *, repo_id: str, request: ReviewRequest) -> ReviewResponse:
        repository = self.db.get(Repository, repo_id)
        if repository is None:
            raise FileNotFoundError("Repository not found")
        if repository.status != "indexed":
            raise RuntimeError("Repository must be indexed before running PR Review")

        diff = (request.diff or "").strip()
        if not diff:
            diff = self._diff_refs(repository, request.base_ref or "", request.head_ref or "")
        if not diff.strip():
            raise ValueError("No diff content found for review.")

        changed_files = self._changed_files(diff)
        results = RetrievalService(self.db).retrieve(
            repo_id=repo_id,
            query=self._review_query(diff, changed_files, request.question),
            top_k=settings.review_context_top_k,
        )
        repo_names = {repository.id: repository.name}
        contexts = [self._to_context(result, repo_names) for result in results]
        raw_review = self.llm.review_pull_request(
            diff=diff[: settings.review_max_diff_chars],
            contexts=contexts,
            question=request.question,
        )
        findings = [ReviewFinding(**finding) for finding in raw_review.get("findings", [])]
        return ReviewResponse(
            summary=str(raw_review.get("summary") or "PR Review completed."),
            changed_files=changed_files or raw_review.get("changed_files", []),
            findings=findings,
            citations=[self._to_citation(result, repo_names) for result in results[:8]],
        )

    def _diff_refs(self, repository: Repository, base_ref: str, head_ref: str) -> str:
        if repository.local_path is None:
            raise FileNotFoundError("Repository workspace is not available")
        workspace = Path(repository.local_path)
        self._run_git(workspace, ["fetch", "--all", "--prune"], allow_failure=True)
        result = self._run_git(
            workspace,
            ["diff", "--find-renames", "--unified=80", f"{base_ref}...{head_ref}"],
        )
        return result.stdout

    def _run_git(
        self,
        workspace: Path,
        args: list[str],
        *,
        allow_failure: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", "-C", str(workspace), *args],
            capture_output=True,
            text=True,
            timeout=settings.clone_timeout_seconds,
            check=False,
        )
        if result.returncode != 0 and not allow_failure:
            message = result.stderr.strip() or result.stdout.strip() or "git command failed"
            raise RuntimeError(message)
        return result

    def _changed_files(self, diff: str) -> list[str]:
        files: list[str] = []
        for match in re.finditer(r"^diff --git a/(.*?) b/(.*?)$", diff, re.MULTILINE):
            for path in (match.group(2), match.group(1)):
                if path != "/dev/null" and path not in files:
                    files.append(path)
                    break
        if files:
            return files
        for match in re.finditer(r"^\+\+\+ b/(.*?)$", diff, re.MULTILINE):
            path = match.group(1)
            if path != "/dev/null" and path not in files:
                files.append(path)
        return files

    def _review_query(
        self,
        diff: str,
        changed_files: list[str],
        question: str | None,
    ) -> str:
        additions = []
        for line in diff.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                additions.append(line[1:].strip())
            if len(additions) >= 80:
                break
        return "\n".join(
            piece
            for piece in [
                question or "PR review code changes risk behavior tests",
                " ".join(changed_files),
                "\n".join(additions),
            ]
            if piece
        )

    def _to_context(self, result: RetrievalResult, repo_names: dict[str, str]) -> LLMContext:
        chunk = result.chunk
        return LLMContext(
            chunk_id=chunk.id,
            file_path=chunk.file_path,
            symbol_name=chunk.symbol_name,
            symbol_type=chunk.symbol_type,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            content=chunk.content or "",
            repo_id=chunk.repo_id,
            repo_name=repo_names.get(chunk.repo_id),
        )

    def _to_citation(self, result: RetrievalResult, repo_names: dict[str, str]) -> ReviewCitation:
        chunk = result.chunk
        return ReviewCitation(
            chunk_id=chunk.id,
            repo_id=chunk.repo_id,
            repo_name=repo_names.get(chunk.repo_id),
            file_path=chunk.file_path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            symbol_name=chunk.symbol_name,
            symbol_type=chunk.symbol_type,
        )
