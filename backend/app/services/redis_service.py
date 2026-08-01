import redis.asyncio as redis
from app.config import settings
import json
from typing import Optional, Any

redis_client: Optional[redis.Redis] = None


async def init_redis():
    global redis_client
    redis_client = redis.Redis(
        host=settings.REDIS_HOST,
        port=settings.REDIS_PORT,
        db=settings.REDIS_DB,
        password=settings.REDIS_PASSWORD or None,
        decode_responses=True,
    )
    return redis_client


async def get_redis() -> redis.Redis:
    if not redis_client:
        await init_redis()
    return redis_client


async def cache_get(key: str) -> Optional[Any]:
    client = await get_redis()
    data = await client.get(key)
    return json.loads(data) if data else None


async def cache_set(key: str, value: Any, expire: int = 300):
    client = await get_redis()
    await client.setex(key, expire, json.dumps(value))


async def cache_delete(key: str):
    client = await get_redis()
    await client.delete(key)


async def rate_limit_check(key: str, limit: int, window: int = 60) -> bool:
    client = await get_redis()
    current = await client.get(key)
    if current and int(current) >= limit:
        return False
    pipe = client.pipeline()
    await pipe.incr(key)
    await pipe.expire(key, window)
    await pipe.execute()
    return True
