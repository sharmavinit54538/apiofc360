"""AI Policy Explainer RAG Search and Chat service.

Splits policies manuals into chunks, generates vector embeddings, and performs
vector cosine similarity search queries to answer chatbot inputs.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.llm.client import get_llm_client
from app.llm.prompts import PromptLibrary

# Models
from app.models.policy import CompanyPolicyDocument, CompanyPolicyChunk

logger = logging.getLogger(__name__)


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute basic cosine similarity between two vector float lists."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot_product = sum(a * b for a, b in zip(v1, v2))
    norm_v1 = sum(a * a for a in v1) ** 0.5
    norm_v2 = sum(b * b for b in v2) ** 0.5
    if not norm_v1 or not norm_v2:
        return 0.0
    return dot_product / (norm_v1 * norm_v2)


class PolicyService:
    """Enterprise Policy RAG explainer service."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.llm = get_llm_client()

    async def upload_policy_document(
        self,
        company_id: uuid.UUID,
        title: str,
        category: str,
        raw_content: str,
    ) -> CompanyPolicyDocument:
        """Register policy manual and partition it into vector embedded chunks."""
        doc = CompanyPolicyDocument(
            id=uuid.uuid4(),
            company_id=company_id,
            title=title,
            category=category.upper(),
            raw_content=raw_content,
        )
        self.db.add(doc)
        await self.db.flush()

        # Chunk content into semantic 500-char parts
        chunk_size = 500
        words = raw_content.split()
        chunks = []
        current_chunk = []
        current_len = 0

        for w in words:
            current_chunk.append(w)
            current_len += len(w) + 1
            if current_len >= chunk_size:
                chunks.append(" ".join(current_chunk))
                current_chunk = []
                current_len = 0
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        # Generate embeddings and save chunks
        for idx, text_block in enumerate(chunks):
            # nomic-embed-text generates 768 float values
            try:
                vector = await self.llm.embed(text_block)
            except Exception as exc:
                logger.error("Embedding generation failed: %s", exc)
                from app.core.exceptions import AppException
                raise AppException(message=f"Failed to generate embedding for policy document chunk: {exc}", status_code=500) from exc

            chunk = CompanyPolicyChunk(
                id=uuid.uuid4(),
                policy_document_id=doc.id,
                chunk_text=text_block,
                vector=vector,
                chunk_order=idx,
            )
            self.db.add(chunk)

        await self.db.commit()
        await self.db.refresh(doc)
        logger.info("Policy document uploaded: %s with %s chunks", doc.title, len(chunks))
        return doc

    async def search_relevant_chunks(
        self,
        company_id: uuid.UUID,
        query_text: str,
        limit: int = 3,
    ) -> list[tuple[CompanyPolicyChunk, float]]:
        """Fetch search query embedding and query local chunks using cosine similarity."""
        try:
                query_vector = await self.llm.embed(query_text)
        except Exception as exc:
            logger.error("Query embedding failed: %s", exc)
            return []

        # Retrieve all policy chunks belonging to this company
        stmt = (
            select(CompanyPolicyChunk)
            .join(CompanyPolicyChunk.document)
            .where(CompanyPolicyDocument.company_id == company_id)
        )
        res = await self.db.execute(stmt)
        chunks = res.scalars().all()

        scored_chunks = []
        for c in chunks:
            sim = cosine_similarity(query_vector, c.vector)
            scored_chunks.append((c, sim))

        # Sort descending by similarity
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        return scored_chunks[:limit]

    async def answer_policy_query(
        self,
        company_id: uuid.UUID,
        user_query: str,
        language: str = "English",
        model: Optional[str] = None,
    ) -> dict[str, Any]:
        """Query policy manuals RAG database and formulate LLM context answer response."""
        matches = await self.search_relevant_chunks(company_id, user_query, limit=3)

        context_blocks = []
        sources = []
        for c, score in matches:
            if score > 0.1:  # check minimum threshold
                context_blocks.append(f"[Policy: {c.document.title}]\n{c.chunk_text}")
                sources.append({
                    "title": c.document.title,
                    "category": c.document.category,
                    "similarity": float(score)
                })

        context_str = "\n\n".join(context_blocks) or "No relevant policy documents found."

        try:
            prompt = PromptLibrary.ai_policy_user(context_str, user_query, language)
            answer = await self.llm.complete(
                prompt=prompt,
                system=PromptLibrary.AI_POLICY_EXPLAINER_CHAT,
                model=model,
                temperature=0.2
            )
        except Exception as exc:
            logger.error("LLM explainer prompt query failed: %s", exc)
            answer = "Sorry, I encountered an internal error compiling policy details."

        return {
            "answer": answer,
            "language": language,
            "sources": sources
        }
