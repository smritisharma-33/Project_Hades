#!/bin/bash
# Chaos Engineering Demo for Project Hades
# This script runs through several chaos scenarios with pauses for observation.

set -e

CHAOS_URL="http://localhost:8005"
GATEWAY_URL="http://localhost:8000"
BLUE='\033[0;34m'
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║   Project Hades — Chaos Engineering Demo     ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════╝${NC}"
echo ""

# Verify services are up
echo -e "${YELLOW}[1/6] Verifying services are healthy...${NC}"
curl -sf "$GATEWAY_URL/health" > /dev/null && echo -e "${GREEN}  ✓ Gateway healthy${NC}" || echo -e "${RED}  ✗ Gateway unhealthy${NC}"
curl -sf "$CHAOS_URL/health" > /dev/null && echo -e "${GREEN}  ✓ Chaos Controller healthy${NC}" || echo -e "${RED}  ✗ Chaos Controller unhealthy${NC}"
echo ""

# Baseline test
echo -e "${YELLOW}[2/6] Running baseline test (normal operation)...${NC}"
for i in {1..5}; do
    RESP=$(curl -sf -w "%{http_code}:%{time_total}" -o /dev/null -X POST "$GATEWAY_URL/api/v1/process" \
        -H "Content-Type: application/json" \
        -H "X-API-Key: hades-key-001" \
        -d '{"input_data": "Baseline test '$i'", "model": "fast"}')
    echo -e "  Request $i: HTTP ${RESP%%:*} in ${RESP##*:}s"
done
echo ""

# Scenario 1: Cascading Failure
echo -e "${RED}[3/6] Starting chaos: Cascading Failure (30s)${NC}"
echo -e "  Injecting 2s latency into DB service..."
curl -sf -X POST "$CHAOS_URL/chaos/scenario/cascading-failure" \
    -H "Content-Type: application/json" \
    -d '{"duration_seconds": 30}' | python3 -m json.tool
echo ""
echo -e "${YELLOW}  Observe in Grafana: latency spike propagating through services${NC}"
echo -e "${YELLOW}  Sending requests during chaos...${NC}"
for i in {1..5}; do
    RESP=$(curl -sf -w "%{http_code}:%{time_total}" -o /dev/null -X POST "$GATEWAY_URL/api/v1/process" \
        -H "Content-Type: application/json" \
        -d '{"input_data": "Chaos test '$i'", "model": "default"}' 2>/dev/null || echo "500:timeout")
    echo -e "  Request $i: HTTP ${RESP%%:*} in ${RESP##*:}s"
done
echo ""

# Wait and stop
echo -e "${YELLOW}  Waiting 10s for observation...${NC}"
sleep 10
curl -sf -X POST "$CHAOS_URL/chaos/stop-all" > /dev/null
echo -e "${GREEN}  ✓ Chaos stopped${NC}"
echo ""

# Scenario 2: Auth Outage
echo -e "${RED}[4/6] Starting chaos: Auth Outage (20s)${NC}"
curl -sf -X POST "$CHAOS_URL/chaos/scenario/auth-outage" \
    -H "Content-Type: application/json" \
    -d '{"duration_seconds": 20}' > /dev/null
echo -e "  Auth service returning 503 for all requests..."
for i in {1..3}; do
    HTTP_CODE=$(curl -sf -w "%{http_code}" -o /dev/null -X POST "$GATEWAY_URL/api/v1/process" \
        -H "Content-Type: application/json" \
        -d '{"input_data": "Auth down test", "model": "fast"}' 2>/dev/null || echo "error")
    echo -e "  Request $i: HTTP $HTTP_CODE (expected: 401 or 503)"
done
sleep 5
curl -sf -X POST "$CHAOS_URL/chaos/stop-all" > /dev/null
echo -e "${GREEN}  ✓ Auth outage stopped${NC}"
echo ""

# Recovery test
echo -e "${YELLOW}[5/6] Recovery test — verifying services recovered...${NC}"
sleep 3
for i in {1..3}; do
    RESP=$(curl -sf -w "%{http_code}:%{time_total}" -o /dev/null -X POST "$GATEWAY_URL/api/v1/process" \
        -H "Content-Type: application/json" \
        -d '{"input_data": "Recovery test '$i'", "model": "fast"}')
    echo -e "  Request $i: HTTP ${RESP%%:*} in ${RESP##*:}s"
done
echo ""

# Summary
echo -e "${BLUE}[6/6] Demo complete!${NC}"
echo -e "${YELLOW}  Open Grafana at http://localhost:3000 (admin/hades) to review:${NC}"
echo -e "  • SLI/SLO Dashboard — check error budget impact"
echo -e "  • Service Overview — see latency spikes and error rates"
echo -e "  • Traces in Tempo — follow request propagation during chaos"
echo ""
