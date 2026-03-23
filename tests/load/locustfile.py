"""Locust load tests for Project Hades."""

import random
from locust import HttpUser, between, task


class HadesUser(HttpUser):
    wait_time = between(0.5, 2.0)
    host = "http://localhost:8000"

    def on_start(self):
        """Called when a simulated user starts."""
        self.api_keys = ["hades-key-001", "hades-key-002", "hades-key-003"]
        self.models = ["default", "fast", "deep"]
        self.sample_inputs = [
            "Analyze this text for sentiment",
            "Classify the following document",
            "Process natural language query",
            "Run deep analysis on input data",
            "Quick classification needed",
            "Evaluate text complexity",
            "Summarize the key points",
            "Detect language and translate",
        ]

    @task(10)
    def process_request(self):
        """Main processing endpoint — highest weight."""
        self.client.post(
            "/api/v1/process",
            json={
                "input_data": random.choice(self.sample_inputs),
                "model": random.choice(self.models),
                "use_cache": True,
            },
            headers={"X-API-Key": random.choice(self.api_keys)},
        )

    @task(3)
    def process_no_cache(self):
        """Process without cache — forces DB + inference every time."""
        self.client.post(
            "/api/v1/process",
            json={
                "input_data": f"Unique input {random.randint(1, 100000)}",
                "model": random.choice(self.models),
                "use_cache": False,
            },
            headers={"X-API-Key": random.choice(self.api_keys)},
        )

    @task(2)
    def health_check(self):
        """Health check endpoint."""
        self.client.get("/health")

    @task(1)
    def readiness_check(self):
        """Readiness check — includes downstream service checks."""
        self.client.get("/ready")
