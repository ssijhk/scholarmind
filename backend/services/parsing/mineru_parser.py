"""MinerU API integration — direct HTTP with auth token support."""
import asyncio
import os
import tempfile
import httpx
from common.config import settings
from common.logging import logger

MINERU_TIMEOUT = 300
POLL_INTERVAL = 5


async def parse_pdf_with_mineru(pdf_bytes: bytes) -> dict:
    """Upload PDF to MinerU cloud API, poll until done, return structured blocks."""
    pipeline_id = getattr(settings, "MINERU_PIPELINE_ID", "")
    if not pipeline_id:
        logger.warning("MINERU_PIPELINE_ID not set; skipping MinerU parsing")
        return {"text_blocks": [], "formulas": [], "tables": [], "figures": []}

    # Write to temp file
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(pdf_bytes)
            tmp_path = f.name

        base = settings.MINERU_BASE_URL.rstrip("/")

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            # Upload PDF — send pipeline_id in body, auth token in header
            logger.info(f"MinerU: uploading {len(pdf_bytes)} bytes...")
            with open(tmp_path, "rb") as fp:
                upload_resp = await client.post(
                    f"{base}/restful/pipelines/{pipeline_id}/upload",
                    files={"file": ("paper.pdf", fp, "application/pdf")},
                    headers={"Authorization": f"Bearer {pipeline_id}"},
                )
            if upload_resp.status_code >= 400:
                logger.error(f"MinerU upload failed: {upload_resp.status_code} {upload_resp.text[:200]}")
                raise RuntimeError(f"MinerU upload failed: {upload_resp.status_code}")

            upload_data = upload_resp.json()
            file_ids = upload_data.get("file_ids") or upload_data.get("data", {}).get("file_ids") or []
            if not file_ids:
                # Maybe it's a single file_id
                file_ids = [upload_data.get("file_id")] if upload_data.get("file_id") else []
            logger.info(f"MinerU file_ids: {file_ids}")

            # Poll for completion
            deadline = asyncio.get_event_loop().time() + MINERU_TIMEOUT
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(POLL_INTERVAL)
                result_resp = await client.get(
                    f"{base}/restful/pipelines/{pipeline_id}/files/{file_ids[0]}/result"
                    if file_ids else f"{base}/restful/pipelines/{pipeline_id}/result",
                    headers={"Authorization": f"Bearer {pipeline_id}"},
                )
                if result_resp.status_code == 200:
                    blocks = _normalize_result(result_resp.json())
                    logger.info(f"MinerU done: {len(blocks.get('text_blocks',[]))} text")
                    return blocks
                elif result_resp.status_code == 404:
                    continue  # still processing

            logger.warning("MinerU timed out")

    except Exception as e:
        logger.error(f"MinerU parsing failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

    return {"text_blocks": [], "formulas": [], "tables": [], "figures": []}


def _normalize_result(result) -> dict:
    text_blocks, formulas, tables, figures = [], [], [], []
    items = result if isinstance(result, list) else result.get("blocks", result.get("data", []))
    if isinstance(items, dict):
        items = items.get("blocks", items.get("data", []))

    for item in items:
        bt = item.get("type", "text") if isinstance(item, dict) else getattr(item, "type", "text")
        content = (
            item.get("content", item.get("text", "")) if isinstance(item, dict)
            else getattr(item, "content", getattr(item, "text", ""))
        ) or ""
        page_num = item.get("page_num", 0) if isinstance(item, dict) else getattr(item, "page_num", 0)

        entry = {"content": content, "page_num": page_num, "bbox": []}
        if bt in ("text", "paragraph", "title"):
            text_blocks.append(entry)
        elif bt in ("formula", "equation"):
            formulas.append(entry)
        elif bt in ("table",):
            tables.append(entry)
        elif bt in ("figure", "image"):
            figures.append(entry)

    return {"text_blocks": text_blocks, "formulas": formulas, "tables": tables, "figures": figures}
