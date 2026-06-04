"""Intent router: classify queries as chitchat / knowledge / complex / followup."""
import json
import os

from common.clients.llm import llm_chat
from common.config import settings
from common.logging import logger

_PDIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "prompts"))


async def route_intent(query: str, history: list[dict] = None) -> dict:
    """Classify user intent. Falls back to 'knowledge' on failure.

    Returns {"intent": str, "need_retrieval": bool, "reason": str}.
    """
    if not settings.ENABLE_INTENT_ROUTER:
        return {"intent": "knowledge", "need_retrieval": True, "reason": "router disabled"}

    try:
        path = os.path.join(_PDIR, "intent_router.md")
        with open(path, "r", encoding="utf-8") as f:
            md = f.read()
        blocks = md.split("```")
        cs = [b.strip() for b in blocks[1:-1:2] if b.strip()]
        template = cs[-1] if cs else md.strip()

        hist = ""
        if history:
            hist = "\n".join(f"[{m['role']}]: {m['content']}" for m in history[-6:])

        prompt = template.replace("{history}", hist or "(no history)").replace("{question}", query)
        raw = await llm_chat([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=256)
        raw = raw.strip()

        s = raw.find("{"); e = raw.rfind("}") + 1
        parsed = json.loads(raw[s:e]) if s != -1 and e > s else {}

        intent = parsed.get("intent", "knowledge")
        if intent not in {"chitchat", "knowledge", "complex", "followup"}:
            intent = "knowledge"

        need_retrieval = intent in ("knowledge", "complex", "followup")

        return {"intent": intent, "need_retrieval": need_retrieval, "reason": parsed.get("reason", "")}

    except Exception as e:
        logger.warning(f"Intent routing failed: {e}; defaulting to knowledge")
        return {"intent": "knowledge", "need_retrieval": True, "reason": "fallback"}
