"""Citation-aware answer generation with streaming support."""
import os
from typing import AsyncGenerator

from common.clients.llm import llm_chat, llm_chat_stream
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


def _build_chunk_context(chunks: list[dict]) -> str:
    """Build context string from chunks for the LLM."""
    lines = []
    for i, ch in enumerate(chunks):
        title = ch.get("paper_title", ch.get("paper_id", ""))
        page = ch.get("page_num", "?")
        content = ch.get("content_zh") or ch.get("content_en", "")
        chunk_type = ch.get("chunk_type", "text")
        tag = f"[{i+1}]"
        if chunk_type == "table_html":
            lines.append(f"{tag} (TABLE, {title}, P.{page})\n{content[:2000]}")
        elif chunk_type == "formula":
            lines.append(f"{tag} (FORMULA, {title}, P.{page})\n{content[:1000]}")
        elif chunk_type == "figure":
            lines.append(f"{tag} (FIGURE, {title}, P.{page})\n{content[:1000]}")
        else:
            lines.append(f"{tag} ({title}, P.{page})\n{content[:3000]}")
    return "\n\n---\n\n".join(lines)


async def generate_answer_with_citations(
    query: str, chunks: list[dict], history: list[dict] = None
) -> str:
    """Generate a non-streaming answer with citation markers."""
    template = _load("answer_with_citation")
    ctx = _build_chunk_context(chunks)

    hist = ""
    if history:
        hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-10:])

    prompt = (
        template.replace("{context}", ctx)
        .replace("{history}", hist or "(无历史)")
        .replace("{question}", query)
    )

    messages = [{"role": "user", "content": prompt}]
    return await llm_chat(messages, temperature=settings.LLM_TEMPERATURE)


async def generate_answer_stream(
    query: str, chunks: list[dict], history: list[dict] = None
) -> AsyncGenerator[str, None]:
    """Stream answer generation with citation markers."""
    template = _load("answer_with_citation")
    ctx = _build_chunk_context(chunks)

    hist = ""
    if history:
        hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-10:])

    prompt = (
        template.replace("{context}", ctx)
        .replace("{history}", hist or "(无历史)")
        .replace("{question}", query)
    )

    messages = [{"role": "user", "content": prompt}]
    async for token in llm_chat_stream(messages, temperature=settings.LLM_TEMPERATURE):
        yield token


async def generate_review_stream(
    query: str, chunks: list[dict]
) -> AsyncGenerator[str, None]:
    """Stream a literature review from multiple papers."""
    template = _load("review_generation")
    ctx = _build_chunk_context(chunks)
    prompt = template.replace("{context}", ctx).replace("{topic}", query)

    messages = [{"role": "user", "content": prompt}]
    async for token in llm_chat_stream(messages, temperature=0.5):
        yield token
