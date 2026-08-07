"""Vector Store — multi-backend vector storage for semantic search.

Supported backends:
1. FAISS (default) — file-based, zero external infra, fast in-process
2. Qdrant — production distributed vector DB
3. ChromaDB — lightweight persistent vector DB

The factory pattern allows runtime backend switching via VECTOR_STORE_TYPE config.

Each backend exposes a uniform interface:
  - upsert(id, embedding, metadata)
  - search(query_embedding, top_k) -> [(id, score, metadata)]
  - delete(id)
  - count() -> int
"""

from __future__ import annotations

import json
import logging
import os
import pickle
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Base interface
# ---------------------------------------------------------------------------

class VectorStoreBase(ABC):
    """Abstract base for all vector store backends."""

    @abstractmethod
    def upsert(self, doc_id: str, embedding: list[float], metadata: dict[str, Any]) -> None:
        """Add or update a document embedding."""

    @abstractmethod
    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict | None = None,
    ) -> list[dict[str, Any]]:
        """Find the top-k most similar documents.

        Returns list of dicts: {"id": str, "score": float, "metadata": dict}
        """

    @abstractmethod
    def delete(self, doc_id: str) -> bool:
        """Remove a document by ID. Returns True if found and deleted."""

    @abstractmethod
    def count(self) -> int:
        """Return total number of stored vectors."""

    @abstractmethod
    def clear(self) -> None:
        """Remove all vectors from the store."""


# ---------------------------------------------------------------------------
# FAISS Backend (default — file-based, no external infra)
# ---------------------------------------------------------------------------

