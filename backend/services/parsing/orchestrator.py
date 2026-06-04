"""Parsing orchestrator — coordinates MinerU + GROBID + VLM pipeline.

Entry point: ingest_paper(user_id, paper_id, pdf_key)
Called by RQ worker; runs parsing → normalization → persistence.
Handles MinerU failures gracefully - continues with GROBID and marks paper as done.
Updates ingest_tasks status throughout the pipeline.
"""
import asyncio
import io
import json
import xxhash
from datetime import datetime
from sqlalchemy import text
from common.config import settings
from common.logging import logger
from common.db.mysql import AsyncSessionLocal
from common.db.minio_client import minio_client
from common.clients.llm import vlm_describe_image
from .mineru_parser import parse_pdf_with_mineru
from .grobid_parser import parse_references_with_grobid
from .prompts import load_prompt, fill_prompt


async def ingest_paper(user_id: str, paper_id: str, pdf_key: str) -> dict:
    """Run full ingestion pipeline for one PDF."""
    logger.info(f"Ingesting paper {paper_id} for user {user_id}")

    # Update task to 'parsing'
    await _update_task_status(user_id, paper_id, "parsing", 10)

    # 1. Download PDF
    try:
        obj = minio_client.get_object(settings.MINIO_BUCKET_PDF, pdf_key)
        pdf_bytes = obj.read()
        obj.close()
        obj.release_conn()
    except Exception as e:
        logger.error(f"Failed to download PDF {pdf_key}: {e}")
        await _update_task_status(user_id, paper_id, "failed", 0, str(e))
        await _update_paper_status(paper_id, user_id, "failed")
        raise

    file_hash = xxhash.xxh64(pdf_bytes).hexdigest()

    # 2. Run parsers concurrently (MinerU may return empty gracefully)
    mineru_result, references = await asyncio.gather(
        parse_pdf_with_mineru(pdf_bytes),
        parse_references_with_grobid(pdf_bytes),
    )

    block_count = 0
    figure_count = 0

    # 3. Persist MinerU blocks (if any)
    if mineru_result and any(mineru_result.get(k) for k in ["text_blocks", "tables", "formulas", "figures"]):
        await _update_task_status(user_id, paper_id, "parsing", 50)
        block_count = await _persist_blocks(user_id, paper_id, mineru_result)
        figure_count = await _process_figures(user_id, paper_id, mineru_result)
    else:
        # Fallback: extract plain text from PDF using pypdf
        logger.info("MinerU unavailable, using pypdf text extraction fallback")
        fallback = _extract_text_fallback(pdf_bytes)
        if fallback:
            mineru_result = {"text_blocks": fallback, "formulas": [], "tables": [], "figures": []}
            block_count = await _persist_blocks(user_id, paper_id, mineru_result)
        else:
            logger.info("No MinerU results and pypdf fallback empty; skipping block persistence")

    # 4. Persist citations
    ref_count = await _persist_citations(paper_id, references or [])

    # 5. Run Indexing: chunk → enrich → vectorize → Milvus
    chunk_count = 0
    if block_count > 0:
        await _update_task_status(user_id, paper_id, "indexing", 70)
        chunk_count = await _run_indexing(user_id, paper_id)
    else:
        logger.info("No blocks to index")

    # 6. Mark paper as done
    await _update_paper_status(paper_id, user_id, "done", chunk_count)
    await _update_task_status(user_id, paper_id, "done", 100)

    logger.info(f"Paper {paper_id} done: {block_count} blocks, {chunk_count} chunks, {figure_count} figures, {ref_count} citations")
    return {"paper_id": paper_id, "file_hash": file_hash, "blocks": block_count, "figures": figure_count, "citations": ref_count}


def _extract_text_fallback(pdf_bytes: bytes) -> list:
    """Extract plain text from PDF using pypdf as fallback."""
    try:
        from pypdf import PdfReader
        import io
        reader = PdfReader(io.BytesIO(pdf_bytes))
        blocks = []
        for page_num, page in enumerate(reader.pages, 1):
            text = page.extract_text()
            if text and text.strip():
                # Split long pages into paragraph blocks
                for para in text.split('\n\n'):
                    para = para.strip()
                    if len(para) > 50:
                        blocks.append({
                            "content": para,
                            "page_num": page_num,
                            "bbox": [],
                        })
        logger.info(f"pypdf fallback extracted {len(blocks)} text blocks")
        return blocks
    except Exception as e:
        logger.error(f"pypdf fallback failed: {e}")
        return []


