import redis.asyncio as aioredis
from app.core.config import settings

_redis_client = None

def get_redis_client() -> aioredis.Redis:
    """Returns a shared, lazily initialized async Redis client instance."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=5.0,
            socket_connect_timeout=5.0
        )
    return _redis_client
