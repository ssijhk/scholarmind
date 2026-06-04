"""OpenAI-compatible LLM / Embedding / Reranker / VLM client.

All model calls go through this module; direct API calls elsewhere are forbidden.
"""
from typing import Optional, List, AsyncGenerator
import httpx
from common.config import settings
from common.logging import logger

TIMEOUT = httpx.Timeout(60.0, connect=10.0)
MAX_RETRIES = 3


async def _post_json(url: str, payload: dict, api_key: str) -> dict:
    """POST with retry and timeout."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    last_exc = None
    for attempt in range(MAX_RETRIES):
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            last_exc = e
            logger.warning(f"LLM call attempt {attempt + 1}/{MAX_RETRIES} failed: {e}")
    raise last_exc or RuntimeError("LLM call failed")


async def llm_chat(
    messages: List[dict],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    reasoning: bool = False,
) -> str:
    """Call LLM chat completion, return text content."""
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    payload = {
        "model": model or (settings.LLM_REASON_MODEL if reasoning else settings.LLM_MODEL),
        "messages": messages,
        "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE,
        "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
    }
    result = await _post_json(url, payload, settings.LLM_API_KEY)
    return result["choices"][0]["message"]["content"]


async def llm_chat_stream(
    messages: List[dict],
    model: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    reasoning: bool = False,
) -> AsyncGenerator[str, None]:
    """Call LLM chat completion with streaming."""
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    payload = {
        "model": model or (settings.LLM_REASON_MODEL if reasoning else settings.LLM_MODEL),
        "messages": messages,
        "temperature": temperature if temperature is not None else settings.LLM_TEMPERATURE,
        "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        "stream": True,
    }
    headers = {
        "Authorization": f"Bearer {settings.LLM_API_KEY}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        async with client.stream("POST", url, json=payload, headers=headers) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    import json
                    try:
                        chunk = json.loads(data)
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta:
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue


async def embed_texts(texts: List[str], model: Optional[str] = None) -> List[List[float]]:
    """Get embeddings for a list of texts."""
    url = f"{settings.EMBEDDING_BASE_URL}/embeddings"
    payload = {
        "model": model or settings.EMBEDDING_MODEL,
        "input": texts,
    }
    result = await _post_json(url, payload, settings.EMBEDDING_API_KEY)
    return [item["embedding"] for item in result["data"]]


async def embed_query(text: str, model: Optional[str] = None) -> List[float]:
    """Get embedding for a single query text."""
    embeddings = await embed_texts([text], model)
    return embeddings[0]


async def rerank(
    query: str,
    documents: List[str],
    top_n: Optional[int] = None,
    model: Optional[str] = None,
) -> List[dict]:
    """Rerank documents by relevance to query. Returns sorted [{index, score, document}, ...]."""
    url = settings.RERANK_BASE_URL
    payload = {
        "model": model or settings.RERANK_MODEL,
        "query": query,
        "documents": documents,
        "top_n": top_n or settings.RERANK_TOP_N,
    }
    result = await _post_json(url, payload, settings.RERANK_API_KEY)
    return result.get("results", [])


async def vlm_describe_image(image_url: str, prompt: str) -> str:
    """Call vision-language model to describe an image."""
    url = f"{settings.VLM_BASE_URL}/chat/completions"
    payload = {
        "model": settings.VLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 1024,
    }
    result = await _post_json(url, payload, settings.VLM_API_KEY)
    return result["choices"][0]["message"]["content"]
