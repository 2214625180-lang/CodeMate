from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.database import Base
from app.indexing.chunkers import get_chunker
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository
from app.services.retrieval_service import RetrievalResult, RetrievalService


def test_ast_chunkers_preserve_python_typescript_and_vue_symbol_boundaries() -> None:
    python_content = (
        "import decimal\nfrom typing import Final\n\n"
        "__all__ = ['Cart', 'calculate_total']\n\n"
        "@staticmethod\ndef calculate_total(value: int) -> int:\n    return value\n\n"
        "class Cart:\n    def total(self) -> int:\n        return 1\n"
    )
    python = get_chunker("python", Path("cart.py")).parse(Path("cart.py"), python_content)

    assert python.imports == ["decimal", "typing.Final"]
    assert python.exports == ["Cart", "calculate_total"]
    assert {(chunk.symbol_name, chunk.symbol_type) for chunk in python.chunks} == {
        ("calculate_total", "decorated_function"),
        ("Cart", "class"),
        ("Cart.total", "method"),
    }
    assert all(chunk.content_hash for chunk in python.chunks)

    typescript = get_chunker("typescript", Path("checkout.tsx")).parse(
        Path("checkout.tsx"),
        "import { taxRate } from './tax';\n"
        "export const Checkout = (amount: number) => <span>{amount}</span>;\n",
    )
    assert typescript.imports == ["./tax"]
    assert typescript.exports == ["Checkout"]
    assert any(chunk.symbol_name == "Checkout" and chunk.symbol_type == "component" for chunk in typescript.chunks)

    vue = get_chunker("vue", Path("CartPanel.vue")).parse(
        Path("CartPanel.vue"),
        "<template>\n  <section>{{ total }}</section>\n</template>\n"
        "<script setup lang=\"ts\">\nexport const total = 1\n</script>\n",
    )
    assert any(chunk.symbol_name == "CartPanel.template" for chunk in vue.chunks)
    assert "total" in vue.exports


def test_invalid_python_source_is_not_indexed_as_a_partial_semantic_chunk() -> None:
    parsed = get_chunker("python", Path("broken.py")).parse(Path("broken.py"), "def broken(:\n")

    assert parsed.imports == []
    assert parsed.exports == []
    assert parsed.chunks == []


class FixedEmbeddingProvider:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        assert len(texts) == 1
        return [[0.1, 0.2, 0.3]]


class FixedVectorStore:
    def __init__(self, point_scores: dict[str, float]) -> None:
        self.point_scores = point_scores

    def search_repo_chunks(self, *, repo_id: str, query_vector: list[float], limit: int):
        assert query_vector == [0.1, 0.2, 0.3]
        return [
            SimpleNamespace(payload={"chunk_id": chunk_id}, score=score)
            for chunk_id, score in self.point_scores.items()
        ][:limit]


def test_hybrid_retrieval_reranks_exact_symbols_and_expands_same_file_context(monkeypatch, tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'retrieval.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-retrieval",
        name="retrieval",
        repo_url="https://example.com/retrieval.git",
        status="indexed",
    )
    target_file = CodeFile(
        id="file-cart",
        repo_id=repository.id,
        file_path="src/cart.py",
        language="python",
        content_hash="cart-hash",
        line_count=30,
        size_bytes=400,
    )
    other_file = CodeFile(
        id="file-user",
        repo_id=repository.id,
        file_path="src/user.py",
        language="python",
        content_hash="user-hash",
        line_count=10,
        size_bytes=120,
    )
    chunks = [
        CodeChunk(
            id="cart-helper",
            repo_id=repository.id,
            file_id=target_file.id,
            file_path=target_file.file_path,
            language="python",
            symbol_name="normalize_price",
            symbol_type="function",
            start_line=1,
            end_line=8,
            content="def normalize_price(value):\n    return value",
        ),
        CodeChunk(
            id="cart-target",
            repo_id=repository.id,
            file_id=target_file.id,
            file_path=target_file.file_path,
            language="python",
            symbol_name="calculate_total",
            symbol_type="function",
            start_line=10,
            end_line=20,
            content="def calculate_total():\n    raise TaxCalculationError('invalid tax')",
        ),
        CodeChunk(
            id="user-noise",
            repo_id=repository.id,
            file_id=other_file.id,
            file_path=other_file.file_path,
            language="python",
            symbol_name="calculate_profile",
            symbol_type="function",
            start_line=1,
            end_line=5,
            content="def calculate_profile():\n    return None",
        ),
    ]
    db.add_all([repository, target_file, other_file, *chunks])
    db.commit()

    monkeypatch.setattr(settings, "retrieval_strategy", "hybrid")
    monkeypatch.setattr(settings, "retrieval_min_vector_score", 0.1)
    monkeypatch.setattr(settings, "retrieval_rerank_enabled", True)
    monkeypatch.setattr(settings, "retrieval_context_expansion_enabled", True)
    monkeypatch.setattr(settings, "retrieval_context_window", 1)
    monkeypatch.setattr(settings, "retrieval_context_max_extra", 2)
    service = RetrievalService(db)
    service.embedding_provider = FixedEmbeddingProvider()  # type: ignore[assignment]
    service.vector_store = FixedVectorStore({"user-noise": 0.95, "cart-target": 0.80})  # type: ignore[assignment]

    results = service.retrieve(
        repo_id=repository.id,
        query="src/cart.py TaxCalculationError calculate_total",
        top_k=1,
    )

    assert [result.chunk.id for result in results] == ["cart-target", "cart-helper"]
    assert results[0].source == "hybrid+rerank"
    assert results[1].source == "hybrid+rerank+expanded"
    assert service.rewrite_query("订单 checkout.ts TimeoutError").file_paths == ["checkout.ts"]
    assert "order" in service.rewrite_query("订单 checkout.ts TimeoutError").keywords


def test_postgresql_fts_orders_rank_before_limiting_candidates() -> None:
    statement = RetrievalService._postgres_fts_statement(
        repo_ids=["repo-fts"],
        search_terms=["calculate_total", "TaxCalculationError"],
        limit=16,
    )
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )

    assert "plainto_tsquery" in sql
    assert "ts_rank_cd" in sql
    assert "ORDER BY keyword_score DESC, code_chunks.id ASC" in sql
    assert sql.index("ORDER BY") < sql.index("LIMIT 16")


def test_rrf_prioritizes_chunks_returned_by_keyword_and_vector_searches() -> None:
    def result(chunk_id: str, source: str) -> RetrievalResult:
        return RetrievalResult(
            chunk=SimpleNamespace(id=chunk_id),  # type: ignore[arg-type]
            score=1.0,
            source=source,
        )

    service = RetrievalService.__new__(RetrievalService)
    fused = service._reciprocal_rank_fusion(
        keyword_results=[result("keyword-only", "keyword"), result("shared", "keyword")],
        vector_results=[result("vector-only", "vector"), result("shared", "vector")],
    )

    assert [item.chunk.id for item in fused] == ["shared", "keyword-only", "vector-only"]
    assert fused[0].source == "hybrid"
