"""Gateway Service — entry point for all client requests."""

import sys
import os
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request
from prometheus_client import make_asgi_app

# Add project root to path for shared imports
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=30.0)
    yield
    await http_client.aclose()


app = FastAPI(
    title="Gateway Service",
    description="Entry point for AI Service Reliability Platform",
    version="1.0.0",
    lifespan=lifespan,
)

tracer, meter = init_telemetry(app, settings.service_name, settings.otel_exporter_otlp_endpoint)
add_middleware(app, settings.service_name, meter)

# Mount Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(service=settings.service_name, status="healthy")


@app.get("/ready")
async def ready():
    """Readiness check — verifies downstream services are reachable."""
    checks = {}
    for name, url in [
        ("auth", settings.auth_service_url),
        ("ai_service", settings.ai_service_url),
    ]:
        try:
            resp = await http_client.get(f"{url}/health", timeout=5.0)
            checks[name] = "healthy" if resp.status_code == 200 else "unhealthy"
        except Exception:
            checks[name] = "unreachable"

    all_healthy = all(v == "healthy" for v in checks.values())
    return HealthResponse(
        service=settings.service_name,
        status="ready" if all_healthy else "degraded",
        details=checks,
    )


@app.post("/api/v1/process", response_model=ProcessResponse)
async def process(request: ProcessRequest, req: Request):
    """Main processing endpoint. Forwards to Auth, then AI Service."""
    request_id = getattr(req.state, "request_id", "unknown")

    with tracer.start_as_current_span("gateway.process") as span:
        span.set_attribute("request_id", request_id)
        span.set_attribute("model", request.model)

        # Step 1: Authenticate
        with tracer.start_as_current_span("gateway.auth_call"):
            auth_headers = {
                "Authorization": req.headers.get("Authorization", ""),
                "X-API-Key": req.headers.get("X-API-Key", ""),
                "X-Request-ID": request_id,
            }
            try:
                auth_resp = await http_client.post(
                    f"{settings.auth_service_url}/auth/validate",
                    json={"token": auth_headers["Authorization"].replace("Bearer ", ""),
                          "api_key": auth_headers["X-API-Key"]},
                    headers={"X-Request-ID": request_id},
                )
            except httpx.RequestError as e:
                await logger.aerror("auth_service_unreachable", error=str(e))
                raise HTTPException(status_code=503, detail="Auth service unavailable")

            if auth_resp.status_code != 200 or not auth_resp.json().get("valid"):
                raise HTTPException(status_code=401, detail="Authentication failed")

        # Step 2: Forward to AI Service
        with tracer.start_as_current_span("gateway.ai_call"):
            try:
                ai_resp = await http_client.post(
                    f"{settings.ai_service_url}/ai/process",
                    json=request.model_dump(),
                    headers={"X-Request-ID": request_id},
                )
            except httpx.RequestError as e:
                await logger.aerror("ai_service_unreachable", error=str(e))
                raise HTTPException(status_code=503, detail="AI service unavailable")

            if ai_resp.status_code != 200:
                raise HTTPException(
                    status_code=ai_resp.status_code,
                    detail=ai_resp.json().get("detail", "AI processing failed"),
                )

        return ai_resp.json()


# --- Chaos endpoints (internal) ---
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
