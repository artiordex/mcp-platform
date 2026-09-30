#!/usr/bin/env bash
# =============================================================================
# 파일명: doctor.sh
# 경로: scripts/doctor.sh
# 목적: mcp-platform 런타임, 커넥터, 사내 RAG, 클라이언트 설정 상태를 종합 진단함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MCP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"

echo "================================================================="
echo "               MCP Platform 시스템 종합 진단 도구                "
echo "================================================================="

TOTAL_CHECKS=0
PASSED_CHECKS=0
WARNING_CHECKS=0
FAILED_CHECKS=0

report_ok() {
  local msg="$1"
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  PASSED_CHECKS=$((PASSED_CHECKS + 1))
  echo "[OK]   $msg"
}

report_warn() {
  local msg="$1"
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  WARNING_CHECKS=$((WARNING_CHECKS + 1))
  echo "[WARN] $msg"
}

report_fail() {
  local msg="$1"
  TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
  FAILED_CHECKS=$((FAILED_CHECKS + 1))
  echo "[FAIL] $msg"
}

# 1. Node.js 및 빌드 산출물 점검
echo ""
echo "--- 1. Node.js 및 TypeScript 빌드 점검 ---"
if command -v node >/dev/null 2>&1; then
  NODE_VER="$(node -v)"
  report_ok "Node.js 런타임 감지됨: $NODE_VER"
else
  report_fail "Node.js가 설치되어 있지 않음"
fi

if [[ -f "$MCP_ROOT/dist/servers/mcp-gateway.js" && -f "$MCP_ROOT/dist/servers/data-go-gateway.js" ]]; then
  report_ok "TypeScript 빌드 산출물(dist/) 정상 존재함"
else
  report_warn "TypeScript 빌드 산출물이 없거나 불완전함 (npm run build 필요)"
fi

# 2. Python FastMCP 가상환경 점검
echo ""
echo "--- 2. Python FastMCP 커넥터 런타임 점검 ---"
VENV_PYTHON="$MCP_ROOT/.venv/bin/python"
if [[ -x "$VENV_PYTHON" ]]; then
  PY_VER="$("$VENV_PYTHON" -c 'import sys; print(sys.version.split()[0])')"
  report_ok "Python 가상환경 감지됨: Python $PY_VER ($VENV_PYTHON)"
  
  if "$VENV_PYTHON" -c "import mcp, httpx, pydantic" >/dev/null 2>&1; then
    report_ok "핵심 의존성(mcp, httpx, pydantic) 로드 정상임"
  else
    report_fail "핵심 Python 패키지 누락됨"
  fi

  if "$VENV_PYTHON" -c "from mcp_platform.servers import rag, pps, nts, nps, fsc, food_safety, portal_catalog, corporate_intelligence, dart, address, smes, kipris" >/dev/null 2>&1; then
    report_ok "전체 12개 FastMCP 커넥터 모듈 로드 정상임"
  else
    report_fail "일부 FastMCP 커넥터 모듈 로드 실패함"
  fi

  if [[ -x "$MCP_ROOT/scripts/mcp-cli.sh" && -f "$MCP_ROOT/scripts/mcp-cli.py" ]]; then
    report_ok "mcp-cli 관리 CLI 유틸리티 준비 완료됨"
  else
    report_warn "mcp-cli 관리 CLI 유틸리티가 누락되었거나 실행 권한이 없음"
  fi

  CACHE_CHECK="$("$MCP_ROOT/scripts/mcp-cli.sh" cache stats 2>/dev/null || echo '{}')"
  if echo "$CACHE_CHECK" | grep -q '"status": "active"'; then
    report_ok "TieredCache (L1 메모리 + L2 SQLite) 영속 캐시 계층 정상 가동 중"
  else
    report_warn "영속 캐시 계층 진단 응답 이상"
  fi
else
  report_fail "Python 가상환경($VENV_PYTHON)을 찾을 수 없음"
fi

# 3. 사내 RAG-vLLM 서비스 점검
echo ""
echo "--- 3. 사내 RAG-vLLM 서비스 점검 ---"
RAG_URL="${RAG_VLLM_URL:-http://127.0.0.1:11020}"
RAG_STATUS="$(curl -s -m 2 "$RAG_URL/health" || true)"
if [[ -n "$RAG_STATUS" ]] && echo "$RAG_STATUS" | grep -q '"status":"ok"'; then
  report_ok "사내 RAG-vLLM 서비스 정상 가동 중: $RAG_URL/health"
  STATS="$(curl -s -m 2 "$RAG_URL/stats" || true)"
  if [[ -n "$STATS" ]]; then
    TOTAL_DOCS="$(echo "$STATS" | grep -o '"total_documents":[0-9]*' | cut -d: -f2 || echo "0")"
    TOTAL_CHUNKS="$(echo "$STATS" | grep -o '"total_chunks":[0-9]*' | cut -d: -f2 || echo "0")"
    report_ok "RAG 색인 현황: 문서 ${TOTAL_DOCS}건, 청크 ${TOTAL_CHUNKS}건 등록됨"
  fi