class FAISSVectorStore(VectorStoreBase):
    """FAISS flat L2 index with persistent JSON metadata store.

    Stores index as {path}/faiss.index and metadata as {path}/metadata.json
    Automatically persists on every write.
    """

    def __init__(self, persist_path: str, embedding_dim: int = 768) -> None:
        self._path = persist_path
        self._dim = embedding_dim
        self._index_path = os.path.join(persist_path, "faiss.index")
        self._meta_path = os.path.join(persist_path, "metadata.json")
        self._id_path = os.path.join(persist_path, "ids.json")

        os.makedirs(persist_path, exist_ok=True)

        self._index: Any = None
        self._id_to_pos: dict[str, int] = {}  # doc_id -> position in index
        self._pos_to_id: dict[int, str] = {}  # position -> doc_id
        self._metadata: dict[str, dict] = {}  # doc_id -> metadata
        self._deleted: set[str] = set()

        self._load()

    def upsert(self, doc_id: str, embedding: list[float], metadata: dict[str, Any]) -> None:
        self._init_index()
        vec = np.array([embedding], dtype=np.float32)

        if doc_id in self._id_to_pos:
            # FAISS doesn't support in-place updates; mark as logically updated
            pos = self._id_to_pos[doc_id]
            self._index.add(vec)
            new_pos = self._index.ntotal - 1
            self._id_to_pos[doc_id] = new_pos
            self._pos_to_id[new_pos] = doc_id
        else:
            self._index.add(vec)
            pos = self._index.ntotal - 1
            self._id_to_pos[doc_id] = pos
            self._pos_to_id[pos] = doc_id

        self._metadata[doc_id] = metadata
        self._deleted.discard(doc_id)
        self._persist()

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict | None = None,
    ) -> list[dict[str, Any]]:
        self._init_index()
        if self._index.ntotal == 0:
            return []

        q = np.array([query_embedding], dtype=np.float32)
        distances, indices = self._index.search(q, min(top_k * 3, self._index.ntotal))

        results: list[dict[str, Any]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx < 0:
                continue
            doc_id = self._pos_to_id.get(int(idx))
            if doc_id is None or doc_id in self._deleted:
                continue
            meta = self._metadata.get(doc_id, {})

            # Apply metadata filter if provided
            if filter_metadata:
                if not all(meta.get(k) == v for k, v in filter_metadata.items()):
                    continue

            # Convert L2 distance to similarity score (0.0-1.0)
            score = float(1.0 / (1.0 + dist))
            results.append({"id": doc_id, "score": score, "metadata": meta})

            if len(results) >= top_k:
                break

        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def delete(self, doc_id: str) -> bool:
        if doc_id not in self._id_to_pos:
            return False
        self._deleted.add(doc_id)
        del self._metadata[doc_id]
        self._persist()
        return True

    def count(self) -> int:
        return len(self._metadata)

    def clear(self) -> None:
        self._init_index(force=True)
        self._id_to_pos.clear()
        self._pos_to_id.clear()
        self._metadata.clear()
        self._deleted.clear()
        self._persist()

    # ------------------------------------------------------------------

    def _init_index(self, force: bool = False) -> None:
        if self._index is None or force:
            try:
                import faiss
                self._index = faiss.IndexFlatL2(self._dim)
            except ImportError:
                logger.warning("faiss-cpu not installed — using numpy fallback store")
                self._index = _NumpyFallbackIndex(self._dim)

    def _load(self) -> None:
        """Load persisted index and metadata."""
        self._init_index()
        try:
            if os.path.exists(self._index_path):
                try:
                    import faiss
                    self._index = faiss.read_index(self._index_path)
                except ImportError:
                    pass
            if os.path.exists(self._meta_path):
                with open(self._meta_path, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
            if os.path.exists(self._id_path):
                with open(self._id_path, "r", encoding="utf-8") as f:
                    id_data = json.load(f)
                    self._id_to_pos = id_data.get("id_to_pos", {})
                    self._pos_to_id = {int(k): v for k, v in id_data.get("pos_to_id", {}).items()}
        except Exception as exc:
            logger.error("Failed to load FAISS store: %s", exc)

    def _persist(self) -> None:
        """Persist index and metadata to disk."""
        try:
            try:
                import faiss
                faiss.write_index(self._index, self._index_path)
            except (ImportError, AttributeError):
                pass

            with open(self._meta_path, "w", encoding="utf-8") as f:
                json.dump(self._metadata, f)

            with open(self._id_path, "w", encoding="utf-8") as f:
                json.dump({
                    "id_to_pos": self._id_to_pos,
                    "pos_to_id": {str(k): v for k, v in self._pos_to_id.items()},
                }, f)
        except Exception as exc:
            logger.error("Failed to persist FAISS store: %s", exc)


# ---------------------------------------------------------------------------
# Numpy Fallback (when faiss-cpu is not installed)
# ---------------------------------------------------------------------------

class _NumpyFallbackIndex:
    """Simple numpy-based flat index as fallback when faiss is not installed."""

    def __init__(self, dim: int) -> None:
        self._dim = dim
        self._vectors: list[np.ndarray] = []
        self.ntotal: int = 0

    def add(self, vec: "np.ndarray") -> None:
        self._vectors.append(vec[0].copy())
        self.ntotal += 1

    def search(self, query: "np.ndarray", k: int):
        if not self._vectors:
            return np.array([[]], dtype=np.float32), np.array([[-1]], dtype=np.int64)
        q = query[0]
        dists = [np.sum((v - q) ** 2) for v in self._vectors]
        top_k_idx = np.argsort(dists)[:k]
        top_k_dist = np.array([dists[i] for i in top_k_idx], dtype=np.float32)
        return np.array([top_k_dist]), np.array([top_k_idx.tolist()])


# ---------------------------------------------------------------------------
# Qdrant Backend
# ---------------------------------------------------------------------------

class QdrantVectorStore(VectorStoreBase):
    """Qdrant vector DB backend for production deployments."""

    def __init__(self, collection_name: str = "resumes", dim: int = 768) -> None:
        self._collection = collection_name
        self._dim = dim
        self._client = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models

            self._client = QdrantClient(
                host=settings.QDRANT_HOST,
                port=settings.QDRANT_PORT,
            )
            # Create collection if not exists
            existing = [c.name for c in self._client.get_collections().collections]
            if self._collection not in existing:
                self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=models.VectorParams(
                        size=self._dim,
                        distance=models.Distance.COSINE,
                    ),
                )
        except ImportError:
            logger.warning("qdrant-client not installed")
        except Exception as exc:
            logger.error("Qdrant init failed: %s", exc)

    def upsert(self, doc_id: str, embedding: list[float], metadata: dict[str, Any]) -> None:
        if not self._client:
            return
        try:
            from qdrant_client.http import models
            self._client.upsert(
                collection_name=self._collection,
                points=[models.PointStruct(id=doc_id, vector=embedding, payload=metadata)],
            )
        except Exception as exc:
            logger.error("Qdrant upsert failed: %s", exc)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict | None = None,
    ) -> list[dict[str, Any]]:
        if not self._client:
            return []
        try:
            query_filter = None
            if filter_metadata:
                from qdrant_client.http import models
                conditions = [
                    models.FieldCondition(key=k, match=models.MatchValue(value=v))
                    for k, v in filter_metadata.items()
                ]
                query_filter = models.Filter(must=conditions)

            results = self._client.search(
                collection_name=self._collection,
                query_vector=query_embedding,
                limit=top_k,
                query_filter=query_filter,
            )
            return [
                {"id": str(r.id), "score": float(r.score), "metadata": r.payload or {}}
                for r in results
            ]
        except Exception as exc:
            logger.error("Qdrant search failed: %s", exc)
            return []

    def delete(self, doc_id: str) -> bool:
        if not self._client:
            return False
        try:
            from qdrant_client.http import models
            self._client.delete(
                collection_name=self._collection,
                points_selector=models.PointIdsList(points=[doc_id]),
            )
            return True
        except Exception as exc:
            logger.error("Qdrant delete failed: %s", exc)
            return False

    def count(self) -> int:
        if not self._client:
            return 0
        try:
            info = self._client.get_collection(self._collection)
            return info.points_count or 0
        except Exception:
            return 0

    def clear(self) -> None:
        if not self._client:
            return
        try:
            self._client.delete_collection(self._collection)
            self._init_client()
        except Exception as exc:
            logger.error("Qdrant clear failed: %s", exc)