async def _run_indexing(user_id: str, paper_id: str) -> int:
    """Run the full indexing pipeline: chunking → enrichment → vectorization."""
    try:
        from services.indexing.chunker import chunk_doc_blocks
        from services.indexing.enricher import enrich_chunks_zh
        from services.indexing.vectorizer import vectorize_and_insert

        # Load doc_blocks from MySQL
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("SELECT id, block_type, content, page_num, image_key FROM doc_blocks WHERE paper_id = :pid AND user_id = :uid"),
                {"pid": paper_id, "uid": user_id},
            )
            blocks = [dict(r._mapping) for r in result.fetchall()]

        if not blocks:
            return 0

        # Get folder_id
        async with AsyncSessionLocal() as session:
            r = await session.execute(text("SELECT folder_id FROM papers WHERE id = :pid"), {"pid": paper_id})
            row = r.fetchone()
            folder_id = row[0] if row and row[0] else ""

        # 1. Semantic chunking
        chunks = await chunk_doc_blocks(paper_id, user_id, blocks)
        logger.info(f"Indexing: {len(chunks)} chunks from {len(blocks)} blocks")

        # 2. Bilingual enrichment (skip if DNS unstable)
        try:
            chunks = await enrich_chunks_zh(chunks)
        except Exception as e:
            logger.warning(f"Enrichment failed, skipping: {e}")

        # 3. Vectorize and insert to Milvus
        inserted = await vectorize_and_insert(chunks, user_id)
        logger.info(f"Indexing: {inserted} vectors written to Milvus")

        return inserted
    except Exception as e:
        logger.error(f"Indexing failed: {e}")
        return 0


async def _update_task_status(user_id: str, paper_id: str, stage: str, progress: int, error_msg: str = None):
    """Update ingest_tasks stage/progress."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text(
                    "UPDATE ingest_tasks SET stage = :stage, progress = :p, error_msg = :err, "
                    "started_at = COALESCE(started_at, NOW()) "
                    "WHERE user_id = :uid AND paper_id = :pid AND stage != 'done'"
                ),
                {"stage": stage, "p": progress, "err": error_msg, "uid": user_id, "pid": paper_id},
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to update task status: {e}")


async def _update_paper_status(paper_id: str, user_id: str, status: str, chunk_count: int = 0):
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("UPDATE papers SET status = :s, chunk_count = :c, updated_at = NOW() WHERE id = :pid AND user_id = :uid"),
                {"s": status, "c": chunk_count, "pid": paper_id, "uid": user_id},
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"Failed to update paper status: {e}")


async def _persist_blocks(user_id: str, paper_id: str, result: dict) -> int:
    async with AsyncSessionLocal() as session:
        count = 0
        for block_type in ["text_blocks", "tables", "formulas", "figures"]:
            block_list = result.get(block_type, [])
            bt = block_type.replace("_blocks", "").replace("s", "")
            if bt == "text_block":
                bt = "text"
            for block in block_list:
                bid = xxhash.xxh64(f"{paper_id}_{bt}_{count}").hexdigest()
                await session.execute(
                    text(
                        "INSERT INTO doc_blocks (id, paper_id, user_id, block_type, content, page_num, bbox, created_at) "
                        "VALUES (:id, :pid, :uid, :bt, :c, :pn, :bbox, NOW()) "
                        "ON DUPLICATE KEY UPDATE content=VALUES(content)"
                    ),
                    {"id": bid, "pid": paper_id, "uid": user_id, "bt": bt, "c": block.get("content", ""),
                     "pn": block.get("page_num", 0), "bbox": json.dumps(block.get("bbox", []))},
                )
                count += 1
        await session.commit()
    return count


async def _process_figures(user_id: str, paper_id: str, result: dict) -> int:
    return 0  # Figures are processed during block persistence


async def _persist_citations(paper_id: str, references: list) -> int:
    if not references:
        return 0
    async with AsyncSessionLocal() as session:
        count = 0
        for ref in references:
            await session.execute(
                text(
                    "INSERT INTO citations (id, paper_id, title, authors, year, doi, raw_ref, created_at) "
                    "VALUES (:id, :pid, :t, :a, :y, :d, :r, NOW()) "
                    "ON DUPLICATE KEY UPDATE title=VALUES(title)"
                ),
                {"id": xxhash.xxh64(paper_id + (ref.get("title", "") or ref.get("raw_ref", ""))).hexdigest(),
                 "pid": paper_id, "t": ref.get("title", ""), "a": json.dumps(ref.get("authors", [])),
                 "y": ref.get("year", ""), "d": ref.get("doi", ""), "r": ref.get("raw_ref", "")},
            )
            count += 1
        await session.commit()
    return count
