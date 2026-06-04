"""Bilingual enhancement: generate Chinese summaries for English chunks.

Uses LLM via prompts/enrich_zh_summary.md. Each chunk gets content_zh, keywords_en,
summary_zh fields populated.
"""
import asyncio
import json
import os

from common.clients.llm import llm_chat
from common.config import settings
from common.logging import logger

_PROMPT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "prompts")
)

CONCURRENCY = 2  # reduced to avoid Docker DNS overload


async def enrich_chunks_zh(chunks: list[dict]) -> list[dict]:
    """Generate Chinese summaries and keywords for chunks concurrently."""

    prompt_template = _load_enrich_prompt()
    if not prompt_template:
        logger.warning("enrich_zh_summary prompt not found; skipping enrichment")
        for ch in chunks:
            ch["content_zh"] = ch.get("content_en", "")
        return chunks

    sem = asyncio.Semaphore(CONCURRENCY)

    async def enrich_one(chunk: dict):
        async with sem:
            await _enrich_single(chunk, prompt_template)

    tasks = [enrich_one(ch) for ch in chunks if ch.get("chunk_type") == "text" and len(ch.get("content_en", "")) > 100]

    # Chunks that don't need enrichment
    for ch in chunks:
        if ch.get("chunk_type") != "text" or len(ch.get("content_en", "")) <= 100:
            ch["content_zh"] = ch.get("content_en", "")

    await asyncio.gather(*tasks, return_exceptions=True)
    return chunks


def _load_enrich_prompt() -> str:
    """Load and extract the enrich_zh_summary prompt body."""
    path = os.path.join(_PROMPT_DIR, "enrich_zh_summary.md")
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    blocks = content.split("```")
    candidates = [b.strip() for b in blocks[1:-1:2] if b.strip()]
    return candidates[-1] if candidates else content.strip()


async def _enrich_single(chunk: dict, prompt_template: str):
    """Enrich one chunk with Chinese summary."""
    content = chunk.get("content_en", "")
    try:
        prompt = prompt_template.replace("{content}", content)
        messages = [{"role": "user", "content": prompt}]
        result = await llm_chat(messages, temperature=0.2, max_tokens=512)

        # Try to parse JSON; fallback to raw text
        try:
            start = result.find("{")
            end = result.rfind("}") + 1
            if start != -1 and end > start:
                parsed = json.loads(result[start:end])
                chunk["content_zh"] = parsed.get("summary_zh", result)
                chunk["keywords_en"] = ", ".join(parsed.get("keywords", []))
                chunk["summary_zh"] = parsed.get("summary_zh", result)
            else:
                chunk["content_zh"] = result
        except json.JSONDecodeError:
            chunk["content_zh"] = result

    except Exception:
        # Fallback: use original English as Chinese placeholder
        chunk["content_zh"] = content
