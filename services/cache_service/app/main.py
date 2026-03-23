"""Cache Service — Redis-backed caching layer."""

import json
import sys
import os
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.telemetry import init_telemetry
from shared.middleware import add_middleware, get_chaos_config, set_chaos_config, reset_chaos_config
from shared.models import (
    CacheGetRequest,
    CacheSetRequest,
    CacheResponse,
    HealthResponse,
    ChaosConfig,
)
from app.config import settings

logger = structlog.get_logger()
redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    await logger.ainfo("cache_service_started", redis_url=settings.redis_url)
    yield
    await redis_client.aclose()


app = FastAPI(
    title="Cache Service",
    description="Redis-backed caching layer",
    version="1.0.0",
    lifespan=lifespan,
)

tracer, meter = init_telemetry(app, settings.service_name, settings.otel_exporter_otlp_endpoint)
add_middleware(app, settings.service_name, meter)

cache_hits = meter.create_counter("cache_hits_total", description="Total cache hits")
cache_misses = meter.create_counter("cache_misses_total", description="Total cache misses")
cache_latency = meter.create_histogram("cache_operation_duration_seconds", description="Cache operation duration", unit="s")

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health", response_model=HealthResponse)
async def health():
    healthy = False
    try:
        await redis_client.ping()
        healthy = True
    except Exception:
        pass
    return HealthResponse(
        service=settings.service_name,
        status="healthy" if healthy else "unhealthy",
        details={"redis_connected": healthy},
    )


@app.post("/cache/get", response_model=CacheResponse)
async def cache_get(request: CacheGetRequest):
    """Get a value from cache."""
    with tracer.start_as_current_span("cache.get") as span:
        span.set_attribute("cache.key", request.key)

        import time
        start = time.perf_counter()

        value = await redis_client.get(request.key)

        duration = time.perf_counter() - start
        cache_latency.record(duration, {"operation": "get"})

        if value is not None:
            cache_hits.add(1)
            span.set_attribute("cache.hit", True)
            try:
                parsed = json.loads(value)
            except (json.JSONDecodeError, TypeError):
                parsed = value
            return CacheResponse(key=request.key, value=parsed, hit=True)
        else:
            cache_misses.add(1)
            span.set_attribute("cache.hit", False)
            return CacheResponse(key=request.key, value=None, hit=False)


@app.post("/cache/set")
async def cache_set(request: CacheSetRequest):
    """Set a value in cache with optional TTL."""
    with tracer.start_as_current_span("cache.set") as span:
        span.set_attribute("cache.key", request.key)
        span.set_attribute("cache.ttl", request.ttl)

        import time
        start = time.perf_counter()

        serialized = json.dumps(request.value) if not isinstance(request.value, str) else request.value
        await redis_client.setex(request.key, request.ttl, serialized)

        duration = time.perf_counter() - start
        cache_latency.record(duration, {"operation": "set"})

        return {"status": "stored", "key": request.key, "ttl": request.ttl}


@app.delete("/cache/invalidate/{key}")
async def cache_invalidate(key: str):
    """Invalidate a cache entry."""
    with tracer.start_as_current_span("cache.invalidate") as span:
        span.set_attribute("cache.key", key)
        deleted = await redis_client.delete(key)
        if deleted == 0:
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found in cache")
        return {"status": "invalidated", "key": key}


@app.post("/cache/flush")
async def cache_flush():
    """Flush all cache entries."""
    await redis_client.flushdb()
    return {"status": "flushed"}


# --- Chaos endpoints ---
@app.post("/chaos/configure")
async def configure_chaos(config: ChaosConfig):
    set_chaos_config(config.model_dump())
    return {"status": "configured", "config": get_chaos_config()}


@app.post("/chaos/reset")
async def reset_chaos():
    reset_chaos_config()
    return {"status": "reset"}


@app.get("/chaos/status")
async def chaos_status():
    return get_chaos_config()
