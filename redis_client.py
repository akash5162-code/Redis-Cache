import os
import redis.asyncio as redis

# -----------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------
# Change REDIS_URL if your Redis is not running on the default port.
# E.g. if you're using Docker: "redis://localhost:6379"
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# How long (in seconds) we keep a cached product before it auto-expires.
# After 60 seconds Redis will automatically delete the key — stale data problem solved!
CACHE_TTL = 60  # seconds

# -----------------------------------------------------------------------
# Global Redis client (initialized during app startup via lifespan)
# -----------------------------------------------------------------------
redis_client: redis.Redis = None


async def init_redis():
    """
    Create the async Redis connection pool and verify the connection.
    Called once at application startup (see lifespan in main.py).
    
    decode_responses=True → Redis returns strings instead of bytes,
    so we don't need to call .decode() everywhere.
    """
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    await redis_client.ping()  # Will raise ConnectionError if Redis is not running
    print(f"✅ Redis connected at {REDIS_URL}")


async def close_redis():
    """
    Gracefully close the Redis connection pool.
    Called once at application shutdown (see lifespan in main.py).
    """
    global redis_client
    if redis_client:
        await redis_client.aclose()
        print("🔴 Redis connection closed")


def get_client() -> redis.Redis:
    """
    Getter for the Redis client — always returns the live object.

    WHY this exists:
        Python's `from module import variable` copies the VALUE at import time.
        Since redis_client starts as None and is only assigned inside init_redis(),
        any module that does `from redis_client import redis_client` would
        get None forever — even after init_redis() runs.

        Using get_client() instead always reads the current value of the
        global redis_client from this module's namespace, so it works correctly.
    """
    return redis_client
