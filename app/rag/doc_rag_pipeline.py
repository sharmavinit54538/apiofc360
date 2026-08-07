"""Retrieval-Augmented Generation (RAG) pipeline for document QA.

Handles text chunking, embedding, vector store indexing, similarity retrieval,
context building, and natural language QA completion.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from app.core.config import settings
from app.llm.client import get_llm_client
from app.llm.response_parser import ResponseParser
from app.rag.embeddings import get_embedding_service
from app.rag.vector_store import VectorStoreFactory

logger = logging.getLogger(__name__)


class DocChunk:
    def __init__(self, doc_id: str, index: int, text: str, metadata: dict) -> None:
        self.chunk_id = f"{doc_id}_chunk_{index}"
        self.doc_id = doc_id
        self.index = index
        self.text = text
        self.metadata = {
            **metadata,
            "document_id": doc_id,
            "chunk_index": index,
            "content": text,  # Crucial: vector search retrieves metadata, we need content here
        }


class DocumentRAGPipeline:
    """Orchestrates embedding, retrieval, and QA over multiple document chunks."""

    def __init__(self) -> None:
        self.embedder = get_embedding_service()
        self.store = VectorStoreFactory.get_store()
        self.llm = get_llm_client()

    # ------------------------------------------------------------------
    # Indexing Operations
    # ------------------------------------------------------------------

    async def index_document_text(
        self,
        doc_id: str,
        text: str,
        metadata: dict,
        chunk_size: int = 600,
        overlap: int = 150,
    ) -> bool:
        """Split text into overlapping chunks, embed, and index in vector store."""
        if not text or not text.strip():
            logger.warning("Empty text provided for indexing (doc_id=%s)", doc_id)
            return False

        try:
            chunks = self._chunk_text(text, chunk_size, overlap)
            logger.info("Splitting document %s into %d chunks", doc_id, len(chunks))

            doc_chunks = [
                DocChunk(doc_id, idx, chunk_text, metadata)
                for idx, chunk_text in enumerate(chunks)
            ]

            # Generate embeddings and upload to Vector DB
            for chunk in doc_chunks:
                embedding = await self.embedder.embed(chunk.text)
                if embedding:
                    self.store.upsert(chunk.chunk_id, embedding, chunk.metadata)

            return True
        except Exception as exc:
            logger.error("Failed to index document %s in RAG vector DB: %s", doc_id, exc)
            return False

    def remove_document_from_index(self, doc_id: str) -> None:
        """Deletes all vector chunks registered under this document ID."""
        # Note: Depending on backend, we scan for IDs matching the prefix {doc_id}_chunk_
        # FAISS implementation supports checking metadata. Since FAISS is in-memory
        # we can delete items from our metadata dictionary.
        # Let's call delete on the store if it supports it.
        # Simple iterative cleanup:
        for idx in range(100):  # assuming typical document has < 100 chunks
            chunk_id = f"{doc_id}_chunk_{idx}"
            self.store.delete(chunk_id)

    # ------------------------------------------------------------------
    # Semantic Search
    # ------------------------------------------------------------------

    async def semantic_search(
        self,
        query: str,
        top_k: int = 10,
        filter_metadata: Optional[dict] = None,
    ) -> list[dict[str, Any]]:
        """Retrieve most similar chunks matching query."""
        query_emb = await self.embedder.embed(query)
        if not query_emb:
            return []

        results = self.store.search(
            query_embedding=query_emb,
            top_k=top_k,
            filter_metadata=filter_metadata
        )
        return results

    # ------------------------------------------------------------------
    # RAG Question Answering
    # ------------------------------------------------------------------

    async def answer_question(
        self,
        question: str,
        document_ids: list[str],
        company_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Perform RAG Q&A scoped to specified document IDs."""
        # 1. Retrieve candidate chunks
        query_emb = await self.embedder.embed(question)
        if not query_emb:
            return {"answer": "Unable to generate embedding for the question.", "sources": []}

        filter_meta = {}
        if company_id:
            filter_meta["company_id"] = company_id

        raw_results = self.store.search(
            query_embedding=query_emb,
            top_k=8,
            filter_metadata=filter_meta if filter_meta else None
        )

        # Filter by document list (scoped search)
        matched_results = []
        for r in raw_results:
            doc_id = r["metadata"].get("document_id")
            if doc_id in document_ids:
                matched_results.append(r)

        if not matched_results:
            return {
                "answer": "No relevant text matching your question was found in the specified documents.",
                "sources": []
            }

        # 2. Compile context
        context_chunks = []
        sources = []
        for r in matched_results:
            meta = r["metadata"]
            content = meta.get("content", "")
            if content:
                context_chunks.append(f"[Source: {meta.get('file_name', 'Doc')} (Page/Chunk: {meta.get('chunk_index')})]\n{content}")
                sources.append({
                    "document_id": meta.get("document_id"),
                    "file_name": meta.get("file_name"),
                    "chunk_index": meta.get("chunk_index"),
                    "score": round(r["score"], 3)
                })

        context = "\n\n---\n\n".join(context_chunks)

        # 3. LLM Query completion
        system = """You are an expert Document Q&A AI assistant.
Your task is to answer user questions using ONLY the provided document context.
Be factual and precise. Cites the sources or filename if appropriate.
If the answer cannot be determined from the context, state that clearly."""

        prompt = f"""Use the following source contexts to answer the user question.

<context>
{context[:4000]}
</context>

Question: {question}

Helpful Answer:"""

        answer_text = await self.llm.complete(
            prompt=prompt,
            system=system,
            model=model,
            temperature=0.3
        )

        return {
            "answer": answer_text or "No response from LLM.",
            "sources": sources
        }

    # ------------------------------------------------------------------
    # Chunker logic
    # ------------------------------------------------------------------

    @staticmethod
    def _chunk_text(text: str, size: int, overlap: int) -> list[str]:
        """Perform recursive sliding window character chunking."""
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = min(start + size, text_len)
            chunk = text[start:end]
            if chunk:
                chunks.append(chunk)
            if end >= text_len:
                break
            start += size - overlap
        return chunks


# Singleton Accessor
_rag_pipeline: DocumentRAGPipeline | None = None


def get_rag_pipeline() -> DocumentRAGPipeline:
    global _rag_pipeline
    if _rag_pipeline is None:
        _rag_pipeline = DocumentRAGPipeline()
    return _rag_pipeline
