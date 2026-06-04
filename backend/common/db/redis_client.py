"""Redis client for caching, RQ queue, rate-limiting."""
import redis.asyncio as aioredis
from common.config import settings

redis = aioredis.Redis(
    host=settings.REDIS_HOST,
    port=settings.REDIS_PORT,
    db=settings.REDIS_DB,
    decode_responses=True,
)
