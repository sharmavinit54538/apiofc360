"""Read-only LLM advice; model text never directly dispatches HR actions."""
import asyncio
import uuid
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from app.llm.client import get_llm_client


class Advice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    response: str = Field(min_length=1, max_length=12000)


async def chat(message, context=None, conversation_id=None):
    # No database access or action tools are exposed to the model. User-supplied
    # context is untrusted conversation text, never an authorization source.
    messages = [
        {"role": "system", "content": "You are OFC360's HR assistant. Provide advice only. You have no employee database or execution tools. Never claim that an action was performed, or invent employee facts, payroll amounts, or confidence scores. Explain that HR/financial changes require an authorized user's explicit approval in the relevant workflow. Return JSON with exactly one string field: response."},
        {"role": "user", "content": message},
    ]
    try:
        raw = await asyncio.wait_for(get_llm_client().chat(messages, json_mode=True, temperature=0.1), timeout=30)
        advice = Advice.model_validate_json(raw)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise HTTPException(503, "AI provider is unavailable or returned an invalid response.") from exc
    return {"conversation_id": str(conversation_id or uuid.uuid4()), "response": advice.response,
            "proposed_actions": [], "requires_approval": False}
