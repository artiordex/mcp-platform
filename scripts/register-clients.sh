#!/usr/bin/env bash
# =============================================================================
# 파일명: register-clients.sh
# 경로: scripts/register-clients.sh
# 목적: mcp-platform 서버들을 Codex, Antigravity(agy), VS Code, Cursor 설정에 원클릭으로 등록 및 갱신함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MCP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
WORKSPACE_ROOT="$(cd -- "$MCP_ROOT/.." && pwd)"

echo "=== MCP Platform 클라이언트 등록 시작 ==="

# 템플릿 치환 헬퍼 함수
render_template() {
  local src="$1"
  sed -e "s|__MCP_PLATFORM_ROOT__|$MCP_ROOT|g" \
      -e "s|__WORKSPACE_ROOT__|$WORKSPACE_ROOT|g" \
      "$src"
}

# 1. Antigravity (~/.gemini/config/mcp_config.json) 등록
AGY_CONFIG_DIR="$HOME/.gemini/config"
mkdir -p "$AGY_CONFIG_DIR"
render_template "$MCP_ROOT/config/clients/antigravity.json" > "$AGY_CONFIG_DIR/mcp_config.json"
echo "[OK] Antigravity 설정 갱신 완료: $AGY_CONFIG_DIR/mcp_config.json"

# 2. Codex (~/.codex/config.toml) 등록
CODEX_CONFIG="$HOME/.codex/config.toml"
if [[ -f "$CODEX_CONFIG" ]]; then
  # 기존 mcp-platform 항목이 없거나 갱신이 필요한 경우 처리
  if grep -q "mcp-platform" "$CODEX_CONFIG"; then
    echo "[INFO] Codex 설정에 mcp-platform 항목이 이미 존재함: $CODEX_CONFIG"
  else
    echo "" >> "$CODEX_CONFIG"
    render_template "$MCP_ROOT/config/clients/codex.toml" >> "$CODEX_CONFIG"
    echo "[OK] Codex 설정에 mcp-platform 추가 완료: $CODEX_CONFIG"
  fi
else
  mkdir -p "$(dirname "$CODEX_CONFIG")"
  render_template "$MCP_ROOT/config/clients/codex.toml" > "$CODEX_CONFIG"
  echo "[OK] Codex 신규 설정 생성 완료: $CODEX_CONFIG"
fi

# 3. VS Code / Cline / Roo Code 작업 공간 설정 (.vscode/mcp.json) 갱신 (존재하는 경우)
VSCODE_DIR="$MCP_ROOT/.vscode"
mkdir -p "$VSCODE_DIR"
render_template "$MCP_ROOT/config/clients/vscode_mcp.json" > "$VSCODE_DIR/mcp.json"
echo "[OK] VS Code 작업 공간 설정 갱신 완료: $VSCODE_DIR/mcp.json"

# 4. internal-portal 프로젝트 작업 공간 설정 (.vscode/mcp.json) 갱신
PORTAL_DIR="$WORKSPACE_ROOT/internal-portal/.vscode"
if [[ -d "$(dirname "$PORTAL_DIR")" ]]; then
  mkdir -p "$PORTAL_DIR"
  render_template "$MCP_ROOT/config/clients/vscode_mcp.json" > "$PORTAL_DIR/mcp.json"
  echo "[OK] internal-portal MCP 설정 갱신 완료: $PORTAL_DIR/mcp.json"
fi

# 5. 런타임 빌드 상태 검증
echo "--- TypeScript 게이트웨이 빌드 검증 ---"
(cd "$MCP_ROOT" && npm run build)

echo "=== 모든 MCP 클라이언트 등록 및 준비 완료 ==="
