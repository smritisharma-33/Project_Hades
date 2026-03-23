"""Common FastAPI middleware for request timing, error handling, and chaos injection."""

import asyncio
import random
import time
import uuid
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = structlog.get_logger()

# Per-service chaos state — modified via /chaos/configure endpoint
_chaos_config: dict[str, Any] = {
    "enabled": False,
    "fault_type": None,  # "latency", "error", "crash"
    "probability": 0.0,
    "parameters": {},
}


def get_chaos_config() -> dict[str, Any]:
    return _chaos_config


def set_chaos_config(config: dict[str, Any]) -> None:
    _chaos_config.update(config)


def reset_chaos_config() -> None:
    _chaos_config.update(
        {"enabled": False, "fault_type": None, "probability": 0.0, "parameters": {}}
    )


class RequestMiddleware(BaseHTTPMiddleware):
    """Adds request ID, timing, structured logging, and chaos injection."""

    def __init__(self, app, service_name: str, meter=None):
        super().__init__(app)
        self.service_name = service_name
        self.request_counter = None
        self.latency_histogram = None
        self.error_counter = None
        if meter:
            self.request_counter = meter.create_counter(
                "http_requests_total",
                description="Total HTTP requests",
            )
            self.latency_histogram = meter.create_histogram(
                "http_request_duration_seconds",
                description="HTTP request duration in seconds",
                unit="s",
            )
            self.error_counter = meter.create_counter(
                "http_errors_total",
                description="Total HTTP errors",
            )

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        start_time = time.perf_counter()

        labels = {
            "service": self.service_name,
            "method": request.method,
            "path": request.url.path,
        }

        # --- Chaos injection ---
        if _chaos_config["enabled"] and random.random() < _chaos_config["probability"]:
            fault = _chaos_config["fault_type"]
            if fault == "latency":
                delay = _chaos_config["parameters"].get("latency_ms", 2000) / 1000
                await asyncio.sleep(delay)
            elif fault == "error":
                status_code = _chaos_config["parameters"].get("status_code", 500)
                if self.error_counter:
                    self.error_counter.add(1, {**labels, "status_code": str(status_code)})
                return Response(
                    content='{"error": "chaos fault injected"}',
                    status_code=status_code,
                    media_type="application/json",
                )
            elif fault == "crash":
                raise RuntimeError("Chaos crash fault injected")

        try:
            response = await call_next(request)
            duration = time.perf_counter() - start_time

            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration:.4f}"

            if self.request_counter:
                self.request_counter.add(
                    1, {**labels, "status_code": str(response.status_code)}
                )
            if self.latency_histogram:
                self.latency_histogram.record(duration, labels)
            if response.status_code >= 400 and self.error_counter:
                self.error_counter.add(
                    1, {**labels, "status_code": str(response.status_code)}
                )

            await logger.ainfo(
                "request_completed",
                service=self.service_name,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=round(duration * 1000, 2),
            )
            return response

        except Exception as exc:
            duration = time.perf_counter() - start_time
            if self.error_counter:
                self.error_counter.add(1, {**labels, "status_code": "500"})
            await logger.aerror(
                "request_failed",
                service=self.service_name,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error=str(exc),
                duration_ms=round(duration * 1000, 2),
            )
            return Response(
                content=f'{{"error": "{str(exc)}"}}',
                status_code=500,
                media_type="application/json",
            )


def add_middleware(app: FastAPI, service_name: str, meter=None) -> None:
    """Convenience function to attach all common middleware to a FastAPI app."""
    app.add_middleware(RequestMiddleware, service_name=service_name, meter=meter)
