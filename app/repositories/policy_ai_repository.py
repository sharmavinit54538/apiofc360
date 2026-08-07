"""AI Policy Assistant Repository executing RAG vector searches and document queries."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.policy import CompanyPolicyChunk, CompanyPolicyDocument

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


class PolicyAIRepository:
    """Repository querying database models for AI Policy Assistant endpoints."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_company_documents(
        self, company_id: Optional[uuid.UUID] = None, category: Optional[str] = None
    ) -> List[CompanyPolicyDocument]:
        """Fetch indexed policy documents for a company."""
        try:
            stmt = select(CompanyPolicyDocument)
            if company_id:
                stmt = stmt.where(CompanyPolicyDocument.company_id == company_id)
            if category:
                stmt = stmt.where(CompanyPolicyDocument.category.ilike(category))

            res = await self.session.execute(stmt)
            return list(res.scalars().all())
        except Exception as exc:
            logger.error("Error fetching policy documents: %s", exc)
            return []

    async def get_document_by_id(
        self, document_id: uuid.UUID
    ) -> Optional[CompanyPolicyDocument]:
        """Fetch single policy document by ID."""
        try:
            stmt = select(CompanyPolicyDocument).where(CompanyPolicyDocument.id == document_id)
            res = await self.session.execute(stmt)
            return res.scalar_one_or_none()
        except Exception as exc:
            logger.error("Error fetching document by ID '%s': %s", document_id, exc)
            return None

    async def search_vector_chunks(
        self,
        company_id: Optional[uuid.UUID] = None,
        query_vector: Optional[List[float]] = None,
        category: Optional[str] = None,
        top_k: int = 5,
    ) -> List[Tuple[CompanyPolicyChunk, float]]:
        """Search policy chunks using vector cosine similarity."""
        try:
            stmt = select(CompanyPolicyChunk).join(CompanyPolicyChunk.document)
            if company_id:
                stmt = stmt.where(CompanyPolicyDocument.company_id == company_id)
            if category:
                stmt = stmt.where(CompanyPolicyDocument.category.ilike(category))

            res = await self.session.execute(stmt)
            chunks = list(res.scalars().all())

            if not query_vector or not chunks:
                return []

            scored = []
            for c in chunks:
                sim = cosine_similarity(query_vector, c.vector)
                scored.append((c, sim))

            scored.sort(key=lambda x: x[1], reverse=True)
            return scored[:top_k]
        except Exception as exc:
            logger.error("Error searching vector chunks: %s", exc)
            return []
