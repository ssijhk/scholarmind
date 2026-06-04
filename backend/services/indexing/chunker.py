"""Semantic chunker: split doc_blocks into retrievable chunks.

Rules:
- Text blocks: split by paragraph/sentence with ~20% overlap
- Table / Formula / Figure: kept whole (small-big retrieval)
- Every chunk carries: user_id, paper_id, folder_id, page_num, block_id, image_key
- chunk_id = xxhash(user_id + paper_id + block_id + chunk_index)
"""
import xxhash
from typing import Optional


async def chunk_doc_blocks(
    paper_id: str,
    user_id: str,
    blocks: list[dict],
    max_chunk_size: int = 2048,
    overlap: float = 0.2,
) -> list[dict]:
    """Split doc_blocks into retrievable chunks."""
    chunks: list[dict] = []

    for block in blocks:
        block_type = block.get("block_type", "text")
        block_id = str(block.get("id", ""))
        page_num = block.get("page_num")
        image_key = block.get("image_key", "")
        folder_id = block.get("folder_id", "")
        content = block.get("content", "") or ""

        if not content.strip():
            continue

        if block_type in ("table", "formula", "figure"):
            ch_type = "table_html" if block_type == "table" else block_type
            chunks.append(
                _make_chunk(
                    user_id, paper_id, folder_id, page_num, block_id, image_key, ch_type, content, 0
                )
            )
        else:
            parts = semantic_split_text(content, max_chunk_size, overlap)
            for idx, part in enumerate(parts):
                chunks.append(
                    _make_chunk(
                        user_id, paper_id, folder_id, page_num, block_id, image_key, "text", part, idx
                    )
                )

    return chunks


def semantic_split_text(
    text: str, max_chars: int = 2048, overlap: float = 0.2
) -> list[str]:
    """Split text by semantic boundaries with overlap."""
    if len(text) <= max_chars:
        return [text] if text.strip() else []

    parts = []
    pos = 0
    overlap_chars = int(max_chars * overlap)

    while pos < len(text):
        end = min(pos + max_chars, len(text))
        chunk = text[pos:end]

        # Try to break at a clean boundary (search backwards)
        if end < len(text):
            for sep in ["\n\n", "\n", ". ", "。", "; ", "；"]:
                last = chunk.rfind(sep)
                if last > max_chars * 0.5:
                    chunk = chunk[: last + len(sep)]
                    end = pos + len(chunk)
                    break

        parts.append(chunk.strip())
        pos = end - overlap_chars if end < len(text) else len(text)

    return parts


def _make_chunk(
    user_id: str,
    paper_id: str,
    folder_id: str,
    page_num: Optional[int],
    block_id: str,
    image_key: str,
    chunk_type: str,
    content: str,
    idx: int,
) -> dict:
    return {
        "chunk_id": xxhash.xxh64(f"{user_id}_{paper_id}_{block_id}_{idx}").hexdigest(),
        "user_id": user_id,
        "paper_id": paper_id,
        "folder_id": folder_id,
        "page_num": page_num or 0,
        "block_id": block_id,
        "image_key": image_key,
        "chunk_type": chunk_type,
        "content_en": content,
        "content_zh": "",
        "sentences_en": "",
        "keywords_en": "",
        "summary_zh": "",
    }