# ---------------------------------------------------------------------------
# ChromaDB Backend
# ---------------------------------------------------------------------------

class ChromaVectorStore(VectorStoreBase):
    """ChromaDB backend — lightweight persistent vector DB."""

    def __init__(self, collection_name: str = "resumes") -> None:
        self._collection_name = collection_name
        self._client = None
        self._collection = None
        self._init_client()

    def _init_client(self) -> None:
        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        except ImportError:
            logger.warning("chromadb not installed")
        except Exception as exc:
            logger.error("ChromaDB init failed: %s", exc)

    def upsert(self, doc_id: str, embedding: list[float], metadata: dict[str, Any]) -> None:
        if not self._collection:
            return
        try:
            # Chroma requires string values in metadata
            safe_meta = {k: str(v) for k, v in metadata.items()}
            self._collection.upsert(ids=[doc_id], embeddings=[embedding], metadatas=[safe_meta])
        except Exception as exc:
            logger.error("ChromaDB upsert failed: %s", exc)

    def search(
        self,
        query_embedding: list[float],
        top_k: int = 10,
        filter_metadata: dict | None = None,
    ) -> list[dict[str, Any]]:
        if not self._collection:
            return []
        try:
            where = {k: str(v) for k, v in filter_metadata.items()} if filter_metadata else None
            results = self._collection.query(
                query_embeddings=[query_embedding],
                n_results=min(top_k, self._collection.count()),
                where=where,
            )
            output = []
            for i, doc_id in enumerate(results["ids"][0]):
                score = 1.0 - float(results["distances"][0][i])  # cosine distance -> similarity
                meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                output.append({"id": doc_id, "score": score, "metadata": meta})
            return output
        except Exception as exc:
            logger.error("ChromaDB search failed: %s", exc)
            return []

    def delete(self, doc_id: str) -> bool:
        if not self._collection:
            return False
        try:
            self._collection.delete(ids=[doc_id])
            return True
        except Exception as exc:
            logger.error("ChromaDB delete failed: %s", exc)
            return False

    def count(self) -> int:
        if not self._collection:
            return 0
        try:
            return self._collection.count()
        except Exception:
            return 0

    def clear(self) -> None:
        if not self._client:
            return
        try:
            self._client.delete_collection(self._collection_name)
            self._init_client()
        except Exception as exc:
            logger.error("ChromaDB clear failed: %s", exc)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

class VectorStoreFactory:
    """Create and cache the configured vector store backend."""

    _instance: VectorStoreBase | None = None

    @classmethod
    def get_store(cls) -> VectorStoreBase:
        """Return the singleton vector store based on VECTOR_STORE_TYPE config."""
        if cls._instance is None:
            cls._instance = cls._create()
        return cls._instance

    @classmethod
    def _create(cls) -> VectorStoreBase:
        store_type = settings.VECTOR_STORE_TYPE.lower()
        dim = settings.VECTOR_EMBEDDING_DIM

        if store_type == "qdrant":
            logger.info("Using Qdrant vector store")
            return QdrantVectorStore(dim=dim)

        elif store_type == "chroma":
            logger.info("Using ChromaDB vector store")
            return ChromaVectorStore()

        else:
            # Default: FAISS
            logger.info("Using FAISS vector store (path: %s)", settings.VECTOR_STORE_PATH)
            os.makedirs(settings.VECTOR_STORE_PATH, exist_ok=True)
            return FAISSVectorStore(persist_path=settings.VECTOR_STORE_PATH, embedding_dim=dim)
