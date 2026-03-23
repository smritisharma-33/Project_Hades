"""Auth Service — authentication and authorization."""

import sys
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from prometheus_client import make_asgi_app

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from shared.telemetry import init_telemetry
from shared.middleware import add_middleware, get_chaos_config, set_chaos_config, reset_chaos_config
from shared.models import (
    AuthValidateRequest,
    AuthValidateResponse,
    HealthResponse,
    ChaosConfig,
)
from app.config import settings

logger = structlog.get_logger()

VALID_API_KEYS = set(settings.valid_api_keys.split(","))
VALID_TOKENS = set(settings.valid_tokens.split(","))


@asynccontextmanager
async def lifespan(app: FastAPI):
    await logger.ainfo("auth_service_started", valid_keys=len(VALID_API_KEYS))
    yield


app = FastAPI(
    title="Auth Service",
    description="Authentication and authorization service",
    version="1.0.0",
    lifespan=lifespan,
)

tracer, meter = init_telemetry(app, settings.service_name, settings.otel_exporter_otlp_endpoint)
add_middleware(app, settings.service_name, meter)

auth_requests_counter = meter.create_counter("auth_requests_total", description="Total auth requests")
auth_failures_counter = meter.create_counter("auth_failures_total", description="Total auth failures")

metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)


@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(service=settings.service_name, status="healthy")


@app.post("/auth/validate", response_model=AuthValidateResponse)
async def validate(request: AuthValidateRequest):
    """Validate an API key or bearer token."""
    with tracer.start_as_current_span("auth.validate") as span:
        auth_requests_counter.add(1)

        # Check API key
        if request.api_key and request.api_key in VALID_API_KEYS:
            span.set_attribute("auth.method", "api_key")
            span.set_attribute("auth.valid", True)
            return AuthValidateResponse(valid=True, user_id="user-apikey", message="API key valid")

        # Check bearer token
        if request.token and request.token in VALID_TOKENS:
            span.set_attribute("auth.method", "token")
            span.set_attribute("auth.valid", True)
            return AuthValidateResponse(valid=True, user_id="user-token", message="Token valid")

        # Allow requests with no credentials in demo mode
        if not request.api_key and not request.token:
            span.set_attribute("auth.method", "none")
            span.set_attribute("auth.valid", True)
            return AuthValidateResponse(valid=True, user_id="anonymous", message="Demo mode — no auth required")

        span.set_attribute("auth.valid", False)
        auth_failures_counter.add(1)
        await logger.awarn("auth_failed", api_key=bool(request.api_key), token=bool(request.token))
        return AuthValidateResponse(valid=False, message="Invalid credentials")


@app.post("/auth/token")
async def issue_token():
    """Issue a demo token for testing."""
    return {"token": "hades-token-001", "type": "bearer", "expires_in": 3600}


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
