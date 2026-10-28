"""HR Copilot RAG Pipeline.

Allows HR professionals to ask natural language questions and receive
AI-powered answers grounded in the actual candidate database.

Example queries:
- "Find the best Python developer with AWS experience"
- "Show candidates with React and 5+ years experience"
- "Compare Candidate A and Candidate B"
- "Which candidates match this job description?"
- "Find candidates available in 30 days"
- "Who has AWS certification?"

Architecture:
1. Classify the query intent (find/compare/analyze/recommend)
2. Retrieve semantically similar candidate profiles from vector store
3. Build context from retrieved documents
4. Generate RAG response using Ollama LLM
5. Return structured answer with cited candidates
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from app.llm.client import LLMClient, get_llm_client
from app.llm.prompts import PromptLibrary
from app.llm.response_parser import ResponseParser
from app.rag.retriever import Retriever, get_retriever

logger = logging.getLogger(__name__)

# Query intent types
QUERY_INTENTS = {
    "FIND_CANDIDATES",
    "COMPARE_CANDIDATES",
    "ANALYZE_CANDIDATE",
    "JD_MATCH",
    "SKILL_SEARCH",
    "GENERAL",
}


@dataclass
class HRCopilotResponse:
    """Structured HR Copilot answer."""

    query: str
    answer: str
    intent: str = "GENERAL"
    cited_candidates: list[dict[str, Any]] = field(default_factory=list)
    retrieved_count: int = 0
    confidence: float = 0.0
    follow_up_suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "answer": self.answer,
            "intent": self.intent,
            "cited_candidates": self.cited_candidates,
            "retrieved_count": self.retrieved_count,
            "confidence": self.confidence,
            "follow_up_suggestions": self.follow_up_suggestions,
        }


class HRCopilotRAG:
    """RAG-powered HR Copilot for natural language candidate queries."""

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        retriever: Retriever | None = None,
    ) -> None:
        self._llm = llm_client or get_llm_client()
        self._retriever = retriever or get_retriever()

    async def query(
        self,
        question: str,
        top_k: int = 10,
        job_id: str | None = None,
        model: str | None = None,
    ) -> HRCopilotResponse:
        """Answer an HR natural language question using RAG.

        Args:
            question: Natural language HR query.
            top_k: Number of candidate documents to retrieve.
            job_id: Optional job ID to scope results to a specific role.
            model: Optional Ollama model override.
        """
        # Sanitize input
        safe_question = ResponseParser.sanitize_user_input(question, max_length=500)

        if ResponseParser.contains_injection(safe_question):
            return HRCopilotResponse(
                query=question,
                answer="I'm sorry, I cannot process that query. Please ask a recruitment-related question.",
                intent="REJECTED",
                confidence=1.0,
            )

        # Step 1: Detect intent
        intent = self._classify_intent(safe_question)

        # Step 2: Build search query from the HR question
        search_query = self._build_search_query(safe_question, intent)

        # Step 3: Retrieve relevant documents
        filter_meta = None
        if job_id:
            filter_meta = {"job_id": job_id}

        documents = []
        try:
            if intent == "SKILL_SEARCH":
                # Skill search: retrieve candidate profiles
                documents = await self._retriever.retrieve_candidates(
                    query=search_query,
                    top_k=top_k,
                    score_threshold=0.2,
                )
            else:
                documents = await self._retriever.retrieve(
                    query=search_query,
                    top_k=top_k,
                    filter_metadata=filter_meta,
                    score_threshold=0.15,
                )
        except Exception as exc:
            logger.error("Vector retrieval failed: %s", exc)
            documents = []

        # Step 4: Build context for LLM
        if documents:
            try:
                context = self._retriever.build_context(documents, max_chars=4000)
            except Exception as exc:
                logger.error("Context building failed: %s", exc)
                context = "No candidate profiles found in the database matching this query."
        else:
            context = "No candidate profiles found in the database matching this query."

        # Step 5: Generate RAG response
        response_text = await self._llm.complete(
            prompt=PromptLibrary.hr_copilot_user(safe_question, context),
            system=PromptLibrary.HR_COPILOT_SYSTEM,
            model=model,
            temperature=0.4,
            num_predict=1500,
        )

        if not response_text:
            response_text = "I was unable to generate a response. Please try again."

        # Build cited candidates list
        cited_candidates: list[dict[str, Any]] = []
        for doc in documents[:5]:
            if doc.candidate_name:
                cited_candidates.append({
                    "candidate_id": doc.candidate_id,
                    "candidate_name": doc.candidate_name,
                    "relevance_score": round(doc.score, 3),
                })

        # Generate follow-up suggestions
        follow_ups = self._generate_follow_ups(intent, safe_question)

        return HRCopilotResponse(
            query=question,
            answer=response_text,
            intent=intent,
            cited_candidates=cited_candidates,
            retrieved_count=len(documents),
            confidence=documents[0].score if documents else 0.0,
            follow_up_suggestions=follow_ups,
        )

    async def index_candidate(
        self,
        candidate_id: str,
        candidate_name: str,
        resume_text: str,
        skills: list[str],
        job_id: str | None = None,
        extra_metadata: dict | None = None,
    ) -> bool:
        """Index a candidate's resume in the vector store.

        Call this whenever a new resume is uploaded or parsed.
        """
        metadata: dict[str, Any] = {
            "document_type": "resume",
            "candidate_id": candidate_id,
            "candidate_name": candidate_name,
            "skills": ", ".join(skills[:30]),
        }
        if job_id:
            metadata["job_id"] = job_id
        if extra_metadata:
            metadata.update(extra_metadata)

        return await self._retriever.add_document(
            doc_id=candidate_id,
            text=resume_text,
            metadata=metadata,
        )

    async def index_job(
        self,
        job_id: str,
        job_title: str,
        jd_text: str,
        department: str,
    ) -> bool:
        """Index a job description for semantic search."""
        return await self._retriever.add_document(
            doc_id=f"job_{job_id}",
            text=jd_text,
            metadata={
                "document_type": "job_description",
                "job_id": job_id,
                "job_title": job_title,
                "department": department,
            },
        )

    async def ground_policy_query(
        self,
        *,
        company_id: uuid.UUID,
        question: str,
        documents: list[dict[str, Any]],
        top_k: int = 5,
    ) -> dict[str, Any]:
        """Ground an HR answer in tenant-supplied handbook/standing-order chunks.

        The service layer supplies documents only after applying its tenant and
        publication-state predicates.  This method deliberately performs local
        lexical retrieval instead of using the global candidate vector index:
        policy text from two tenants must never share an unscoped namespace.
        Returned citations contain the exact supporting excerpt, allowing the
        caller to render a deterministic response when no LLM is available.
        """
        import re

        safe_question = ResponseParser.sanitize_user_input(question, max_length=1000)
        if ResponseParser.contains_injection(safe_question):
            return {
                "answer": "The policy request could not be processed.",
                "citations": [], "confidence": 0.0,
                "grounding_status": "REJECTED",
            }

        stop_words = {
            "about", "after", "before", "could", "disciplinary", "employee",
            "from", "have", "incident", "policy", "should", "show", "that",
            "their", "there", "this", "under", "what", "when", "where", "with",
        }
        terms = {
            token for token in re.findall(r"[a-z0-9]+", safe_question.lower())
            if len(token) >= 3 and token not in stop_words
        }
        ranked: list[tuple[float, dict[str, Any]]] = []
        for document in documents:
            # Defence in depth: ignore accidentally supplied cross-tenant rows.
            if str(document.get("company_id")) != str(company_id):
                continue
            text = str(document.get("chunk_text") or document.get("raw_content") or "").strip()
            if not text:
                continue
            haystack = f"{document.get('title', '')} {document.get('category', '')} {text}".lower()
            matched = sum(1 for term in terms if term in haystack)
            # A small title/category boost helps short standing-order clauses.
            title_text = f"{document.get('title', '')} {document.get('category', '')}".lower()
            matched += sum(0.5 for term in terms if term in title_text)
            score = matched / max(1, len(terms))
            if matched or not terms:
                ranked.append((score, document))
        ranked.sort(key=lambda item: (-item[0], str(item[1].get("title") or ""), int(item[1].get("chunk_order") or 0)))
        selected = ranked[: max(1, min(top_k, 20))]
        citations = []
        for score, document in selected:
            excerpt = str(document.get("chunk_text") or document.get("raw_content") or "").strip()
            citations.append({
                "policy_document_id": str(document.get("policy_document_id") or document.get("id")),
                "document": document.get("title") or "Company policy",
                "category": document.get("category") or "GENERAL",
                "section": f"Section {int(document.get('chunk_order') or 0) + 1}",
                "version": document.get("version_number") or "1.0",
                "excerpt": excerpt[:1200],
                "relevance_score": round(float(score), 4),
            })
        if citations:
            answer = "Relevant tenant policy passages were retrieved. Use the cited clauses and verify their effective version before issuing any notice."
            status_value = "GROUNDED"
            confidence = max(float(item["relevance_score"]) for item in citations)
        else:
            answer = "Insufficient published handbook or standing-order evidence was found. Obtain and verify the applicable policy before proceeding."
            status_value = "INSUFFICIENT_EVIDENCE"
            confidence = 0.0
        return {
            "answer": answer,
            "citations": citations,
            "confidence": round(confidence, 4),
            "grounding_status": status_value,
            "company_id": str(company_id),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify_intent(question: str) -> str:
        """Simple keyword-based intent classification."""
        q = question.lower()

        if any(kw in q for kw in ["compare", "vs", "versus", "difference between"]):
            return "COMPARE_CANDIDATES"
        if any(kw in q for kw in ["match this jd", "match this job", "which candidates for"]):
            return "JD_MATCH"
        if any(kw in q for kw in ["best", "top", "recommend", "who is"]):
            return "FIND_CANDIDATES"
        if any(kw in q for kw in ["skill", "certified", "knows", "experience in", "years of"]):
            return "SKILL_SEARCH"
        if any(kw in q for kw in ["analyze", "tell me about", "profile of"]):
            return "ANALYZE_CANDIDATE"
        return "GENERAL"

    @staticmethod
    def _build_search_query(question: str, intent: str) -> str:
        """Enhance the raw question into a better embedding search query."""
        if intent == "SKILL_SEARCH":
            return f"candidate skills experience {question}"
        if intent == "FIND_CANDIDATES":
            return f"candidate profile resume {question}"
        if intent == "JD_MATCH":
            return f"candidate matches job requirements {question}"
        return question

    @staticmethod
    def _generate_follow_ups(intent: str, question: str) -> list[str]:
        """Generate contextual follow-up query suggestions."""
        base: list[str] = [
            "Show me their contact information",
            "What is their notice period?",
            "Which of these candidates are available immediately?",
        ]

        if intent == "FIND_CANDIDATES":
            return [
                "Compare the top 3 candidates",
                "Which of these have AWS certification?",
                "Schedule interviews for the best matches",
            ]
        if intent == "COMPARE_CANDIDATES":
            return [
                "Which candidate has stronger leadership experience?",
                "Who has a better cultural fit for a startup?",
            ]
        if intent == "SKILL_SEARCH":
            return [
                "Show candidates with 5+ years of this skill",
                "Which candidates have related certifications?",
            ]
        return base


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_hr_copilot: HRCopilotRAG | None = None


def get_hr_copilot() -> HRCopilotRAG:
    """Return the global HR Copilot RAG singleton."""
    global _hr_copilot
    if _hr_copilot is None:
        _hr_copilot = HRCopilotRAG()
    return _hr_copilot
