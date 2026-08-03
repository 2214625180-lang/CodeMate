import re
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import Text, and_, func, literal, literal_column, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.embeddings.code_text import build_query_embedding_text
from app.embeddings.factory import get_embedding_provider
from app.models.code_chunk import CodeChunk
from app.vectorstore.qdrant_store import QdrantVectorStore


@dataclass(slots=True)
class QueryTerms:
    keywords: list[str]
    file_paths: list[str]
    symbols: list[str]
    error_terms: list[str]


@dataclass(slots=True)
class RetrievalResult:
    chunk: CodeChunk
    score: float
    source: str


class RetrievalService:
    RRF_K = 60
    CHINESE_HINTS = {
        "登录": ["login", "auth", "signin", "sign_in", "authenticate", "session", "token"],
        "认证": ["auth", "authenticate", "authorization", "token", "session"],
        "鉴权": ["auth", "authorization", "permission", "token"],
        "路由": ["route", "router", "routes"],
        "订单": ["order", "checkout"],
        "库存": ["inventory", "stock"],
        "支付": ["payment", "billing", "invoice"],
        "用户": ["user", "account", "profile"],
        "刷新": ["refresh", "renew"],
        "过期": ["expire", "expired", "expiry", "timeout"],
    }
    STOPWORDS = {
        "the",
        "and",
        "for",
        "with",
        "where",
        "what",
        "how",
        "why",
        "this",
        "that",
        "逻辑",
        "哪里",
        "在哪",
        "实现",
        "代码",
    }
    IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")

    def __init__(self, db: Session):
        self.db = db
        self.embedding_provider = get_embedding_provider()
        self.vector_store = QdrantVectorStore()

    def retrieve(
        self,
        *,
        repo_id: str,
        query: str,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        return self.retrieve_many(repo_ids=[repo_id], query=query, top_k=top_k)

    def retrieve_many(
        self,
        *,
        repo_ids: list[str],
        query: str,
        top_k: int | None = None,
    ) -> list[RetrievalResult]:
        scoped_repo_ids = self._bounded_repo_ids(repo_ids)
        if not scoped_repo_ids:
            return []

        limit = top_k or settings.retrieval_top_k
        candidate_limit = max(limit * settings.retrieval_candidate_multiplier, limit)
        terms = self.rewrite_query(query)
        strategy = settings.retrieval_strategy.strip().lower()
        if strategy not in {"vector", "hybrid"}:
            raise ValueError(
                "RETRIEVAL_STRATEGY must be either 'vector' or 'hybrid'"
            )

        keyword_results: list[RetrievalResult] = []
        if strategy == "hybrid":
            keyword_results = self._keyword_search(
                scoped_repo_ids,
                terms,
                limit=candidate_limit * 2,
            )

        vector_results = [
            result
            for result in self._vector_search(
                scoped_repo_ids,
                query,
                terms,
                limit=candidate_limit,
            )
            if result.score >= settings.retrieval_min_vector_score
        ]

        candidates = (
            self._reciprocal_rank_fusion(
                keyword_results=keyword_results,
                vector_results=vector_results,
            )
            if strategy == "hybrid"
            else vector_results
        )
        if settings.retrieval_rerank_enabled:
            ranked = self._rerank(candidates, query=query, terms=terms)
        else:
            ranked = sorted(candidates, key=lambda item: (-item.score, item.chunk.id))

        results = ranked[:limit]
        if settings.retrieval_context_expansion_enabled:
            return self._expand_context(repo_ids=scoped_repo_ids, results=results)
        return results

    def rewrite_query(self, query: str) -> QueryTerms:
        file_paths = re.findall(r"[\w./@-]+\.(?:ts|tsx|js|jsx|py|vue)", query)
        error_terms = re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*(?:Error|Exception)\b", query)
        symbols = re.findall(r"\b[A-Za-z_$][A-Za-z0-9_$]{2,}\b", query)

        keywords = set(symbols + error_terms)
        for path in file_paths:
            keywords.update(part for part in re.split(r"[/_.-]+", path) if part)
        for chinese, hints in self.CHINESE_HINTS.items():
            if chinese in query:
                keywords.update(hints)

        for token in re.split(r"[^A-Za-z0-9_$]+", query):
            if len(token) >= 2:
                keywords.add(token)

        normalized = [
            keyword.lower()
            for keyword in keywords
            if keyword.lower() not in self.STOPWORDS
        ]

        return QueryTerms(
            keywords=sorted(set(normalized)),
            file_paths=sorted(set(file_paths)),
            symbols=sorted(set(symbols)),
            error_terms=sorted(set(error_terms)),
        )

    def _keyword_search(
        self,
        repo_ids: list[str],
        terms: QueryTerms,
        limit: int,
    ) -> list[RetrievalResult]:
        search_terms = self._bounded_terms(
            [*terms.keywords, *terms.file_paths, *terms.symbols, *terms.error_terms]
        )
        if not search_terms:
            return []

        if self.db.get_bind().dialect.name == "postgresql":
            return self._postgres_fts_search(repo_ids, search_terms, limit=limit)

        conditions = []
        for term in search_terms:
            pattern = f"%{term}%"
            conditions.extend(
                [
                    CodeChunk.file_path.ilike(pattern),
                    CodeChunk.symbol_name.ilike(pattern),
                    CodeChunk.content.ilike(pattern),
                ]
            )

        statement = (
            select(CodeChunk)
            .where(CodeChunk.repo_id.in_(repo_ids))
            .where(or_(*conditions))
            .order_by(CodeChunk.file_path.asc(), CodeChunk.start_line.asc(), CodeChunk.id.asc())
            .limit(limit)
        )
        chunks = list(self.db.execute(statement).scalars().all())

        results = [
            RetrievalResult(
                chunk=chunk,
                score=self._keyword_score(chunk, search_terms),
                source="keyword",
            )
            for chunk in chunks
        ]
        return sorted(results, key=lambda item: (-item.score, item.chunk.id))

    def _postgres_fts_search(
        self,
        repo_ids: list[str],
        search_terms: list[str],
        *,
        limit: int,
    ) -> list[RetrievalResult]:
        statement = self._postgres_fts_statement(
            repo_ids=repo_ids,
            search_terms=search_terms,
            limit=limit,
        )
        rows = self.db.execute(statement).all()
        return [
            RetrievalResult(chunk=chunk, score=float(score), source="keyword")
            for chunk, score in rows
        ]

    @staticmethod
    def _postgres_fts_statement(
        *,
        repo_ids: list[str],
        search_terms: list[str],
        limit: int,
    ):
        config = literal_column("'simple'")
        empty_text = literal("", type_=Text())

        def weighted_vector(column, weight: str):
            return func.setweight(
                func.to_tsvector(config, func.coalesce(column, empty_text)),
                literal_column(f"'{weight}'"),
            )

        document = weighted_vector(CodeChunk.symbol_name, "A")
        document = document.op("||")(weighted_vector(CodeChunk.file_path, "B"))
        document = document.op("||")(weighted_vector(CodeChunk.summary, "C"))
        document = document.op("||")(weighted_vector(CodeChunk.content, "D"))
        tsquery = func.plainto_tsquery(config, search_terms[0])
        for term in search_terms[1:]:
            tsquery = tsquery.op("||")(func.plainto_tsquery(config, term))
        rank = func.ts_rank_cd(document, tsquery, 32).label("keyword_score")
        return (
            select(CodeChunk, rank)
            .where(CodeChunk.repo_id.in_(repo_ids))
            .where(document.op("@@")(tsquery))
            .order_by(rank.desc(), CodeChunk.id.asc())
            .limit(limit)
        )

    def _vector_search(
        self,
        repo_ids: list[str],
        query: str,
        terms: QueryTerms,
        limit: int,
    ) -> list[RetrievalResult]:
        try:
            query_text = build_query_embedding_text(
                query=query,
                keywords=terms.keywords,
                file_paths=terms.file_paths,
                symbols=terms.symbols,
                error_terms=terms.error_terms,
            )
            query_vector = self.embedding_provider.embed_texts([query_text])[0]
            points = []
            for repo_id in repo_ids:
                points.extend(
                    self.vector_store.search_repo_chunks(
                        repo_id=repo_id,
                        query_vector=query_vector,
                        limit=limit,
                    )
                )
        except Exception:  # noqa: BLE001 - keyword retrieval should still work without Qdrant.
            return []

        scored_ids: dict[str, float] = {}
        for point in points:
            payload = point.payload or {}
            chunk_id = payload.get("chunk_id")
            if isinstance(chunk_id, str):
                scored_ids[chunk_id] = max(scored_ids.get(chunk_id, float("-inf")), float(point.score))

        if not scored_ids:
            return []

        chunks_by_id = {
            chunk.id: chunk
            for chunk in self.db.execute(
                select(CodeChunk)
                .where(CodeChunk.repo_id.in_(repo_ids))
                .where(CodeChunk.id.in_(scored_ids))
            )
            .scalars()
        }

        return [
            RetrievalResult(chunk=chunks_by_id[chunk_id], score=score, source="vector")
            for chunk_id, score in sorted(
                scored_ids.items(), key=lambda item: (-item[1], item[0])
            )
            if chunk_id in chunks_by_id
        ]

    def _reciprocal_rank_fusion(
        self,
        *,
        keyword_results: list[RetrievalResult],
        vector_results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        fused: dict[str, RetrievalResult] = {}
        source_signals: dict[str, set[str]] = {}
        for source, results in (("keyword", keyword_results), ("vector", vector_results)):
            seen_ids: set[str] = set()
            for rank, result in enumerate(results, start=1):
                chunk_id = result.chunk.id
                if chunk_id in seen_ids:
                    continue
                seen_ids.add(chunk_id)
                existing = fused.get(chunk_id)
                if existing is None:
                    existing = RetrievalResult(chunk=result.chunk, score=0.0, source=source)
                    fused[chunk_id] = existing
                existing.score += 1.0 / (self.RRF_K + rank)
                source_signals.setdefault(chunk_id, set()).add(source)

        for chunk_id, result in fused.items():
            if len(source_signals[chunk_id]) > 1:
                result.source = "hybrid"
        return sorted(fused.values(), key=lambda item: (-item.score, item.chunk.id))

    def _rerank(
        self,
        results: list[RetrievalResult],
        *,
        query: str,
        terms: QueryTerms,
    ) -> list[RetrievalResult]:
        if not results:
            return []

        bounded_terms = self._bounded_terms(
            [*terms.keywords, *terms.file_paths, *terms.symbols, *terms.error_terms]
        )
        max_initial_score = max(abs(result.score) for result in results) or 1.0
        for result in results:
            result.score = self._rerank_score(
                result,
                query=query,
                terms=terms,
                bounded_terms=bounded_terms,
                max_initial_score=max_initial_score,
            )
            if "rerank" not in result.source:
                result.source = f"{result.source}+rerank"

        return sorted(results, key=lambda item: (-item.score, item.chunk.id))

    def _rerank_score(
        self,
        result: RetrievalResult,
        *,
        query: str,
        terms: QueryTerms,
        bounded_terms: list[str],
        max_initial_score: float,
    ) -> float:
        chunk = result.chunk
        haystack = self._ranking_text(chunk)
        symbol_name = (chunk.symbol_name or "").lower()
        file_path = chunk.file_path.lower()
        query_lower = query.lower()

        score = (result.score / max_initial_score) * 2.0
        if result.source == "hybrid":
            score += 1.0
        elif result.source == "vector":
            score += 0.35

        if bounded_terms:
            hits = sum(1 for term in bounded_terms if term in haystack)
            score += (hits / len(bounded_terms)) * 5.0

        for file_path_query in terms.file_paths:
            lowered_path = file_path_query.lower()
            if file_path == lowered_path or file_path.endswith(lowered_path):
                score += 6.0
            elif lowered_path in file_path:
                score += 3.0

        for symbol in terms.symbols:
            lowered_symbol = symbol.lower()
            if symbol_name == lowered_symbol:
                score += 5.0
            elif lowered_symbol in symbol_name:
                score += 2.5

        for error_term in terms.error_terms:
            if error_term.lower() in haystack:
                score += 3.0

        for identifier in self.IDENTIFIER_RE.findall(query_lower):
            if identifier in symbol_name:
                score += 1.5

        return score

    def _ranking_text(self, chunk: CodeChunk) -> str:
        metadata = " ".join(
            str(value)
            for value in [
                chunk.file_path,
                chunk.language,
                chunk.symbol_name or "",
                chunk.symbol_type or "",
                " ".join(chunk.imports or []),
                " ".join(chunk.exports or []),
            ]
        )
        return f"{metadata}\n{chunk.content or ''}".lower()

    def _expand_context(
        self,
        *,
        repo_ids: list[str],
        results: list[RetrievalResult],
    ) -> list[RetrievalResult]:
        if not results or settings.retrieval_context_window <= 0:
            return results

        file_ids = sorted({result.chunk.file_id for result in results})
        if not file_ids:
            return results

        chunks_by_file = self._chunks_by_file(repo_ids=repo_ids, file_ids=file_ids)
        seen_ids = {result.chunk.id for result in results}
        expanded: list[RetrievalResult] = []
        extra_count = 0

        for result in results:
            expanded.append(result)
            if extra_count >= settings.retrieval_context_max_extra:
                continue
            for chunk in self._neighbor_chunks(
                result.chunk,
                chunks_by_file.get(result.chunk.file_id, []),
            ):
                if chunk.id in seen_ids:
                    continue
                seen_ids.add(chunk.id)
                expanded.append(
                    RetrievalResult(
                        chunk=chunk,
                        score=result.score * 0.65,
                        source=f"{result.source}+expanded",
                    )
                )
                extra_count += 1
                if extra_count >= settings.retrieval_context_max_extra:
                    break

        return expanded

    def _chunks_by_file(
        self,
        *,
        repo_ids: list[str],
        file_ids: list[str],
    ) -> dict[str, list[CodeChunk]]:
        statement = (
            select(CodeChunk)
            .where(CodeChunk.repo_id.in_(repo_ids))
            .where(CodeChunk.file_id.in_(file_ids))
            .where(
                and_(
                    CodeChunk.start_line.is_not(None),
                    CodeChunk.end_line.is_not(None),
                )
            )
            .order_by(CodeChunk.file_id, CodeChunk.start_line, CodeChunk.end_line)
        )
        chunks = list(self.db.execute(statement).scalars().all())
        grouped: dict[str, list[CodeChunk]] = {}
        for chunk in chunks:
            grouped.setdefault(chunk.file_id, []).append(chunk)
        return grouped

    def _bounded_repo_ids(self, repo_ids: list[str]) -> list[str]:
        bounded: list[str] = []
        for repo_id in repo_ids:
            normalized = repo_id.strip()
            if not normalized or normalized in bounded:
                continue
            bounded.append(normalized)
            if len(bounded) >= settings.multi_repo_max_repos:
                break
        return bounded

    def _neighbor_chunks(self, seed: CodeChunk, chunks: list[CodeChunk]) -> list[CodeChunk]:
        try:
            index = next(position for position, chunk in enumerate(chunks) if chunk.id == seed.id)
        except StopIteration:
            return []

        selected: list[CodeChunk] = []
        for chunk in chunks:
            if self._contains_chunk(parent=chunk, child=seed):
                selected.append(chunk)

        window = settings.retrieval_context_window
        selected.extend(chunks[max(index - window, 0) : index])
        selected.extend(chunks[index + 1 : index + 1 + window])
        return self._unique_chunks(selected)

    def _contains_chunk(self, *, parent: CodeChunk, child: CodeChunk) -> bool:
        if parent.id == child.id:
            return False
        if parent.start_line is None or parent.end_line is None:
            return False
        if child.start_line is None or child.end_line is None:
            return False
        return parent.start_line <= child.start_line and parent.end_line >= child.end_line

    def _unique_chunks(self, chunks: list[CodeChunk]) -> list[CodeChunk]:
        seen: set[str] = set()
        unique: list[CodeChunk] = []
        for chunk in chunks:
            if chunk.id in seen:
                continue
            seen.add(chunk.id)
            unique.append(chunk)
        return unique

    def _keyword_score(self, chunk: CodeChunk, terms: list[str]) -> float:
        file_path = chunk.file_path.lower()
        symbol_name = (chunk.symbol_name or "").lower()
        content = (chunk.content or "").lower()

        score = 0.0
        for term in terms:
            lowered = term.lower()
            if lowered in symbol_name:
                score += 5.0
            if lowered in file_path:
                score += 3.0
            if lowered in content:
                score += 1.0
        return score

    def _bounded_terms(self, terms: Iterable[str]) -> list[str]:
        cleaned: list[str] = []
        for term in terms:
            normalized = term.strip().lower()
            if len(normalized) < 2 or normalized in self.STOPWORDS:
                continue
            if normalized not in cleaned:
                cleaned.append(normalized)
            if len(cleaned) >= 24:
                break
        return cleaned
