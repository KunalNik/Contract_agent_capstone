"""Shared helper for LLM-based guard validators."""
import json
import os
import re
from typing import Any, Dict, Optional

from backend.shared.utils.logger import get_logger

logger = get_logger(__name__)

GUARD_MODEL = os.getenv("GUARD_MODEL", "gemini-2.5-flash")


def guard_fail_closed() -> bool:
    """When true, a guard that cannot reach its LLM blocks instead of allowing."""
    return os.getenv("GUARD_FAIL_CLOSED", "false").lower() in ("1", "true", "yes")


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        obj = re.search(r"\{.*\}", text, re.S)
        if obj:
            return json.loads(obj.group(0))
        raise


def ask_json(system_instruction: str, content: str, llm: Optional[Any] = None) -> Dict[str, Any]:
    """Ask the guard model a question and parse its JSON answer.

    Uses the raw chat model (``LLMManager.get_chat_model``), not the
    tool-calling chat agent, so ``invoke`` accepts a plain string.
    Raises on any failure; callers decide fail-open vs fail-closed.
    """
    if llm is None:
        from backend.llm_manager import get_shared_llm_manager
        llm = get_shared_llm_manager().get_chat_model(GUARD_MODEL)
    response = llm.invoke(f"System: {system_instruction}\n\n{content}")
    raw = response.content if hasattr(response, "content") else str(response)
    if isinstance(raw, list):  # some providers return content blocks
        raw = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in raw)
    return _extract_json(raw)
