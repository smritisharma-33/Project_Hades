#!/usr/bin/env python3
"""Background traffic generator for Project Hades.

Sends steady-state traffic to the gateway to populate dashboards with data.
Usage: python3 scripts/generate_traffic.py
"""

import random
import signal
import sys
import time

import httpx

GATEWAY_URL = "http://localhost:8000"
API_KEYS = ["hades-key-001", "hades-key-002", "hades-key-003"]
MODELS = ["default", "fast", "deep"]
INPUTS = [
    "Analyze customer sentiment from review",
    "Classify support ticket priority",
    "Process natural language query for search",
    "Run deep analysis on financial data",
    "Quick text classification needed",
    "Evaluate document complexity score",
    "Summarize meeting transcript",
    "Detect anomalies in log data",
    "Generate embedding for similarity search",
    "Extract key entities from text",
]

running = True


def signal_handler(sig, frame):
    global running
    print("\nStopping traffic generator...")
    running = False


signal.signal(signal.SIGINT, signal_handler)


def main():
    print(f"Generating traffic to {GATEWAY_URL}")
    print("Press Ctrl+C to stop\n")

    client = httpx.Client(timeout=30.0)
    request_count = 0
    error_count = 0
    start_time = time.time()

    while running:
        try:
            payload = {
                "input_data": random.choice(INPUTS),
                "model": random.choice(MODELS),
                "use_cache": random.random() > 0.3,  # 70% cache-enabled
            }
            headers = {"X-API-Key": random.choice(API_KEYS)}

            resp = client.post(f"{GATEWAY_URL}/api/v1/process", json=payload, headers=headers)
            request_count += 1

            if resp.status_code != 200:
                error_count += 1

            elapsed = time.time() - start_time
            rps = request_count / elapsed if elapsed > 0 else 0

            if request_count % 10 == 0:
                print(
                    f"Requests: {request_count} | Errors: {error_count} | "
                    f"RPS: {rps:.1f} | Last: {resp.status_code} ({resp.elapsed.total_seconds()*1000:.0f}ms)"
                )

            # Random delay between requests (1-3 RPS steady state)
            time.sleep(random.uniform(0.3, 1.0))

        except httpx.RequestError as e:
            error_count += 1
            print(f"Request error: {e}")
            time.sleep(2)
        except Exception as e:
            print(f"Unexpected error: {e}")
            time.sleep(2)

    client.close()
    elapsed = time.time() - start_time
    print(f"\nDone. Total: {request_count} requests, {error_count} errors in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
