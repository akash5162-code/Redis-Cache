"""
FastAPI + Redis: Cache-Aside Pattern Demo
=========================================

Use Case: E-Commerce Product Catalog API

Redis Concepts Demonstrated:
  1. Cache-Aside (Lazy Loading) Pattern  — GET /products/{id}
  2. TTL (Time to Live / Auto-Expiry)   — setex() with CACHE_TTL
  3. Cache Invalidation                 — DELETE/PUT remove Redis key
  4. JSON Serialization in Redis        — json.dumps / json.loads
  5. Async Redis with FastAPI           — redis.asyncio + lifespan

Run:
    uvicorn main:app --reload

Swagger UI:
    http://127.0.0.1:8000/docs
"""

import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException

from database import (
    create_product,
    delete_product,
    get_all_products,
    get_product_by_id,
    init_db,
    update_product,
)
from models import Product, ProductCreate
from redis_client import CACHE_TTL, close_redis, init_redis, get_client


# -----------------------------------------------------------------------
# Lifespan — startup & shutdown logic (modern FastAPI pattern)
# -----------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Everything BEFORE the yield runs at startup.
    Everything AFTER the yield runs at shutdown.
    This replaces the old @app.on_event("startup") style.
    """
    print("\n🚀 Starting up...")
    await init_db()       # Create SQLite tables + seed data
    await init_redis()    # Open Redis connection pool
    yield
    print("\n🛑 Shutting down...")
    await close_redis()   # Gracefully close Redis connection pool


# -----------------------------------------------------------------------
# App instance
# -----------------------------------------------------------------------
app = FastAPI(
    title="🛒 Product Catalog API",
    description=(
        "A learning project demonstrating the **Cache-Aside Pattern** "
        "with **FastAPI** and **Redis**. \n\n"
        "Every GET /products/{id} response includes:\n"
        "- `source` → `cache ⚡` or `database 🗄️`\n"
        "- `response_time_ms` → see the speed difference!\n"
        "- `ttl_remaining` → how many seconds before cache expires"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


# -----------------------------------------------------------------------
# Helper
# -----------------------------------------------------------------------
def cache_key(product_id: int) -> str:
    """
    Redis key naming convention: <namespace>:<identifier>
    Example: "product:1", "product:42"
    
    Using a namespace prefix ("product:") is best practice —
    it avoids key collisions if you store other data in the same Redis instance.
    """
    return f"product:{product_id}"


# -----------------------------------------------------------------------
# ROUTE 1: List all products — always from DB, no caching
# -----------------------------------------------------------------------
@app.get(
    "/products",
    summary="List all products",
    description=(
        "Returns all products **directly from SQLite** (no cache). "
        "List endpoints are usually not cached because the data changes frequently "
        "and the cache key would be hard to invalidate."
    ),
)
async def list_products():
    products = await get_all_products()
    return {
        "source": "database 🗄️",
        "total": len(products),
        "data": products,
    }


# -----------------------------------------------------------------------
# ROUTE 2: Get single product — Cache-Aside Pattern ⚡
# -----------------------------------------------------------------------
@app.get(
    "/products/{product_id}",
    response_model=None,
    summary="Get product by ID  [Cache-Aside Pattern]",
    description=(
        "**The core Redis concept.** \n\n"
        "**Step 1** → Check Redis for the key `product:{id}`\n\n"
        "**If HIT** → Return cached data instantly (sub-millisecond ⚡)\n\n"
        "**If MISS** → Query SQLite (slow, ~500ms), write result to Redis with a "
        f"{CACHE_TTL}s TTL, return data.\n\n"
        "Hit this endpoint **twice** and watch `source` and `response_time_ms` change!"
    ),
)
async def get_product(product_id: int):
    key = cache_key(product_id)
    start = time.perf_counter()
    rc = get_client()  # Always fetches the live Redis client (avoids import-time None bug)

    # ── Step 1: Check Redis ──────────────────────────────────────────────
    cached_value = await rc.get(key)

    if cached_value:
        # ✅ CACHE HIT
        elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
        ttl = await rc.ttl(key)   # How many seconds until this key expires
        return {
            "source": "cache ⚡",
            "response_time_ms": elapsed_ms,
            "ttl_remaining_seconds": ttl,
            "message": "Served from Redis — no DB query needed!",
            "data": json.loads(cached_value),
        }

    # ── Step 2: Cache Miss → Query SQLite ───────────────────────────────
    # get_product_by_id() has an intentional 500ms sleep to simulate real DB latency
    product = await get_product_by_id(product_id)

    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    # ── Step 3: Write to Redis (setex = SET + EXPIRE in one atomic command) ──
    # json.dumps() converts the dict → JSON string (Redis only stores strings)
    await rc.setex(
        name=key,            # Key:   "product:1"
        time=CACHE_TTL,      # TTL:   60 seconds
        value=json.dumps(product),  # Value: '{"id": 1, "name": "Laptop", ...}'
    )

    elapsed_ms = round((time.perf_counter() - start) * 1000, 3)
    return {
        "source": "database 🗄️",
        "response_time_ms": elapsed_ms,
        "cache_written": True,
        "cache_ttl_seconds": CACHE_TTL,
        "message": "Fetched from SQLite and written to Redis cache.",
        "data": product,
    }


# -----------------------------------------------------------------------
# ROUTE 3: Create product — pre-populate cache
# -----------------------------------------------------------------------
@app.post(
    "/products",
    status_code=201,
    summary="Create a new product",
    description=(
        "Creates a product in SQLite and **immediately pre-populates the Redis cache**. "
        "This is a proactive cache write — the first GET will already be a cache hit."
    ),
)
async def add_product(product: ProductCreate):
    # Insert into SQLite
    new_id = await create_product(
        product.name, product.description, product.price, product.stock
    )
    new_product = {"id": new_id, **product.model_dump()}

    # Pre-populate cache so the first GET is a hit, not a miss
    await get_client().setex(
        name=cache_key(new_id),
        time=CACHE_TTL,
        value=json.dumps(new_product),
    )

    return {
        "message": "Product created ✅",
        "cache_pre_populated": True,
        "cache_ttl_seconds": CACHE_TTL,
        "data": new_product,
    }


# -----------------------------------------------------------------------
# ROUTE 4: Update product — Cache Invalidation 🗑️
# -----------------------------------------------------------------------
@app.put(
    "/products/{product_id}",
    summary="Update a product  [Cache Invalidation]",
    description=(
        "Updates the product in SQLite and **deletes the Redis cache key**. \n\n"
        "This is called **Cache Invalidation** — we remove the stale cached version "
        "so the next GET will re-fetch fresh data from the DB and write a new cache entry."
    ),
)
async def edit_product(product_id: int, product: ProductCreate):
    # Verify product exists
    existing = await get_product_by_id(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    # Update in SQLite
    await update_product(
        product_id, product.name, product.description, product.price, product.stock
    )

    # ── Cache Invalidation ───────────────────────────────────────────────
    # Delete the stale Redis key. The next GET will be a cache miss
    # and will re-fetch the updated data, writing a fresh cache entry.
    key = cache_key(product_id)
    deleted_count = await get_client().delete(key)  # Returns 1 if key existed, 0 if not

    updated_product = {"id": product_id, **product.model_dump()}
    return {
        "message": "Product updated ✅",
        "cache_invalidated": bool(deleted_count),  # True if key was in cache
        "note": "Next GET will be a cache miss and will re-populate the cache.",
        "data": updated_product,
    }


# -----------------------------------------------------------------------
# ROUTE 5: Delete product — remove from DB AND cache
# -----------------------------------------------------------------------
@app.delete(
    "/products/{product_id}",
    summary="Delete a product  [Cache Removal]",
    description=(
        "Deletes the product from SQLite **and** removes it from Redis. "
        "If we didn't remove it from Redis, users could still get 'ghost' data "
        "for up to 60 seconds after deletion."
    ),
)
async def remove_product(product_id: int):
    # Verify product exists
    existing = await get_product_by_id(product_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")

    # Delete from SQLite
    await delete_product(product_id)

    # Delete from Redis cache too — prevents serving deleted data
    key = cache_key(product_id)
    await get_client().delete(key)

    return {
        "message": f"Product {product_id} deleted from DB and cache ✅",
    }


# -----------------------------------------------------------------------
# ROUTE 6: Cache Inspector — see what's currently in Redis
# -----------------------------------------------------------------------
@app.get(
    "/cache/inspect",
    summary="Inspect current Redis cache",
    description=(
        "Shows all product keys currently stored in Redis along with their TTL. "
        "Great for understanding what's cached and when it will expire."
    ),
)
async def inspect_cache():
    rc = get_client()
    keys = await rc.keys("product:*")  # Pattern matching — all product keys

    if not keys:
        return {"message": "Cache is empty", "cached_products": 0, "items": {}}

    cache_contents = {}
    for key in sorted(keys):
        ttl = await rc.ttl(key)         # Seconds remaining
        raw = await rc.get(key)
        cache_contents[key] = {
            "ttl_remaining_seconds": ttl,
            "data": json.loads(raw),
        }

    return {
        "cached_products": len(keys),
        "items": cache_contents,
    }


# -----------------------------------------------------------------------
# ROUTE 7: Flush cache — manually clear all Redis entries
# -----------------------------------------------------------------------
@app.delete(
    "/cache/flush",
    summary="Flush all Redis cache entries",
    description=(
        "Manually deletes all `product:*` keys from Redis. "
        "After this, all subsequent GETs will be cache misses (slow) until "
        "the cache is re-populated."
    ),
)
async def flush_cache():
    rc = get_client()
    keys = await rc.keys("product:*")

    if keys:
        await rc.delete(*keys)  # Unpack list → delete all in one call

    return {
        "message": f"Flushed {len(keys)} cache entries ✅",
        "note": "All next GETs will be cache misses now.",
    }
