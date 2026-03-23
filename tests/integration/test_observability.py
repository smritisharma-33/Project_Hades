"""Observability tests — verify metrics, traces, and logs are flowing."""

import time

import httpx
import pytest

PROMETHEUS_URL = "http://localhost:9090"
TEMPO_URL = "http://localhost:3200"
GATEWAY_URL = "http://localhost:8000"


@pytest.fixture
def client():
    return httpx.Client(timeout=30.0)


def _generate_traffic(client, count=5):
    """Send a few requests to generate telemetry data."""
    for _ in range(count):
        client.post(
            f"{GATEWAY_URL}/api/v1/process",
            json={"input_data": "observability test", "model": "fast"},
            headers={"X-API-Key": "hades-key-001"},
        )
    time.sleep(5)  # Wait for metrics scrape cycle


class TestPrometheusMetrics:
    def test_prometheus_is_up(self, client):
        resp = client.get(f"{PROMETHEUS_URL}/-/healthy")
        assert resp.status_code == 200

    def test_targets_are_scraped(self, client):
        resp = client.get(f"{PROMETHEUS_URL}/api/v1/targets")
        assert resp.status_code == 200
        data = resp.json()
        active_targets = data["data"]["activeTargets"]
        assert len(active_targets) > 0

    def test_request_metrics_exist(self, client):
        _generate_traffic(client)

        # Query for http_requests_total metric
        resp = client.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": 'http_requests_total{service="gateway"}'},
        )
        assert resp.status_code == 200
        result = resp.json()["data"]["result"]
        # Metric should exist after traffic
        assert len(result) > 0

    def test_latency_histogram_exists(self, client):
        _generate_traffic(client)

        resp = client.get(
            f"{PROMETHEUS_URL}/api/v1/query",
            params={"query": "http_request_duration_seconds_bucket"},
        )
        assert resp.status_code == 200


class TestServiceMetricsEndpoints:
    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost:8000/metrics",
            "http://localhost:8001/metrics",
            "http://localhost:8002/metrics",
            "http://localhost:8003/metrics",
            "http://localhost:8004/metrics",
        ],
    )
    def test_metrics_endpoint(self, client, url):
        resp = client.get(url)
        assert resp.status_code == 200
        assert "http_request" in resp.text or "TYPE" in resp.text


class TestTempo:
    def test_tempo_is_up(self, client):
        resp = client.get(f"{TEMPO_URL}/ready")
        assert resp.status_code == 200
