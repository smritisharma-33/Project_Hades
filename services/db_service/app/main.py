"""Database Service — SQLite-backed key-value store."""

import json
import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime

import aiosqlite
import structlog
from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.telemetry import init_telemetry
from shared.middleware import add_middleware, get_chaos_config, set_chaos_config, reset_chaos_config
from shared.models import (
    DBQueryRequest,
    DBStoreRequest,
    DBRecord,
    HealthResponse,
    ChaosConfig,
)
from app.config import settings

logger = structlog.get_logger()
db: aiosqlite.Connection | None = None

SEED_DATA = {
    "model-config-default": {"type": "text-classification", "version": "1.0", "max_tokens": 512},
    "model-config-fast": {"type": "sentiment", "version": "0.9", "max_tokens": 128},
    "model-config-deep": {"type": "deep-analysis", "version": "2.1", "max_tokens": 2048},
    "sample-input-1": {"text": "Hello, World!", "language": "en"},
    "sample-input-2": {"text": "Project Hades is an SRE demo platform", "language": "en"},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db
    os.makedirs(os.path.dirname(settings.db_path), exist_ok=True)
    db = await aiosqlite.connect(settings.db_path)
    await db.execute(
        """CREATE TABLE IF NOT EXISTS records (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    # Seed data
    for key, value in SEED_DATA.items():
        await db.execute(
            "INSERT OR IGNORE INTO records (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), datetime.utcnow().isoformat()),
        )
    await db.commit()
    await logger.ainfo("db_service_started", db_path=settings.db_path, seeded=len(SEED_DATA))
    yield
    await db.close()


app = FastAPI(
    title="Database Service",
    description="SQLite-backed key-value store",
    version="1.0.0",
    lifespan=lifespan,
)

tracer, meter = init_telemetry(app, settings.service_name, settings.otel_exporter_otlp_endpoint)
add_middleware(app, settings.service_name, meter)

db_queries_counter = meter.create_counter("db_queries_total", description="Total DB queries")
db_latency_histogram = meter.create_histogram("db_query_duration_seconds", description="DB query duration", unit="s")

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health", response_model=HealthResponse)
async def health():
    healthy = db is not None
    try:
        await db.execute("SELECT 1")
        healthy = True
    except Exception:
        healthy = False
    return HealthResponse(
        service=settings.service_name,
        status="healthy" if healthy else "unhealthy",
        details={"db_connected": healthy},
    )


@app.post("/db/query")
async def query(request: DBQueryRequest):
    """Query a record by key."""
    with tracer.start_as_current_span("db.query") as span:
        span.set_attribute("db.key", request.key)
        db_queries_counter.add(1, {"operation": "query"})

        import time
        start = time.perf_counter()

        async with db.execute(
            "SELECT key, value, created_at FROM records WHERE key = ?", (request.key,)
        ) as cursor:
            row = await cursor.fetchone()

        duration = time.perf_counter() - start
        db_latency_histogram.record(duration, {"operation": "query"})

        if row is None:
            raise HTTPException(status_code=404, detail=f"Key '{request.key}' not found")

        return DBRecord(key=row[0], value=json.loads(row[1]), created_at=row[2])


@app.post("/db/store")
async def store(request: DBStoreRequest):
    """Store a record."""
    with tracer.start_as_current_span("db.store") as span:
        span.set_attribute("db.key", request.key)
        db_queries_counter.add(1, {"operation": "store"})

        import time
        start = time.perf_counter()

        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT OR REPLACE INTO records (key, value, created_at) VALUES (?, ?, ?)",
            (request.key, json.dumps(request.value), now),
        )
        await db.commit()

        duration = time.perf_counter() - start
        db_latency_histogram.record(duration, {"operation": "store"})

        return DBRecord(key=request.key, value=request.value, created_at=now)


@app.delete("/db/delete/{key}")
async def delete(key: str):
    """Delete a record by key."""
    with tracer.start_as_current_span("db.delete") as span:
        span.set_attribute("db.key", key)
        db_queries_counter.add(1, {"operation": "delete"})

        result = await db.execute("DELETE FROM records WHERE key = ?", (key,))
        await db.commit()

        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"Key '{key}' not found")
        return {"status": "deleted", "key": key}


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
