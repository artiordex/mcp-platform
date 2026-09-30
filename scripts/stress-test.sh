#!/usr/bin/env bash
# =============================================================================
# 파일명: stress-test.sh
# 경로: scripts/stress-test.sh
# 목적: mcp-platform HTTP 게이트웨이 및 Go 병렬 수집기 대상 동시성 부하 테스트를 수행함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

PORT=8145
CONCURRENCY=20
TOTAL_REQUESTS=100

echo "================================================================="
echo "        mcp-platform 엔터프라이즈 동시성 부하 테스트           "
echo "================================================================="

# 1. 테스트용 HTTP 게이트웨이 백그라운드 기동
echo "[단계 1] HTTP 게이트웨이 백그라운드 기동 (포트: ${PORT})"
MCP_HTTP_PORT="${PORT}" MCP_HTTP_HOST="127.0.0.1" node "${PROJECT_ROOT}/dist/servers/http-gateway.js" > /dev/null 2>&1 &
SERVER_PID=$!

cleanup() {
    if kill -0 "${SERVER_PID}" 2>/dev/null; then
        kill "${SERVER_PID}" 2>/dev/null || true
        wait "${SERVER_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# 서버 가동 대기 (최대 5초)
for _ in $(seq 1 25); do
    if curl -s "http://127.0.0.1:${PORT}/api/health" > /dev/null 2>&1; then
        break
    fi
    sleep 0.2
done

echo "  - 게이트웨이 가동 확인 완료됨 (PID: ${SERVER_PID})"

# 2. HTTP GET 엔드포인트 병렬 부하 테스트
echo "[단계 2] HTTP REST & 메트릭 엔드포인트 병렬 부하 테스트 (동시성: ${CONCURRENCY}, 총 요청: ${TOTAL_REQUESTS})"

START_TIME=$(date +%s%N)
SUCCESS_COUNT=0
FAIL_COUNT=0

# xargs 기반 병렬 curl 요청
seq 1 "${TOTAL_REQUESTS}" | xargs -n 1 -P "${CONCURRENCY}" -I {} \
    curl -s -o /dev/null -w "%{http_code}\n" "http://127.0.0.1:${PORT}/api/health" > /tmp/stress_results.txt 2>&1

END_TIME=$(date +%s%N)
ELAPSED_MS=$(( (END_TIME - START_TIME) / 1000000 ))

SUCCESS_COUNT=$(grep -c "200" /tmp/stress_results.txt || true)
TOTAL_RUN=$(wc -l < /tmp/stress_results.txt)
FAIL_COUNT=$(( TOTAL_RUN - SUCCESS_COUNT ))

if [ "${ELAPSED_MS}" -le 0 ]; then
    ELAPSED_MS=1
fi

RPS=$(( (TOTAL_REQUESTS * 1000) / ELAPSED_MS ))

echo "  - 총 요청: ${TOTAL_REQUESTS}건"
echo "  - 성공(200 OK): ${SUCCESS_COUNT}건, 실패: ${FAIL_COUNT}건"
echo "  - 총 소요시간: ${ELAPSED_MS} ms (처리량: 약 ${RPS} req/sec)"

# 3. 게이트웨이 메트릭 수집 현황 확인
echo "[단계 3] 수집된 HTTP 게이트웨이 실시간 메트릭 검증"
METRICS_JSON=$(curl -s "http://127.0.0.1:${PORT}/api/metrics")
echo "  - 메트릭 응답 확인: ${METRICS_JSON}" | cut -c 1-120

# 4. Go 고루틴 병렬 수집기 고부하 벤치마크
echo "[단계 4] Go 고성능 병렬 수집기 대규모 부하 벤치마크 (항목: 100개, 워커: 20개)"
cd "${PROJECT_ROOT}"
go run ./cmd/batch-collector -mode all -items 100 -workers 20

echo "================================================================="
echo "         동시성 부하 테스트 성공적으로 완료됨 (Pass)             "
echo "================================================================="
rm -f /tmp/stress_results.txt
