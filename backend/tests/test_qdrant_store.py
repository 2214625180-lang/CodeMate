from types import SimpleNamespace

import pytest
from qdrant_client import QdrantClient, models

from app.vectorstore import qdrant_store
from app.vectorstore.qdrant_store import QdrantVectorStore, VectorDimensionMismatchError


class RecordingQdrantClient:
    def __init__(self) -> None:
        self.vector_sizes: dict[str, int] = {}
        self.created_collections: list[str] = []
        self.deleted_collections: list[str] = []

    def get_collections(self):
        return SimpleNamespace(
            collections=[SimpleNamespace(name=name) for name in self.vector_sizes]
        )

    def create_collection(self, *, collection_name: str, vectors_config) -> None:
        self.created_collections.append(collection_name)
        self.vector_sizes[collection_name] = vectors_config.size

    def get_collection(self, *, collection_name: str):
        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(vectors=SimpleNamespace(size=self.vector_sizes[collection_name]))
            )
        )

    def delete_collection(self, *, collection_name: str) -> None:
        self.deleted_collections.append(collection_name)


def test_embedding_dimensions_use_independent_collections(monkeypatch) -> None:
    client = QdrantClient(":memory:")
    monkeypatch.setattr(qdrant_store, "QdrantClient", lambda **_kwargs: client)
    store = QdrantVectorStore(collection_name="shared_chunks")

    store.ensure_collection(384)
    old_collection = store.collection_name
    store.upsert_chunks(
        [models.PointStruct(id=1, vector=[0.0] * 384, payload={"repo_id": "repo-a"})]
    )
    store.ensure_collection(1024)

    assert old_collection == "shared_chunks__embedding_384d"
    assert store.collection_name == "shared_chunks__embedding_1024d"
    collection_names = {collection.name for collection in client.get_collections().collections}
    assert {old_collection, store.collection_name} <= collection_names
    assert client.count(collection_name=old_collection, exact=True).count == 1


def test_dimension_conflict_never_deletes_a_collection(monkeypatch) -> None:
    client = RecordingQdrantClient()
    client.vector_sizes["shared_chunks__embedding_384d"] = 1024
    monkeypatch.setattr(qdrant_store, "QdrantClient", lambda **_kwargs: client)
    store = QdrantVectorStore(collection_name="shared_chunks")

    with pytest.raises(VectorDimensionMismatchError, match="uses vector size 1024"):
        store.ensure_collection(384)

    assert client.deleted_collections == []
