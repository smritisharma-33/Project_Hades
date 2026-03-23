"""Shared Pydantic models used across services."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# --- Gateway / General ---
class ProcessRequest(BaseModel):
    input_data: str = Field(..., description="Input data to process")
    model: str = Field(default="default", description="AI model to use")
    use_cache: bool = Field(default=True, description="Whether to use cache")


class ProcessResponse(BaseModel):
    request_id: str
    result: str
    model: str
    cached: bool = False
    processing_time_ms: float
    timestamp: str


# --- Auth ---
class AuthValidateRequest(BaseModel):
    token: str | None = None
    api_key: str | None = None


class AuthValidateResponse(BaseModel):
    valid: bool
    user_id: str | None = None
    message: str = ""


# --- Database ---
class DBQueryRequest(BaseModel):
    key: str


class DBStoreRequest(BaseModel):
    key: str
    value: Any


class DBRecord(BaseModel):
    key: str
    value: Any
    created_at: str


# --- Cache ---
class CacheGetRequest(BaseModel):
    key: str


class CacheSetRequest(BaseModel):
    key: str
    value: Any
    ttl: int = Field(default=300, description="TTL in seconds")


class CacheResponse(BaseModel):
    key: str
    value: Any | None = None
    hit: bool = False


# --- Health ---
class HealthResponse(BaseModel):
    status: str = "healthy"
    service: str
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    details: dict[str, Any] = Field(default_factory=dict)


# --- Chaos ---
class ChaosConfig(BaseModel):
    enabled: bool = True
    fault_type: str = Field(..., description="latency, error, or crash")
    probability: float = Field(default=0.5, ge=0, le=1)
    parameters: dict[str, Any] = Field(default_factory=dict)


class ChaosScenario(BaseModel):
    name: str
    description: str
    targets: list[dict[str, Any]]
    duration_seconds: int = 60
