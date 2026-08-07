"""Semantic Retriever — finds the most relevant documents for a query.

Combines:
- Vector similarity search (embedding-based)
- Metadata pre-filtering (job_id, candidate_id, document_type)
- Re-ranking by relevance score
- Context assembly for RAG prompts
"""

from __future__ import annotations

import logging
from typing import Any

from app.rag.embeddings import EmbeddingService, get_embedding_service
from app.rag.vector_store import VectorStoreBase, VectorStoreFactory

logger = logging.getLogger(__name__)


class RetrievedDocument:
    """A retrieved document chunk with metadata and relevance score."""

    def __init__(self, doc_id: str, score: float, metadata: dict[str, Any]) -> None:
        self.doc_id = doc_id
        self.score = score
        self.metadata = metadata
        self.content: str = metadata.get("content", "")
        self.document_type: str = metadata.get("document_type", "unknown")
        self.candidate_name: str = metadata.get("candidate_name", "")
        self.job_id: str = metadata.get("job_id", "")
        self.candidate_id: str = metadata.get("candidate_id", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "score": round(self.score, 4),
            "content": self.content[:500],
            "document_type": self.document_type,
            "candidate_name": self.candidate_name,
            "job_id": self.job_id,
            "candidate_id": self.candidate_id,
        }


class Retriever:
    """Semantic retriever combining vector search with metadata filtering."""

    def __init__(
        self,
        embedding_service: EmbeddingService | None = None,
        vector_store: VectorStoreBase | None = None,
        default_top_k: int = 10,
    ) -> None:
        self._embedder = embedding_service or get_embedding_service()
        self._store = vector_store or VectorStoreFactory.get_store()
        self._default_top_k = default_top_k

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        filter_metadata: dict | None = None,
        score_threshold: float = 0.0,
    ) -> list[RetrievedDocument]:
        """Retrieve semantically similar documents for a query.

        Args:
            query: Natural language query string.
            top_k: Number of results to return.
            filter_metadata: Key-value pairs to filter by (e.g., {"job_id": "xxx"}).
            score_threshold: Minimum similarity score to include.
        """
        top_k = top_k or self._default_top_k

        # Generate query embedding
        query_embedding = await self._embedder.embed(query)
        if not query_embedding:
            logger.warning("Failed to generate query embedding")
            return []

        # Vector search
        raw_results = self._store.search(
            query_embedding=query_embedding,
            top_k=top_k,
            filter_metadata=filter_metadata,
        )

        # Build result objects, apply score threshold
        results: list[RetrievedDocument] = []
        for r in raw_results:
            if r["score"] >= score_threshold:
                results.append(RetrievedDocument(
                    doc_id=r["id"],
                    score=r["score"],
                    metadata=r["metadata"],
                ))

        logger.debug("Retrieved %d documents for query (len=%d)", len(results), len(query))
        return results

    async def retrieve_for_job(
        self,
        query: str,
        job_id: str,
        top_k: int = 10,
    ) -> list[RetrievedDocument]:
        """Retrieve candidate documents filtered by job ID."""
        return await self.retrieve(
            query=query,
            top_k=top_k,
            filter_metadata={"job_id": job_id},
        )

    async def retrieve_candidates(
        self,
        query: str,
        top_k: int = 10,
        score_threshold: float = 0.3,
    ) -> list[RetrievedDocument]:
        """Retrieve candidate profiles by semantic similarity."""
        return await self.retrieve(
            query=query,
            top_k=top_k,
            filter_metadata={"document_type": "resume"},
            score_threshold=score_threshold,
        )

    async def add_document(
        self,
        doc_id: str,
        text: str,
        metadata: dict[str, Any],
    ) -> bool:
        """Embed and index a document.

        Args:
            doc_id: Unique document identifier (e.g., candidate UUID).
            text: Document text to embed.
            metadata: Metadata to store alongside embedding.
        """
        try:
            embedding = await self._embedder.embed(text)
            if not embedding:
                logger.error("Failed to embed document %s", doc_id)
                return False

            # Store content in metadata for retrieval
            metadata_with_content = {
                **metadata,
                "content": text[:2000],  # Store first 2000 chars as context
            }

            self._store.upsert(doc_id, embedding, metadata_with_content)
            logger.debug("Indexed document %s (%d chars)", doc_id, len(text))
            return True

        except Exception as exc:
            logger.error("Failed to index document %s: %s", doc_id, exc)
            return False

    async def add_documents_batch(
        self,
        documents: list[dict[str, Any]],
        max_concurrent: int = 10,
    ) -> dict[str, bool]:
        """Batch index multiple documents.

        Args:
            documents: List of dicts with 'id', 'text', 'metadata'.
        Returns:
            Dict of {doc_id: success_bool}
        """
        import asyncio
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _add(doc: dict) -> tuple[str, bool]:
            async with semaphore:
                success = await self.add_document(
                    doc_id=doc["id"],
                    text=doc["text"],
                    metadata=doc.get("metadata", {}),
                )
                return doc["id"], success

        results = await asyncio.gather(*[_add(d) for d in documents])
        return dict(results)

    def remove_document(self, doc_id: str) -> bool:
        """Remove a document from the vector index."""
        return self._store.delete(doc_id)

    def count_indexed(self) -> int:
        """Return total number of indexed documents."""
        return self._store.count()

    @staticmethod
    def build_context(documents: list[RetrievedDocument], max_chars: int = 4000) -> str:
        """Build a RAG context string from retrieved documents."""
        chunks: list[str] = []
        total = 0

        for doc in documents:
            header = (
                f"[Candidate: {doc.candidate_name}]"
                if doc.candidate_name
                else f"[Document: {doc.doc_id[:8]}]"
            )
            chunk = f"{header}\n{doc.content}"
            chunk_len = len(chunk)
            if total + chunk_len > max_chars:
                # Truncate last chunk to fit
                remaining = max_chars - total
                if remaining > 100:
                    chunks.append(chunk[:remaining])
                break
            chunks.append(chunk)
            total += chunk_len

        return "\n\n---\n\n".join(chunks)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_retriever: Retriever | None = None


def get_retriever() -> Retriever:
    """Return the global retriever singleton."""
    global _retriever
    if _retriever is None:
        _retriever = Retriever()
    return _retriever
