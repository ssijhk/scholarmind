"""Vectorization and Milvus insertion.

Calls Embedding API for dense vectors, builds Milvus insert batches.
"""
from common.clients.llm import embed_texts
from common.db.milvus_client import ensure_collection
from common.config import settings
from common.logging import logger


async def vectorize_and_insert(chunks: list[dict], user_id: str) -> int:
    """Embed content_en fields and insert into Milvus in batches.

    Returns number of chunks inserted.
    """
    if not chunks:
        return 0

    col = ensure_collection()
    batch_size = settings.EMBEDDING_BATCH

    inserted = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        contents = [ch.get("content_en", "") for ch in batch]

        try:
            embeddings = await embed_texts(contents)
        except Exception as e:
            logger.error(f"Embedding failed for batch {i}: {e}")
            continue

        rows = []
        for j, chunk in enumerate(batch):
            vec = embeddings[j] if j < len(embeddings) else None
            if vec is None or len(vec) != settings.EMBEDDING_DIM:
                continue

            row = {
                "id": chunk["chunk_id"],
                "dense_vec": vec,
                "user_id": chunk.get("user_id", ""),
                "paper_id": chunk.get("paper_id", ""),
                "folder_id": chunk.get("folder_id") or "",
                "content_en": chunk.get("content_en") or "",
                "content_zh": chunk.get("content_zh") or "",
                "page_num": chunk.get("page_num") or 0,
                "block_id": chunk.get("block_id") or "",
                "image_key": chunk.get("image_key") or "",
                "chunk_type": chunk.get("chunk_type") or "text",
                "sentences_en": chunk.get("sentences_en") or "",
                "keywords_en": chunk.get("keywords_en") or "",
                "summary_zh": chunk.get("summary_zh") or "",
            }
            rows.append(row)

        if rows:
            try:
                col.insert(rows)
                col.flush()
                inserted += len(rows)
                logger.info(f"Inserted {len(rows)} chunks into Milvus (batch {i})")
            except Exception as e:
                logger.error(f"Milvus insert failed for batch {i}: {e}")

    return inserted
