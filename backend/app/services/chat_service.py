import json
from collections.abc import Iterator

from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.config import settings
from app.llm import LLMContext, get_llm_provider
from app.models.repository import Repository
from app.schemas.chat import CodeCitation
from app.services.retrieval_service import RetrievalResult, RetrievalService


class ChatService:
    """Stream an answer and citations from the same bounded retrieval result set.

    Retrieval completes before generation so the model receives only indexed
    contexts. Citations are emitted from those same results after answer tokens;
    generated text cannot invent a new source reference for the API to endorse.
    """

    def __init__(self, db: Session):
        self.db = db
        self.llm_provider = get_llm_provider()

    def stream_chat(self, *, repo_id: str, question: str) -> Iterator[str]:
        try:
            results = RetrievalService(self.db).retrieve(repo_id=repo_id, query=question)
            repo_names = self._repo_names(results)
            contexts = [self._to_context(result, repo_names) for result in results]

            for token in self.llm_provider.stream_answer(question=question, contexts=contexts):
                yield self._event("token", {"content": token})

            citations = [self._to_citation(result, repo_names) for result in results[:5]]
            for citation in citations:
                yield self._event("citation", citation.model_dump())

            yield self._event(
                "done",
                {
                    "citation_count": len(citations),
                    "found": bool(citations),
                },
            )
        except Exception as exc:  # noqa: BLE001 - surface stream-safe API error.
            yield self._event("error", {"message": str(exc)})

    def stream_multi_repo_chat(self, *, repo_ids: list[str], question: str) -> Iterator[str]:
        try:
            results = RetrievalService(self.db).retrieve_many(
                repo_ids=repo_ids,
                query=question,
                top_k=settings.multi_repo_top_k,
            )
            repo_names = self._repo_names(results)
            contexts = [self._to_context(result, repo_names) for result in results]

            for token in self.llm_provider.stream_answer(question=question, contexts=contexts):
                yield self._event("token", {"content": token})

            citations = [self._to_citation(result, repo_names) for result in results[:8]]
            for citation in citations:
                yield self._event("citation", citation.model_dump())

            yield self._event(
                "done",
                {
                    "citation_count": len(citations),
                    "found": bool(citations),
                    "repo_count": len(set(repo_ids)),
                },
            )
        except Exception as exc:  # noqa: BLE001 - surface stream-safe API error.
            yield self._event("error", {"message": str(exc)})

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

    def _to_citation(self, result: RetrievalResult, repo_names: dict[str, str]) -> CodeCitation:
        chunk = result.chunk
        return CodeCitation(
            chunk_id=chunk.id,
            repo_id=chunk.repo_id,
            repo_name=repo_names.get(chunk.repo_id),
            file_path=chunk.file_path,
            start_line=chunk.start_line,
            end_line=chunk.end_line,
            symbol_name=chunk.symbol_name,
            symbol_type=chunk.symbol_type,
        )

    def _repo_names(self, results: list[RetrievalResult]) -> dict[str, str]:
        repo_ids = sorted({result.chunk.repo_id for result in results})
        if not repo_ids:
            return {}
        rows = self.db.execute(
            select(Repository.id, Repository.name).where(Repository.id.in_(repo_ids))
        ).all()
        return {repo_id: name for repo_id, name in rows}

    def _event(self, event: str, data: dict) -> str:
        # Keep each JSON payload on one data line. The fetch-based frontend parser
        # treats the blank line as the frame boundary and reads one data field.
        return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
