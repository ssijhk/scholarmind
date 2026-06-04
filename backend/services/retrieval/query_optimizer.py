"""Query optimization: concurrent LLM calls for rewrite, translation, HyDE."""
import asyncio
import os

from common.clients.llm import llm_chat
from common.config import settings
from common.logging import logger

_PDIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "prompts"))


def _load(name: str) -> str:
    path = os.path.join(_PDIR, f"{name}.md")
    with open(path, "r", encoding="utf-8") as f:
        md = f.read()
    blocks = md.split("```")
    cs = [b.strip() for b in blocks[1:-1:2] if b.strip()]
    return cs[-1] if cs else md.strip()


async def _rewrite(query: str, history: list[dict] = None) -> str:
    hist = ""
    if history:
        hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-6:])
    prompt = _load("query_rewrite").replace("{history}", hist or "(none)").replace("{question}", query)
    return (await llm_chat([{"role": "user", "content": prompt}], temperature=0.2)).strip()


async def _translate(query: str) -> str:
    prompt = _load("query_translate").replace("{query}", query)
    return (await llm_chat([{"role": "user", "content": prompt}], temperature=0.2)).strip()


async def _hyde(query: str) -> str:
    prompt = _load("hyde").replace("{query}", query)
    return (await llm_chat([{"role": "user", "content": prompt}], temperature=0.7, max_tokens=512)).strip()


async def _expand(query: str) -> list[str]:
    prompt = _load("multi_query").replace("{query}", query)
    text = (await llm_chat([{"role": "user", "content": prompt}], temperature=0.7)).strip()
    import json
    try:
        s = text.find("["); e = text.rfind("]") + 1
        return json.loads(text[s:e]) if s != -1 and e > s else [query]
    except Exception:
        return [query]


async def optimize_query(query: str, history: list[dict] = None) -> dict:
    """Concurrently run query rewrite, translation, HyDE, and multi-query expansion.

    Returns dict with keys: rewritten, translated, hyde, multi_queries.
    Feature switches controlled by settings.ENABLE_*.
    """
    tasks = {}
    results = {}

    if settings.ENABLE_QUERY_REWRITE:
        tasks["rewritten"] = _rewrite(query, history)
    if settings.ENABLE_QUERY_TRANSLATION:
        tasks["translated"] = _translate(query)
    if settings.ENABLE_HYDE:
        tasks["hyde"] = _hyde(query)
    if settings.ENABLE_MULTI_QUERY:
        tasks["multi_queries"] = _expand(query)

    if not tasks:
        return {"rewritten": query, "translated": query, "hyde": "", "multi_queries": [query]}

    names = list(tasks.keys())
    coros = list(tasks.values())
    gathered = await asyncio.gather(*coros, return_exceptions=True)

    for name, val in zip(names, gathered):
        if isinstance(val, Exception):
            logger.warning(f"Query optimizer {name} failed: {val}")
            results[name] = query if name != "multi_queries" else [query]
        else:
            results[name] = val

    results.setdefault("rewritten", query)
    results.setdefault("translated", query)
    results.setdefault("hyde", "")
    results.setdefault("multi_queries", [query])

    return results
