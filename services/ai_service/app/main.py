"""AI Service — simulated ML inference with cache and DB integration."""

import asyncio
import hashlib
import random
import sys
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import structlog
from fastapi import FastAPI, HTTPException
from prometheus_client import make_asgi_app

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.telemetry import init_telemetry
from shared.middleware import add_middleware, get_chaos_config, set_chaos_config, reset_chaos_config
from shared.models import (
    ProcessRequest,
    ProcessResponse,
    HealthResponse,
    ChaosConfig,
)
from app.config import settings

logger = structlog.get_logger()
http_client: httpx.AsyncClient | None = None

MODELS = {
    "default": {"name": "hades-text-v1", "avg_latency_ms": 100},
    "fast": {"name": "hades-fast-v1", "avg_latency_ms": 50},
    "deep": {"name": "hades-deep-v2", "avg_latency_ms": 200},
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=30.0)
    await logger.ainfo("ai_service_started", models=list(MODELS.keys()))
    yield
    await http_client.aclose()


app = FastAPI(
    title="AI Service",
    description="Simulated ML inference service",
    version="1.0.0",
    lifespan=lifespan,
)

tracer, meter = init_telemetry(app, settings.service_name, settings.otel_exporter_otlp_endpoint)
add_middleware(app, settings.service_name, meter)

inference_latency = meter.create_histogram("ai_inference_duration_seconds", description="AI inference duration", unit="s")
inference_counter = meter.create_counter("ai_inferences_total", description="Total AI inferences")
cache_hit_counter = meter.create_counter("ai_cache_hits_total", description="Cache hits for AI requests")

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


def _generate_cache_key(input_data: str, model: str) -> str:
    return f"ai:{model}:{hashlib.md5(input_data.encode()).hexdigest()}"


async def _simulate_inference(input_data: str, model_name: str) -> str:
    """Simulate AI model inference with variable latency."""
    model = MODELS.get(model_name, MODELS["default"])
    base_latency = model["avg_latency_ms"]
    # Add jitter: ±30%
    latency_ms = random.uniform(base_latency * 0.7, base_latency * 1.3)
    await asyncio.sleep(latency_ms / 1000)

    # Simulated result
    words = input_data.split()
    result = {
        "model": model["name"],
        "classification": random.choice(["positive", "negative", "neutral"]),
        "confidence": round(random.uniform(0.75, 0.99), 4),
        "tokens_processed": len(words),
        "summary": f"Processed {len(words)} tokens with {model['name']}",
    }
    return str(result)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(service=settings.service_name, status="healthy")


@app.get("/ai/models")
async def list_models():
    """List available AI models."""
    return {"models": MODELS}


@app.post("/ai/process", response_model=ProcessResponse)
async def process(request: ProcessRequest):
    """Process input through simulated AI inference pipeline."""
    request_id = str(uuid.uuid4())
    start_time = time.perf_counter()

    with tracer.start_as_current_span("ai.process") as span:
        span.set_attribute("ai.model", request.model)
        span.set_attribute("ai.input_size", len(request.input_data))

        cache_key = _generate_cache_key(request.input_data, request.model)
        cached = False
        result = None

        # Step 1: Check cache
        if request.use_cache:
            with tracer.start_as_current_span("ai.cache_lookup"):
                try:
                    cache_resp = await http_client.post(
                        f"{settings.cache_service_url}/cache/get",
                        json={"key": cache_key},
                    )
                    if cache_resp.status_code == 200:
                        data = cache_resp.json()
                        if data.get("hit"):
                            result = data["value"]
                            cached = True
                            cache_hit_counter.add(1)
                            span.set_attribute("ai.cache_hit", True)
                except Exception as e:
                    await logger.awarn("cache_lookup_failed", error=str(e))

        # Step 2: Query DB for model config (if not cached)
        if not cached:
            with tracer.start_as_current_span("ai.db_lookup"):
                try:
                    db_resp = await http_client.post(
                        f"{settings.db_service_url}/db/query",
                        json={"key": f"model-config-{request.model}"},
                    )
                    if db_resp.status_code == 200:
                        span.set_attribute("ai.db_config_found", True)
                except Exception as e:
                    await logger.awarn("db_lookup_failed", error=str(e))

            # Step 3: Run inference
            with tracer.start_as_current_span("ai.inference"):
                inference_counter.add(1, {"model": request.model})
                inference_start = time.perf_counter()
                result = await _simulate_inference(request.input_data, request.model)
                inference_duration = time.perf_counter() - inference_start
                inference_latency.record(inference_duration, {"model": request.model})

            # Step 4: Store in cache
            if request.use_cache:
                with tracer.start_as_current_span("ai.cache_store"):
                    try:
                        await http_client.post(
                            f"{settings.cache_service_url}/cache/set",
                            json={"key": cache_key, "value": result, "ttl": 300},
                        )
                    except Exception as e:
                        await logger.awarn("cache_store_failed", error=str(e))

            # Step 5: Store result in DB
            with tracer.start_as_current_span("ai.db_store"):
                try:
                    await http_client.post(
                        f"{settings.db_service_url}/db/store",
                        json={"key": f"result-{request_id}", "value": result},
                    )
                except Exception as e:
                    await logger.awarn("db_store_failed", error=str(e))

        total_time = time.perf_counter() - start_time
        span.set_attribute("ai.cached", cached)
        span.set_attribute("ai.total_time_ms", round(total_time * 1000, 2))

        return ProcessResponse(
            request_id=request_id,
            result=result,
            model=request.model,
            cached=cached,
            processing_time_ms=round(total_time * 1000, 2),
            timestamp=datetime.utcnow().isoformat(),
        )


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
