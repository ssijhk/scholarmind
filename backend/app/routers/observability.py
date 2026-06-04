"""Observability router — real MySQL-backed stats and logs."""
import json
from fastapi import APIRouter, Depends, Query
from typing import List
from sqlalchemy import text
from app.schemas.observability import QueryLogResponse, AccessLogResponse, StatsOverviewResponse, IngestTaskResponse
from common.auth.deps import get_current_user_id
from common.db.mysql import AsyncSessionLocal
from common.logging import logger

router = APIRouter(tags=["observability"])


def _parse_json_list(val) -> list:
    """Parse a value that might be a JSON string or already a list."""
    if val is None:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    if isinstance(val, str):
        if not val.strip():
            return []
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return [str(v) for v in parsed]
            return []
        except (json.JSONDecodeError, TypeError):
            return []
    return []


@router.get("/logs/queries", response_model=List[QueryLogResponse])
async def list_query_logs(user_id: str = Depends(get_current_user_id), limit: int = Query(10), offset: int = Query(0)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, user_id, question, rewritten_query, latency_ms, prompt_tokens, "
                "completion_tokens, retrieved_chunk_ids, feedback, created_at "
                "FROM query_logs WHERE user_id = :uid ORDER BY created_at DESC LIMIT :lim OFFSET :off"
            ),
            {"uid": user_id, "lim": limit, "off": offset},
        )
        rows = result.fetchall()
        return [
            QueryLogResponse(
                id=str(r[0]), user_id=str(r[1]) if r[1] else None,
                question=r[2] or "", rewritten_query=r[3],
                latency_ms=r[4], prompt_tokens=r[5], completion_tokens=r[6],
                retrieved_chunk_ids=_parse_json_list(r[7]),
                feedback=r[8], created_at=r[9],
            )
            for r in rows
        ]


@router.get("/logs/access", response_model=List[AccessLogResponse])
async def list_access_logs(limit: int = Query(10), offset: int = Query(0)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, user_id, method, path, status_code, ip, latency_ms, created_at "
                "FROM access_logs ORDER BY created_at DESC LIMIT :lim OFFSET :off"
            ),
            {"lim": limit, "off": offset},
        )
        rows = result.fetchall()
        return [
            AccessLogResponse(
                id=str(r[0]), user_id=str(r[1]) if r[1] else None,
                method=r[2] or "", path=r[3] or "", status_code=r[4] or 200,
                ip_address=r[5], created_at=r[7],
            )
            for r in rows
        ]


@router.get("/stats/overview", response_model=StatsOverviewResponse)
async def get_stats_overview(user_id: str = Depends(get_current_user_id)):
    async with AsyncSessionLocal() as session:
        # Paper count
        r = await session.execute(text("SELECT COUNT(*) FROM papers WHERE user_id = :uid"), {"uid": user_id})
        paper_count = r.scalar() or 0

        # Chunk count
        r = await session.execute(text("SELECT SUM(chunk_count) FROM papers WHERE user_id = :uid"), {"uid": user_id})
        chunk_count = r.scalar() or 0

        # Total queries
        r = await session.execute(text("SELECT COUNT(*) FROM query_logs WHERE user_id = :uid"), {"uid": user_id})
        total_queries = r.scalar() or 0

        # Average latency
        r = await session.execute(
            text("SELECT AVG(latency_ms) FROM query_logs WHERE user_id = :uid AND latency_ms IS NOT NULL"),
            {"uid": user_id},
        )
        avg_lat = r.scalar() or 0.0

    return StatsOverviewResponse(
        paper_count=int(paper_count), chunk_count=int(chunk_count),
        total_queries=int(total_queries), average_latency_ms=float(avg_lat),
    )


@router.get("/tasks", response_model=List[IngestTaskResponse])
async def list_ingest_tasks(user_id: str = Depends(get_current_user_id), limit: int = Query(10)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text(
                "SELECT id, file_name, stage, progress, error_msg, started_at "
                "FROM ingest_tasks WHERE user_id = :uid ORDER BY created_at DESC LIMIT :lim"
            ),
            {"uid": user_id, "lim": limit},
        )
        rows = result.fetchall()
        return [
            IngestTaskResponse(
                id=str(r[0]), file_name=r[1] or "", stage=r[2] or "queued",
                progress=r[3] or 0, error_msg=r[4], started_at=r[5],
            )
            for r in rows
        ]
