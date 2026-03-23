"""Integration tests for the full request flow through the platform."""

import httpx
import pytest

BASE_URL = "http://localhost:8000"
CHAOS_URL = "http://localhost:8005"


@pytest.fixture
def client():
    return httpx.Client(timeout=30.0)


class TestHealthChecks:
    """Verify all services are healthy."""

    @pytest.mark.parametrize(
        "service,port",
        [
            ("gateway", 8000),
            ("auth", 8001),
            ("ai-service", 8002),
            ("db-service", 8003),
            ("cache-service", 8004),
            ("chaos-controller", 8005),
        ],
    )
    def test_service_health(self, client, service, port):
        resp = client.get(f"http://localhost:{port}/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("healthy", "ready")

    def test_gateway_readiness(self, client):
        resp = client.get(f"{BASE_URL}/ready")
        assert resp.status_code == 200


class TestEndToEndFlow:
    """Test the full request flow: Gateway → Auth → AI → DB/Cache."""

    def test_process_request_success(self, client):
        resp = client.post(
            f"{BASE_URL}/api/v1/process",
            json={"input_data": "Test input for integration", "model": "default", "use_cache": True},
            headers={"X-API-Key": "hades-key-001"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "result" in data
        assert "request_id" in data
        assert data["model"] == "default"
        assert "processing_time_ms" in data

    def test_process_request_with_auth_token(self, client):
        resp = client.post(
            f"{BASE_URL}/api/v1/process",
            json={"input_data": "Token auth test", "model": "fast"},
            headers={"Authorization": "Bearer hades-token-001"},
        )
        assert resp.status_code == 200

    def test_process_request_no_auth_demo_mode(self, client):
        """Demo mode allows requests without auth."""
        resp = client.post(
            f"{BASE_URL}/api/v1/process",
            json={"input_data": "No auth test", "model": "default"},
        )
        assert resp.status_code == 200

    def test_cache_hit_on_second_request(self, client):
        payload = {"input_data": "Cache integration test", "model": "fast", "use_cache": True}

        # First request — cache miss
        resp1 = client.post(f"{BASE_URL}/api/v1/process", json=payload)
        assert resp1.status_code == 200
        data1 = resp1.json()

        # Second request — should be faster (cache hit)
        resp2 = client.post(f"{BASE_URL}/api/v1/process", json=payload)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["cached"] is True
        assert data2["processing_time_ms"] < data1["processing_time_ms"]

    def test_different_models(self, client):
        for model in ["default", "fast", "deep"]:
            resp = client.post(
                f"{BASE_URL}/api/v1/process",
                json={"input_data": f"Model test: {model}", "model": model},
            )
            assert resp.status_code == 200
            assert resp.json()["model"] == model

    def test_response_has_request_id_header(self, client):
        resp = client.post(
            f"{BASE_URL}/api/v1/process",
            json={"input_data": "Header test"},
        )
        assert resp.status_code == 200
        assert "x-request-id" in resp.headers
        assert "x-response-time" in resp.headers


class TestObservability:
    """Verify observability endpoints are working."""

    @pytest.mark.parametrize("port", [8000, 8001, 8002, 8003, 8004])
    def test_metrics_endpoint(self, client, port):
        resp = client.get(f"http://localhost:{port}/metrics")
        assert resp.status_code == 200
        assert "http_requests" in resp.text or "HELP" in resp.text

    def test_prometheus_targets(self, client):
        resp = client.get("http://localhost:9090/api/v1/targets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"

    def test_grafana_health(self, client):
        resp = client.get("http://localhost:3000/api/health")
        assert resp.status_code == 200


class TestChaosEngineering:
    """Test chaos engineering capabilities."""

    def test_list_scenarios(self, client):
        resp = client.get(f"{CHAOS_URL}/chaos/scenarios")
        assert resp.status_code == 200
        scenarios = resp.json()
        assert "cascading-failure" in scenarios
        assert "auth-outage" in scenarios

    def test_start_and_stop_experiment(self, client):
        # Start
        resp = client.post(
            f"{CHAOS_URL}/chaos/start",
            json={"target": "db-service", "fault_type": "latency",
                  "probability": 0.5, "parameters": {"latency_ms": 100}, "duration_seconds": 10},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "started"

        # Check status
        resp = client.get(f"{CHAOS_URL}/chaos/status")
        assert resp.status_code == 200
        assert resp.json()["total_active"] > 0

        # Stop
        resp = client.post(f"{CHAOS_URL}/chaos/stop/db-service")
        assert resp.status_code == 200

    def test_stop_all(self, client):
        resp = client.post(f"{CHAOS_URL}/chaos/stop-all")
        assert resp.status_code == 200
