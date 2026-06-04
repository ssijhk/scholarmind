"""Settings router — read/write RAG optimization switches.

Settings are persisted to Redis for real-time updates across backend restarts.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from common.auth.deps import get_current_user_id
from common.db.redis_client import redis
from common.config import settings as cfg
from common.logging import logger

router = APIRouter(prefix="/settings", tags=["settings"])

REDIS_KEY = "scholarmind:rag_settings"


class RAGSettingsResponse(BaseModel):
    # Switches
    ENABLE_INTENT_ROUTER: bool = True
    ENABLE_QUERY_REWRITE: bool = True
    ENABLE_MULTI_QUERY: bool = False
    ENABLE_HYDE: bool = True
    ENABLE_QUERY_TRANSLATION: bool = True
    ENABLE_RERANK: bool = True
    ENABLE_CORRECTIVE_RAG: bool = False
    ENABLE_SELF_RAG_REFLECT: bool = False
    # Parameters
    RETRIEVAL_TOP_K: int = 20
    HYBRID_DENSE_WEIGHT: float = 0.6
    # Model info
    LLM_MODEL: str = ""
    LLM_PROVIDER: str = ""
    EMBEDDING_MODEL: str = ""
    EMBEDDING_DIM: int = 1024


@router.get("/rag", response_model=RAGSettingsResponse)
async def get_settings(user_id: str = Depends(get_current_user_id)):
    """Get current RAG settings (from Redis or defaults from config)."""
    try:
        raw = await redis.hgetall(REDIS_KEY)
        if raw:
            raw = {k.decode() if isinstance(k, bytes) else k:
                   _parse_val(v) for k, v in raw.items()}
            return RAGSettingsResponse(
                ENABLE_INTENT_ROUTER=raw.get("ENABLE_INTENT_ROUTER", cfg.ENABLE_INTENT_ROUTER),
                ENABLE_QUERY_REWRITE=raw.get("ENABLE_QUERY_REWRITE", cfg.ENABLE_QUERY_REWRITE),
                ENABLE_MULTI_QUERY=raw.get("ENABLE_MULTI_QUERY", cfg.ENABLE_MULTI_QUERY),
                ENABLE_HYDE=raw.get("ENABLE_HYDE", cfg.ENABLE_HYDE),
                ENABLE_QUERY_TRANSLATION=raw.get("ENABLE_QUERY_TRANSLATION", cfg.ENABLE_QUERY_TRANSLATION),
                ENABLE_RERANK=raw.get("ENABLE_RERANK", cfg.ENABLE_RERANK),
                ENABLE_CORRECTIVE_RAG=raw.get("ENABLE_CORRECTIVE_RAG", cfg.ENABLE_CORRECTIVE_RAG),
                ENABLE_SELF_RAG_REFLECT=raw.get("ENABLE_SELF_RAG_REFLECT", cfg.ENABLE_SELF_RAG_REFLECT),
                RETRIEVAL_TOP_K=int(raw.get("RETRIEVAL_TOP_K", cfg.RETRIEVAL_TOP_K)),
                HYBRID_DENSE_WEIGHT=float(raw.get("HYBRID_DENSE_WEIGHT", cfg.HYBRID_DENSE_WEIGHT)),
                LLM_MODEL=cfg.LLM_MODEL, LLM_PROVIDER=cfg.LLM_PROVIDER,
                EMBEDDING_MODEL=cfg.EMBEDDING_MODEL, EMBEDDING_DIM=cfg.EMBEDDING_DIM,
            )
    except Exception as e:
        logger.warning(f"Failed to read settings from Redis: {e}")

    # Fallback to config defaults
    return RAGSettingsResponse(
        ENABLE_INTENT_ROUTER=cfg.ENABLE_INTENT_ROUTER,
        ENABLE_QUERY_REWRITE=cfg.ENABLE_QUERY_REWRITE,
        ENABLE_MULTI_QUERY=cfg.ENABLE_MULTI_QUERY,
        ENABLE_HYDE=cfg.ENABLE_HYDE,
        ENABLE_QUERY_TRANSLATION=cfg.ENABLE_QUERY_TRANSLATION,
        ENABLE_RERANK=cfg.ENABLE_RERANK,
        ENABLE_CORRECTIVE_RAG=cfg.ENABLE_CORRECTIVE_RAG,
        ENABLE_SELF_RAG_REFLECT=cfg.ENABLE_SELF_RAG_REFLECT,
        RETRIEVAL_TOP_K=cfg.RETRIEVAL_TOP_K,
        HYBRID_DENSE_WEIGHT=cfg.HYBRID_DENSE_WEIGHT,
        LLM_MODEL=cfg.LLM_MODEL, LLM_PROVIDER=cfg.LLM_PROVIDER,
        EMBEDDING_MODEL=cfg.EMBEDDING_MODEL, EMBEDDING_DIM=cfg.EMBEDDING_DIM,
    )


@router.put("/rag", response_model=RAGSettingsResponse)
async def update_settings(data: RAGSettingsResponse, user_id: str = Depends(get_current_user_id)):
    """Save RAG settings to Redis and update runtime config."""
    try:
        payload = data.model_dump(exclude={"LLM_MODEL", "LLM_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIM"})
        await redis.hset(REDIS_KEY, mapping={k: str(v) for k, v in payload.items()})
        # Reflect changes to runtime settings object (module-level singleton)
        for key, val in payload.items():
            if hasattr(cfg, key):
                setattr(cfg, key, val)
        logger.info(f"RAG settings updated by user {user_id}")
    except Exception as e:
        logger.error(f"Failed to save settings: {e}")

    return data


def _parse_val(v) -> str:
    if isinstance(v, bytes):
        return v.decode()
    return v
