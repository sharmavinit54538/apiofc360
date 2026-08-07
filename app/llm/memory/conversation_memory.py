"""Conversation memory — session and persistent conversation history management.

Provides:
- In-memory session memory for active conversations
- Token-aware context window management
- Conversation persistence interface (DB-backed)
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MAX_SESSIONS = 500  # Max concurrent sessions in memory


@dataclass
class Message:
    """A single conversation message."""
    role: str                      # system | user | assistant
    content: str
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversationSession:
    """In-memory conversation session with message history."""
    session_id: str
    user_id: str | None = None
    messages: list[Message] = field(default_factory=list)
    system_prompt: str = ""
    total_tokens: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    summary: str = ""             # Compressed summary of older messages
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_message(self, role: str, content: str, token_count: int = 0) -> Message:
        """Add a message to the session."""
        msg = Message(role=role, content=content, token_count=token_count)
        self.messages.append(msg)
        self.total_tokens += token_count
        self.updated_at = time.time()
        return msg

    def get_messages_for_llm(self, max_tokens: int = 4096) -> list[dict[str, str]]:
        """Get messages formatted for LLM input, respecting token budget.

        Strategy:
        1. Always include system prompt
        2. Include conversation summary if available
        3. Include as many recent messages as fit within budget
        """
        result: list[dict[str, str]] = []
        used_tokens = 0

        # 1. System prompt
        if self.system_prompt:
            result.append({"role": "system", "content": self.system_prompt})
            used_tokens += len(self.system_prompt) // 4  # Approximate

        # 2. Summary of older messages
        if self.summary:
            summary_msg = f"[Previous conversation summary: {self.summary}]"
            result.append({"role": "system", "content": summary_msg})
            used_tokens += len(summary_msg) // 4

        # 3. Recent messages (newest first until budget exhausted)
        recent: list[dict[str, str]] = []
        for msg in reversed(self.messages):
            msg_tokens = msg.token_count or (len(msg.content) // 4)
            if used_tokens + msg_tokens > max_tokens:
                break
            recent.append({"role": msg.role, "content": msg.content})
            used_tokens += msg_tokens

        # Reverse to chronological order
        recent.reverse()
        result.extend(recent)

        return result

    def get_last_n_messages(self, n: int) -> list[dict[str, str]]:
        """Get the last N messages as dicts."""
        return [
            {"role": m.role, "content": m.content}
            for m in self.messages[-n:]
        ]

    @property
    def message_count(self) -> int:
        return len(self.messages)


class ConversationMemory:
    """Manages multiple conversation sessions with LRU eviction.

    This is the primary interface for conversation memory across the application.
    Sessions are stored in-memory with LRU eviction for scalability.
    """

    def __init__(self, max_sessions: int = _MAX_SESSIONS) -> None:
        self._sessions: OrderedDict[str, ConversationSession] = OrderedDict()
        self._max_sessions = max_sessions

    def get_or_create(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        system_prompt: str = "",
    ) -> ConversationSession:
        """Get an existing session or create a new one."""
        if session_id and session_id in self._sessions:
            session = self._sessions[session_id]
            # Move to end (most recently used)
            self._sessions.move_to_end(session_id)
            return session

        # Create new session
        new_id = session_id or str(uuid.uuid4())
        session = ConversationSession(
            session_id=new_id,
            user_id=user_id,
            system_prompt=system_prompt,
        )
        self._sessions[new_id] = session

        # Evict oldest if over capacity
        while len(self._sessions) > self._max_sessions:
            evicted_id, _ = self._sessions.popitem(last=False)
            logger.debug("Evicted conversation session %s (LRU)", evicted_id)

        return session

    def get(self, session_id: str) -> ConversationSession | None:
        """Get a session by ID without creating."""
        session = self._sessions.get(session_id)
        if session:
            self._sessions.move_to_end(session_id)
        return session

    def delete(self, session_id: str) -> bool:
        """Delete a session."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            return True
        return False

    def list_sessions(self, user_id: str | None = None) -> list[dict[str, Any]]:
        """List all sessions, optionally filtered by user_id."""
        sessions = []
        for sid, session in reversed(self._sessions.items()):
            if user_id and session.user_id != user_id:
                continue
            last_msg = session.messages[-1].content[:100] if session.messages else ""
            sessions.append({
                "session_id": sid,
                "user_id": session.user_id,
                "message_count": session.message_count,
                "total_tokens": session.total_tokens,
                "last_message": last_msg,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
            })
        return sessions

    def clear_all(self) -> None:
        """Clear all sessions."""
        self._sessions.clear()

    @property
    def session_count(self) -> int:
        return len(self._sessions)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_memory: ConversationMemory | None = None


def get_conversation_memory() -> ConversationMemory:
    """Return the global conversation memory singleton."""
    global _memory
    if _memory is None:
        _memory = ConversationMemory()
    return _memory
