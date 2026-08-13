from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import Base
from app.models.code_chunk import CodeChunk
from app.models.code_file import CodeFile
from app.models.repository import Repository
from app.services.index_service import IndexService


class DeterministicEmbeddingProvider:
    dimension = 3

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [[float(index + 1), 0.0, 0.0] for index, _text in enumerate(texts)]


class RecordingVectorStore:
    def __init__(self) -> None:
        self.collection_dimensions: list[int] = []
        self.upserted: list[object] = []
        self.deleted_point_ids: list[str] = []

    def ensure_collection(self, dimension: int) -> None:
        self.collection_dimensions.append(dimension)

    def upsert_chunks(self, points: list[object]) -> None:
        self.upserted.extend(points)

    def delete_points(self, point_ids: list[str]) -> None:
        self.deleted_point_ids.extend(point_ids)


def make_index_service(tmp_path: Path) -> tuple[Session, Repository, IndexService, RecordingVectorStore]:
    engine = create_engine(f"sqlite:///{tmp_path / 'index.db'}")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = Repository(
        id="repo-index",
        name="index-fixture",
        repo_url="https://example.com/index-fixture.git",
        status="pending",
    )
    db.add(repository)
    db.commit()

    service = IndexService(db)
    vector_store = RecordingVectorStore()
    service.embedding_provider = DeterministicEmbeddingProvider()  # type: ignore[assignment]
    service.vector_store = vector_store  # type: ignore[assignment]
    service._workspace_path = lambda identifier: tmp_path / "workspaces" / identifier  # type: ignore[method-assign]
    service._read_commit_hash = lambda _workspace: "fixture-commit"  # type: ignore[method-assign]
    service._refresh_memory = lambda _repo_id: None  # type: ignore[method-assign]
    return db, repository, service, vector_store


def add_indexed_file(db: Session, repository: Repository, *, path: str, chunk_id: str) -> None:
    code_file = CodeFile(
        id=f"file-{chunk_id}",
        repo_id=repository.id,
        file_path=path,
        language="python",
        content_hash=f"hash-{chunk_id}",
        line_count=1,
        size_bytes=1,
    )
    chunk = CodeChunk(
        id=chunk_id,
        repo_id=repository.id,
        file_id=code_file.id,
        file_path=path,
        language="python",
        symbol_name="legacy",
        symbol_type="function",
        start_line=1,
        end_line=1,
        content="def legacy(): pass",
        content_hash=f"hash-{chunk_id}",
        embedding_id=chunk_id,
    )
    db.add_all([code_file, chunk])
    db.commit()


def test_full_index_replaces_database_rows_only_after_new_vectors_are_written(tmp_path: Path) -> None:
    db, repository, service, vector_store = make_index_service(tmp_path)
    add_indexed_file(db, repository, path="legacy.py", chunk_id="legacy-point")

    def clone_fixture(_url: str, workspace: Path) -> None:
        workspace.mkdir(parents=True)
        (workspace / "src").mkdir()
        (workspace / "src" / "cart.py").write_text(
            "from decimal import Decimal\n\n"
            "def calculate_total(price: Decimal) -> Decimal:\n"
            "    return price\n",
            encoding="utf-8",
        )
        (workspace / "src" / "tax.py").write_text(
            "def tax_rate(country: str) -> float:\n"
            "    return 0.1\n",
            encoding="utf-8",
        )

    service._clone_repository = clone_fixture  # type: ignore[method-assign]
    service.index_repository(repository.id, full=True)

    db.refresh(repository)
    files = db.execute(select(CodeFile).where(CodeFile.repo_id == repository.id)).scalars().all()
    chunks = db.execute(select(CodeChunk).where(CodeChunk.repo_id == repository.id)).scalars().all()

    assert repository.status == "indexed"
    assert repository.last_commit_hash == "fixture-commit"
    assert {code_file.file_path for code_file in files} == {"src/cart.py", "src/tax.py"}
    assert repository.file_count == len(files) == 2
    assert repository.chunk_count == len(chunks)
    assert all(chunk.embedding_id == chunk.id for chunk in chunks)
    assert vector_store.collection_dimensions == [3]
    assert len(vector_store.upserted) == len(chunks)
    assert vector_store.deleted_point_ids == ["legacy-point"]


def test_incremental_index_updates_changed_and_deleted_paths_without_reembedding_unchanged_files(
    tmp_path: Path,
) -> None:
    db, repository, service, vector_store = make_index_service(tmp_path)
    workspace = tmp_path / "workspaces" / repository.id
    workspace.mkdir(parents=True)
    (workspace / "math.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    (workspace / "removed.py").write_text("def obsolete():\n    return None\n", encoding="utf-8")
    repository.local_path = str(workspace)
    repository.status = "indexed"
    db.add(repository)
    db.commit()
    add_indexed_file(db, repository, path="math.py", chunk_id="math-old")
    add_indexed_file(db, repository, path="removed.py", chunk_id="removed-old")

    def update_fixture(staging_workspace: Path) -> None:
        (staging_workspace / "math.py").write_text(
            "def add(a, b):\n    return a + b\n", encoding="utf-8"
        )
        (staging_workspace / "removed.py").unlink()
        (staging_workspace / "helpers.py").write_text(
            "def clamp(value):\n    return max(value, 0)\n", encoding="utf-8"
        )

    service._update_workspace = update_fixture  # type: ignore[method-assign]
    service.index_repository(repository.id)

    db.refresh(repository)
    chunks = db.execute(select(CodeChunk).where(CodeChunk.repo_id == repository.id)).scalars().all()

    assert repository.status == "indexed"
    assert {chunk.file_path for chunk in chunks} == {"math.py", "helpers.py"}
    assert {"math-old", "removed-old"}.issubset(vector_store.deleted_point_ids)
    assert len(vector_store.upserted) == len(chunks)
    assert all("return a + b" in chunk.content or chunk.file_path == "helpers.py" for chunk in chunks)


def test_failed_full_index_rolls_back_database_rows_and_removes_new_vector_points(tmp_path: Path) -> None:
    db, repository, service, vector_store = make_index_service(tmp_path)
    add_indexed_file(db, repository, path="stable.py", chunk_id="stable-point")

    def clone_fixture(_url: str, workspace: Path) -> None:
        workspace.mkdir(parents=True)
        (workspace / "replacement.py").write_text(
            "def replacement():\n    return True\n", encoding="utf-8"
        )

    service._clone_repository = clone_fixture  # type: ignore[method-assign]
    service._replace_workspace = lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("swap failed"))  # type: ignore[method-assign]
    service.index_repository(repository.id, full=True)

    db.refresh(repository)
    remaining = db.execute(select(CodeChunk).where(CodeChunk.repo_id == repository.id)).scalars().all()
    written_point_ids = [str(getattr(point, "id")) for point in vector_store.upserted]

    assert repository.status == "failed"
    assert [chunk.id for chunk in remaining] == ["stable-point"]
    assert set(written_point_ids).issubset(vector_store.deleted_point_ids)
    assert "stable-point" not in vector_store.deleted_point_ids
