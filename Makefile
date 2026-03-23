.PHONY: up down build logs status health test chaos-start chaos-stop traffic clean

# ============== Core ==============

up: ## Start all services
	docker compose up -d --build

down: ## Stop all services
	docker compose down

build: ## Build all service images
	docker compose build

restart: ## Restart all services
	docker compose restart

logs: ## Tail logs from all services
	docker compose logs -f

logs-app: ## Tail logs from application services only
	docker compose logs -f gateway auth ai-service db-service cache-service

status: ## Show container status
	docker compose ps

# ============== Health ==============

health: ## Check health of all services
	@echo "=== Gateway ===" && curl -s http://localhost:8000/health | python3 -m json.tool
	@echo "\n=== Auth ===" && curl -s http://localhost:8001/health | python3 -m json.tool
	@echo "\n=== AI Service ===" && curl -s http://localhost:8002/health | python3 -m json.tool
	@echo "\n=== DB Service ===" && curl -s http://localhost:8003/health | python3 -m json.tool
	@echo "\n=== Cache Service ===" && curl -s http://localhost:8004/health | python3 -m json.tool

ready: ## Check readiness of gateway (includes downstream checks)
	curl -s http://localhost:8000/ready | python3 -m json.tool

# ============== Testing ==============

test: ## Run a test request through the platform
	@echo "=== Sending test request ===" && \
	curl -s -X POST http://localhost:8000/api/v1/process \
		-H "Content-Type: application/json" \
		-H "X-API-Key: hades-key-001" \
		-d '{"input_data": "Hello from Project Hades!", "model": "default", "use_cache": true}' | \
	python3 -m json.tool

test-cached: ## Send same request twice to test caching
	@echo "=== First request (cache miss) ===" && \
	curl -s -X POST http://localhost:8000/api/v1/process \
		-H "Content-Type: application/json" \
		-H "X-API-Key: hades-key-001" \
		-d '{"input_data": "Cache test", "model": "fast"}' | python3 -m json.tool
	@echo "\n=== Second request (cache hit) ===" && \
	curl -s -X POST http://localhost:8000/api/v1/process \
		-H "Content-Type: application/json" \
		-H "X-API-Key: hades-key-001" \
		-d '{"input_data": "Cache test", "model": "fast"}' | python3 -m json.tool

test-integration: ## Run integration tests
	cd tests && python3 -m pytest integration/ -v

test-load: ## Run load tests with Locust (headless, 30s)
	cd tests/load && locust -f locustfile.py --headless -u 10 -r 2 --run-time 30s --host http://localhost:8000

# ============== Chaos ==============

chaos-start: ## Start a chaos experiment (pass SCENARIO=name)
	curl -s -X POST http://localhost:8005/chaos/scenario/$${SCENARIO:-cascading-failure} | python3 -m json.tool

chaos-stop: ## Stop all chaos experiments
	curl -s -X POST http://localhost:8005/chaos/stop-all | python3 -m json.tool

chaos-status: ## Check chaos status
	curl -s http://localhost:8005/chaos/status | python3 -m json.tool

chaos-scenarios: ## List available chaos scenarios
	curl -s http://localhost:8005/chaos/scenarios | python3 -m json.tool

# ============== Traffic ==============

traffic: ## Generate background traffic (Ctrl+C to stop)
	python3 scripts/generate_traffic.py

# ============== Observability ==============

open-grafana: ## Open Grafana in browser
	open http://localhost:3000

open-prometheus: ## Open Prometheus in browser
	open http://localhost:9090

# ============== Cleanup ==============

clean: ## Remove all containers, volumes, and images
	docker compose down -v --rmi local
	rm -rf services/db_service/data

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

.DEFAULT_GOAL := help
