from qdrant_client import QdrantClient, models

from app.core.config import settings


class VectorDimensionMismatchError(RuntimeError):
    pass


class QdrantVectorStore:
    def __init__(self, collection_name: str | None = None):
        self.collection_name = collection_name or settings.qdrant_collection
        self.client = QdrantClient(url=settings.qdrant_url)

    def ensure_collection(self, vector_size: int, *, recreate_on_mismatch: bool = False) -> None:
        if vector_size <= 0:
            raise ValueError("Qdrant vector size must be greater than zero.")

        collections = self.client.get_collections().collections
        exists = any(collection.name == self.collection_name for collection in collections)
        if not exists:
            self._create_collection(vector_size)
            return

        current_size = self._current_vector_size()
        if current_size == vector_size:
            return

        message = (
            f"Qdrant collection {self.collection_name!r} uses vector size "
            f"{current_size or 'unknown'}, but the configured embedding size is {vector_size}."
        )
        if not recreate_on_mismatch:
            raise VectorDimensionMismatchError(message)

        self.client.delete_collection(collection_name=self.collection_name)
        self._create_collection(vector_size)

    def _create_collection(self, vector_size: int) -> None:
        self.client.create_collection(
            collection_name=self.collection_name,
            vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
        )

    def _current_vector_size(self) -> int | None:
        collection = self.client.get_collection(collection_name=self.collection_name)
        vectors = collection.config.params.vectors
        return _vector_size(vectors)

    def upsert_chunks(self, points: list[models.PointStruct]) -> None:
        if not points:
            return
        self.client.upsert(collection_name=self.collection_name, points=points)

    def search_repo_chunks(
        self,
        *,
        repo_id: str,
        query_vector: list[float],
        limit: int,
    ):
        self.ensure_collection(len(query_vector) or settings.embedding_dimension)
        return self.client.search(
            collection_name=self.collection_name,
            query_vector=query_vector,
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="repo_id",
                        match=models.MatchValue(value=repo_id),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )

    def delete_repo_points(self, repo_id: str) -> None:
        self.ensure_collection(settings.embedding_dimension)
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="repo_id",
                            match=models.MatchValue(value=repo_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def delete_points(self, point_ids: list[str]) -> None:
        if not point_ids:
            return
        self.ensure_collection(settings.embedding_dimension)
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=point_ids),
            wait=True,
        )


def make_chunk_point(
    *,
    point_id: str,
    vector: list[float],
    repo_id: str,
    chunk_id: str,
    file_path: str,
    language: str,
    symbol_name: str | None,
    symbol_type: str | None,
    start_line: int | None,
    end_line: int | None,
    content_hash: str | None,
) -> models.PointStruct:
    return models.PointStruct(
        id=point_id,
        vector=vector,
        payload={
            "repo_id": repo_id,
            "chunk_id": chunk_id,
            "file_path": file_path,
            "language": language,
            "symbol_name": symbol_name,
            "symbol_type": symbol_type,
            "start_line": start_line,
            "end_line": end_line,
            "content_hash": content_hash,
        },
    )


def _vector_size(vectors_config) -> int | None:
    size = getattr(vectors_config, "size", None)
    if isinstance(size, int):
        return size

    if isinstance(vectors_config, dict):
        vector_params = list(vectors_config.values())
        if len(vector_params) != 1:
            return None
        return _vector_size(vector_params[0])

    return None