elif [[ -n "$RAG_STATUS" ]]; then
  report_warn "사내 RAG-vLLM 응답이 정상이 아님: $RAG_STATUS"
else
  report_warn "사내 RAG-vLLM에 연결할 수 없음 (오프라인 모드로 폴백 동작함): $RAG_URL"
fi

# 4. vLLM LLM 엔드포인트 점검
echo ""
echo "--- 4. vLLM 엔진 점검 ---"
VLLM_URL="http://127.0.0.1:11435"
VLLM_STATUS="$(curl -s -m 2 "$VLLM_URL/health" || true)"
if [[ -n "$VLLM_STATUS" ]]; then
  report_ok "vLLM 로컬 추론 엔진 정상 가동 중: $VLLM_URL"
else
  report_warn "vLLM 로컬 추론 엔진 미응답 (11435 포트 확인 필요)"
fi

# 5. 환경 변수 및 보안 키 점검
echo ""
echo "--- 5. 환경 변수 및 API 키 점검 ---"
ENV_FILE="$MCP_ROOT/.env"
if [[ -f "$ENV_FILE" ]]; then
  report_ok ".env 설정 파일 존재함"
  if grep -q "DATA_GO_API_KEY=" "$ENV_FILE" && ! grep -q "DATA_GO_API_KEY=$" "$ENV_FILE"; then
    report_ok "DATA_GO_API_KEY 설정됨"
  else
    report_warn "DATA_GO_API_KEY가 비어 있거나 미설정됨"
  fi
  if grep -q "FOOD_SAFETY_API_KEY=" "$ENV_FILE" && ! grep -q "FOOD_SAFETY_API_KEY=$" "$ENV_FILE"; then
    report_ok "FOOD_SAFETY_API_KEY 설정됨"
  else
    report_warn "FOOD_SAFETY_API_KEY가 비어 있거나 미설정됨"
  fi
else
  report_warn ".env 파일이 없음 (.env.example 참조하여 생성 권장함)"
fi

# 6. 클라이언트 설정 점검
echo ""
echo "--- 6. 클라이언트 등록 상태 점검 ---"
AGY_CONFIG="$HOME/.gemini/config/mcp_config.json"
if [[ -f "$AGY_CONFIG" ]] && grep -q "mcp-platform" "$AGY_CONFIG"; then
  report_ok "Antigravity(agy) MCP 설정 정상 등록됨: $AGY_CONFIG"
else
  report_warn "Antigravity(agy)에 mcp-platform 미등록됨 (scripts/register-clients.sh 실행 권장함)"
fi

CODEX_CONFIG="$HOME/.codex/config.toml"
if [[ -f "$CODEX_CONFIG" ]] && grep -q "mcp-platform" "$CODEX_CONFIG"; then
  report_ok "Codex CLI MCP 설정 정상 등록됨: $CODEX_CONFIG"
else
  report_warn "Codex CLI에 mcp-platform 미등록됨 (scripts/register-clients.sh 실행 권장함)"
fi

VSCODE_CONFIG="$MCP_ROOT/.vscode/mcp.json"
if [[ -f "$VSCODE_CONFIG" ]]; then
  report_ok "VS Code / Cline 작업 공간 설정 존재함: $VSCODE_CONFIG"
else
  report_warn "VS Code 작업 공간 설정 파일 없음"
fi

# 7. 주석 및 규정 검사
echo ""
echo "--- 7. 전사 주석 및 보안 규정 점검 ---"
EMOJI_COUNT="$(python3 -c "
import os, re
pattern = re.compile(r'[\U00010000-\U0010ffff]')
count = 0
for root, _, files in os.walk('$MCP_ROOT'):
    if any(p in root for p in ['.git', 'node_modules', '.venv', 'dist', '__pycache__']):
        continue
    for f in files:
        if f.endswith(('.ts', '.py', '.sh', '.go', '.json', '.toml', '.md')):
            with open(os.path.join(root, f), 'r', errors='ignore') as fp:
                for line in fp:
                    if pattern.search(line): count += 1
print(count)
")"

if [[ "$EMOJI_COUNT" -eq 0 ]]; then
  report_ok "소스 코드 및 문서 내 이모지 0건 (완전 준수함)"
else
  report_warn "소스 코드 및 문서 내 이모지 발견됨: ${EMOJI_COUNT}건"
fi

echo ""
echo "================================================================="
echo "진단 완료: 총 ${TOTAL_CHECKS}건 중 정상 ${PASSED_CHECKS}건, 경고 ${WARNING_CHECKS}건, 실패 ${FAILED_CHECKS}건"
echo "================================================================="

if [[ "$FAILED_CHECKS" -gt 0 ]]; then
  exit 1
fi
exit 0
