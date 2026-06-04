"""Hybrid search: dense+sparse with RRF fusion and rerank."""
import math
from common.clients.llm import embed_query, rerank
from common.db.milvus_client import ensure_collection
from common.config import settings
from common.logging import logger


def build_milvus_expr(user_id: str, scope: dict) -> str:
    """Build scalar filter expression for Milvus search.

    scope may contain: paper_ids (list), folder_id (str).
    """
    parts = [f'user_id == "{user_id}"']

    if scope.get("paper_ids"):
        ids = ", ".join(f'"{p}"' for p in scope["paper_ids"])
        parts.append(f"paper_id in [{ids}]")

    if scope.get("folder_id"):
        parts.append(f'folder_id == "{scope["folder_id"]}"')

    return " and ".join(parts)


async def hybrid_search(
    query_text: str,
    query_vector: list[float],
    user_id: str,
    scope: dict,
    top_k: int = None,
) -> list[dict]:
    """Dense vector search + keyword search, fused with RRF."""
    top_k = top_k or settings.RETRIEVAL_TOP_K
    col = ensure_collection()
    expr = build_milvus_expr(user_id, scope)

    search_params = {"metric_type": settings.MILVUS_METRIC, "params": {"ef": 100}}

    # Dense search
    dense_results = col.search(
        data=[query_vector],
        anns_field="dense_vec",
        param=search_params,
        limit=top_k * 2,
        expr=expr,
        output_fields=["id", "content_en", "content_zh", "paper_id", "page_num", "block_id", "image_key", "chunk_type"],
    )

    # Sparse (keyword) search: simple content_en LIKE matching
    sparse_hits = _keyword_search(col, query_text, expr, top_k)

    # RRF fusion (k=60)
    fused = _rrf_fuse(dense_results[0] if dense_results else [], sparse_hits, k=60)
    fused.sort(key=lambda x: x["score"], reverse=True)
    return fused[:top_k]


def _keyword_search(col, query_text: str, expr: str, top_k: int) -> list:
    """Simple keyword search using Milvus query iterator."""
    words = [w for w in query_text.lower().split() if len(w) > 2]
    if not words:
        return []
    results = []
    expr_with_kw = expr
    for word in words[:3]:
        expr_with_kw += f' and content_en like "%{word}%"'
    try:
        it = col.query_iterator(
            expr=expr_with_kw,
            output_fields=["id", "content_en", "content_zh", "paper_id", "page_num", "block_id", "image_key", "chunk_type"],
            limit=top_k,
        )
        while True:
            batch = it.next()
            if not batch:
                break
            results.extend(batch)
    except Exception as e:
        logger.warning(f"Keyword search failed: {e}")
    return results


def _rrf_fuse(dense_hits: list, sparse_hits: list, k: int = 60) -> list[dict]:
    """Reciprocal Rank Fusion."""
    fused = {}
    for rank, hit in enumerate(dense_hits):
        cid = hit.id
        fused[cid] = {
            **hit.fields, "id": cid,
            "score": fused.get(cid, {}).get("score", 0) + 1.0 / (k + rank + 1)
        }
    for rank, hit in enumerate(sparse_hits):
        cid = hit.get("id", "")
        if cid in fused:
            fused[cid]["score"] += 1.0 / (k + rank + 1)
        else:
            fused[cid] = {**hit, "score": 1.0 / (k + rank + 1)}
    return list(fused.values())


async def rerank_chunks(query: str, chunks: list[dict], top_n: int = None) -> list[dict]:
    """Rerank chunks by semantic relevance."""
    top_n = top_n or settings.RERANK_TOP_N
    if not chunks:
        return []
    docs = [ch.get("content_zh") or ch.get("content_en", "") for ch in chunks]
    try:
        results = await rerank(query, docs, top_n)
    except Exception as e:
        logger.warning(f"Rerank failed: {e}; returning unsorted")
        return chunks[:top_n]

    ranked = []
    for r in sorted(results, key=lambda x: x.get("relevance_score", 0), reverse=True):
        idx = r.get("index", 0)
        if idx < len(chunks):
            ranked.append({**chunks[idx], "rerank_score": r.get("relevance_score", 0)})
    return ranked[:top_n]
