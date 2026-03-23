"""Chaos Controller — orchestrates chaos experiments across services."""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime

import httpx
import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logger = structlog.stdlib.get_logger()

# Service registry
SERVICE_URLS = {
    "gateway": os.getenv("GATEWAY_URL", "http://gateway:8000"),
    "auth": os.getenv("AUTH_URL", "http://auth:8001"),
    "ai-service": os.getenv("AI_SERVICE_URL", "http://ai-service:8002"),
    "db-service": os.getenv("DB_SERVICE_URL", "http://db-service:8003"),
    "cache-service": os.getenv("CACHE_SERVICE_URL", "http://cache-service:8004"),
}

http_client: httpx.AsyncClient | None = None
active_experiments: dict[str, dict] = {}
experiment_tasks: dict[str, asyncio.Task] = {}


# --- Models ---
class ChaosExperiment(BaseModel):
    target: str = Field(..., description="Target service name")
    fault_type: str = Field(..., description="latency, error, or crash")
    probability: float = Field(default=0.5, ge=0, le=1)
    parameters: dict = Field(default_factory=dict)
    duration_seconds: int = Field(default=60, description="Auto-stop after this duration")


class ScenarioRequest(BaseModel):
    duration_seconds: int = Field(default=60)


# --- Pre-defined scenarios ---
SCENARIOS = {
    "cascading-failure": {
        "name": "Cascading Failure",
        "description": "Inject 2s latency into DB service, observe timeout propagation through AI → Gateway",
        "experiments": [
            {"target": "db-service", "fault_type": "latency", "probability": 1.0,
             "parameters": {"latency_ms": 2000}, "duration_seconds": 60},
        ],
    },
    "cache-stampede": {
        "name": "Cache Stampede",
        "description": "Force cache misses, observe DB load spike",
        "experiments": [
            {"target": "cache-service", "fault_type": "error", "probability": 1.0,
             "parameters": {"status_code": 500}, "duration_seconds": 60},
        ],
    },
    "auth-outage": {
        "name": "Auth Outage",
        "description": "Crash Auth service, observe Gateway error rate spike to 100%",
        "experiments": [
            {"target": "auth", "fault_type": "error", "probability": 1.0,
             "parameters": {"status_code": 503}, "duration_seconds": 60},
        ],
    },
    "gradual-degradation": {
        "name": "Gradual Degradation",
        "description": "Slowly increase latency on AI service from 500ms to 5s over 60 seconds",
        "experiments": [
            {"target": "ai-service", "fault_type": "latency", "probability": 0.8,
             "parameters": {"latency_ms": 500}, "duration_seconds": 60},
        ],
    },
    "multi-service-chaos": {
        "name": "Multi-Service Chaos",
        "description": "Inject faults into multiple services simultaneously",
        "experiments": [
            {"target": "db-service", "fault_type": "latency", "probability": 0.5,
             "parameters": {"latency_ms": 1000}, "duration_seconds": 60},
            {"target": "cache-service", "fault_type": "error", "probability": 0.3,
             "parameters": {"status_code": 500}, "duration_seconds": 60},
            {"target": "auth", "fault_type": "latency", "probability": 0.4,
             "parameters": {"latency_ms": 500}, "duration_seconds": 60},
        ],
    },
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client
    http_client = httpx.AsyncClient(timeout=10.0)
    yield
    # Stop all active experiments on shutdown
    for target in list(active_experiments.keys()):
        await _stop_experiment(target)
    await http_client.aclose()


app = FastAPI(
    title="Chaos Controller",
    description="Orchestrates chaos experiments for Project Hades",
    version="1.0.0",
    lifespan=lifespan,
)


async def _apply_chaos(target: str, config: dict) -> dict:
    """Send chaos configuration to a target service."""
    url = SERVICE_URLS.get(target)
    if not url:
        raise HTTPException(status_code=404, detail=f"Unknown target: {target}")

    try:
        resp = await http_client.post(f"{url}/chaos/configure", json=config)
        return resp.json()
    except Exception as e:
        return {"error": str(e), "target": target}


async def _stop_experiment(target: str) -> dict:
    """Stop chaos on a target service."""
    url = SERVICE_URLS.get(target)
    if not url:
        return {"error": f"Unknown target: {target}"}

    # Cancel auto-stop task if running
    if target in experiment_tasks:
        experiment_tasks[target].cancel()
        del experiment_tasks[target]

    active_experiments.pop(target, None)

    try:
        resp = await http_client.post(f"{url}/chaos/reset")
        return resp.json()
    except Exception as e:
        return {"error": str(e), "target": target}


async def _auto_stop(target: str, duration: int):
    """Auto-stop experiment after duration."""
    await asyncio.sleep(duration)
    await _stop_experiment(target)
    logger.info("chaos_auto_stopped", target=target, duration=duration)


# --- Endpoints ---

@app.get("/health")
async def health():
    return {"status": "healthy", "service": "chaos-controller", "timestamp": datetime.utcnow().isoformat()}


@app.post("/chaos/start")
async def start_experiment(experiment: ChaosExperiment):
    """Start a chaos experiment on a target service."""
    config = {
        "enabled": True,
        "fault_type": experiment.fault_type,
        "probability": experiment.probability,
        "parameters": experiment.parameters,
    }

    result = await _apply_chaos(experiment.target, config)

    active_experiments[experiment.target] = {
        **config,
        "started_at": datetime.utcnow().isoformat(),
        "duration_seconds": experiment.duration_seconds,
    }

    # Schedule auto-stop
    task = asyncio.create_task(_auto_stop(experiment.target, experiment.duration_seconds))
    experiment_tasks[experiment.target] = task

    return {
        "status": "started",
        "target": experiment.target,
        "config": config,
        "auto_stop_in": experiment.duration_seconds,
        "result": result,
    }


@app.post("/chaos/stop/{target}")
async def stop_experiment(target: str):
    """Stop chaos on a specific service."""
    result = await _stop_experiment(target)
    return {"status": "stopped", "target": target, "result": result}


@app.post("/chaos/stop-all")
async def stop_all():
    """Stop all active chaos experiments."""
    results = {}
    for target in list(active_experiments.keys()):
        results[target] = await _stop_experiment(target)
    return {"status": "all_stopped", "results": results}


@app.get("/chaos/status")
async def chaos_status():
    """Get status of all active experiments."""
    return {
        "active_experiments": active_experiments,
        "total_active": len(active_experiments),
    }


@app.get("/chaos/scenarios")
async def list_scenarios():
    """List available pre-defined chaos scenarios."""
    return {
        name: {"name": s["name"], "description": s["description"], "experiments": len(s["experiments"])}
        for name, s in SCENARIOS.items()
    }


@app.post("/chaos/scenario/{name}")
async def run_scenario(name: str, request: ScenarioRequest = ScenarioRequest()):
    """Run a pre-defined chaos scenario."""
    scenario = SCENARIOS.get(name)
    if not scenario:
        raise HTTPException(status_code=404, detail=f"Scenario '{name}' not found. Available: {list(SCENARIOS.keys())}")

    results = []
    for exp_config in scenario["experiments"]:
        experiment = ChaosExperiment(
            target=exp_config["target"],
            fault_type=exp_config["fault_type"],
            probability=exp_config["probability"],
            parameters=exp_config["parameters"],
            duration_seconds=request.duration_seconds or exp_config.get("duration_seconds", 60),
        )
        result = await start_experiment(experiment)
        results.append(result)

    return {
        "status": "scenario_started",
        "scenario": scenario["name"],
        "description": scenario["description"],
        "experiments_started": len(results),
        "results": results,
    }
