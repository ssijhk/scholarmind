"""Corrective RAG scoring and Redis caching."""
import json
import os

from common.clients.llm import llm_chat
from common.db.redis_client import redis
from common.config import settings
from common.logging import logger

_PDIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "prompts"))


def _load_grade() -> str:
    path = os.path.join(_PDIR, "corrective_grade.md")
    with open(path, "r", encoding="utf-8") as f:
        md = f.read()
    blocks = md.split("```")
    cs = [b.strip() for b in blocks[1:-1:2] if b.strip()]
    return cs[-1] if cs else md.strip()


def _cache_key(query: str) -> str:
    import xxhash
    return f"rag:answer:{xxhash.xxh64(query).hexdigest()}"


async def grade_retrieval(query: str, chunks: list[dict]) -> dict:
    """Grade retrieval quality: sufficient / partial / insufficient."""
    if not chunks:
        return {"score": "insufficient", "action": "rewrite_query"}

    docs = "\n\n---\n\n".join(
        f"[{i}] {ch.get('content_zh') or ch.get('content_en', '')[:500]}"
        for i, ch in enumerate(chunks[:5])
    )
    prompt = _load_grade().replace("{query}", query).replace("{documents}", docs)

    try:
        text = await llm_chat([{"role": "user", "content": prompt}], temperature=0.0, max_tokens=256)
        s = text.find("{"); e = text.rfind("}") + 1
        return json.loads(text[s:e]) if s != -1 and e > s else {"score": "sufficient", "action": "generate"}
    except Exception:
        return {"score": "sufficient", "action": "generate"}


async def get_cached_answer(query: str) -> str | None:
    """Get cached answer from Redis."""
    try:
        val = await redis.get(_cache_key(query))
        return val.decode() if isinstance(val, bytes) else val
    except Exception:
        return None


async def cache_answer(query: str, answer: str, ttl: int = 600):
    """Cache answer in Redis."""
    try:
        await redis.setex(_cache_key(query), ttl, answer)
    except Exception as e:
        logger.warning(f"Cache write failed: {e}")
