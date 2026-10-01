#!/usr/bin/env bash
# =============================================================================
# 파일명: register-clients.sh
# 경로: scripts/register-clients.sh
# 목적: mcp-platform 서버 설정을 검증된 클라이언트(Codex, Claude Desktop, Cursor, VS Code 등)에 안전하게 병합 등록함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MCP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PROJECTS_ROOT="$(cd -- "$MCP_ROOT/.." && pwd)"
WORKSPACE_ROOT="${MCP_WORKSPACE_ROOT:-$MCP_ROOT}"
PYTHON="${PYTHON:-python3}"
MERGE_SCRIPT="$SCRIPT_DIR/merge-client-config.py"

echo "=== MCP Platform 클라이언트 안전 병합 등록 시작 ==="

# 설정을 바꾸기 전에 실행 파일을 먼저 준비하여 깨진 빌드로 인한 등록을 방지함
echo "--- TypeScript 게이트웨이 빌드 검증 ---"
(cd "$MCP_ROOT" && npm run build)

TMP_DIR="$(mktemp -d -t mcp-reg-XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

# 템플릿 치환 헬퍼 함수
render_template() {
  local src="$1"
  local dst="$2"
  local workspace_root="${3:-$WORKSPACE_ROOT}"
  MCP_TEMPLATE_ROOT="$MCP_ROOT" \
    MCP_TEMPLATE_WORKSPACE="$workspace_root" \
    "$PYTHON" - "$src" "$dst" <<'PY'
import json
import os
import sys
from pathlib import Path

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
content = source.read_text(encoding="utf-8")
replacements = {
    "__MCP_PLATFORM_ROOT__": os.environ["MCP_TEMPLATE_ROOT"],
    "__WORKSPACE_ROOT__": os.environ["MCP_TEMPLATE_WORKSPACE"],
}
for marker, value in replacements.items():
    escaped = json.dumps(value, ensure_ascii=False)[1:-1]
    content = content.replace(marker, escaped)
destination.write_text(content, encoding="utf-8")
PY
}

# 1. Codex (~/.codex/config.toml) 안전 병합
CODEX_CONFIG="$HOME/.codex/config.toml"
TMP_CODEX="$TMP_DIR/codex.toml"
render_template "$MCP_ROOT/config/clients/codex.toml" "$TMP_CODEX"
"$PYTHON" "$MERGE_SCRIPT" toml "$CODEX_CONFIG" "$TMP_CODEX"
echo "[OK] Codex 설정 병합 완료: $CODEX_CONFIG"

# 2. VS Code 작업 공간 설정 (.vscode/mcp.json) 안전 병합
VSCODE_CONFIG="$MCP_ROOT/.vscode/mcp.json"
TMP_VSCODE="$TMP_DIR/vscode.json"
render_template "$MCP_ROOT/config/clients/vscode_mcp.json" "$TMP_VSCODE"
"$PYTHON" "$MERGE_SCRIPT" json "$VSCODE_CONFIG" "$TMP_VSCODE"
echo "[OK] VS Code 작업 공간 설정 병합 완료: $VSCODE_CONFIG"

# 3. internal-portal 프로젝트 작업 공간 설정 병합 (존재하는 경우)
PORTAL_DIR="$PROJECTS_ROOT/internal-portal"
if [[ -d "$PORTAL_DIR" ]]; then
  PORTAL_CONFIG="$PORTAL_DIR/.vscode/mcp.json"
  TMP_PORTAL_VSCODE="$TMP_DIR/portal-vscode.json"
  render_template "$MCP_ROOT/config/clients/vscode_mcp.json" "$TMP_PORTAL_VSCODE" "${MCP_WORKSPACE_ROOT:-$PORTAL_DIR}"
  "$PYTHON" "$MERGE_SCRIPT" json "$PORTAL_CONFIG" "$TMP_PORTAL_VSCODE"
  echo "[OK] internal-portal MCP 설정 병합 완료: $PORTAL_CONFIG"
fi

# 4. Cursor 설정 (~/.cursor/mcp.json) 안전 병합 (디렉터리 존재 시)
CURSOR_DIR="$HOME/.cursor"
if [[ -d "$CURSOR_DIR" ]] || [[ -f "$HOME/.cursor/mcp.json" ]]; then
  CURSOR_CONFIG="$HOME/.cursor/mcp.json"
  TMP_CURSOR="$TMP_DIR/cursor.json"
  render_template "$MCP_ROOT/config/clients/cursor_mcp.json" "$TMP_CURSOR"
  "$PYTHON" "$MERGE_SCRIPT" json "$CURSOR_CONFIG" "$TMP_CURSOR"
  echo "[OK] Cursor 설정 병합 완료: $CURSOR_CONFIG"
fi

# 5. Claude Desktop 설정 (~/.config/Claude/claude_desktop_config.json) 안전 병합 (디렉터리 존재 시)
CLAUDE_DIR="$HOME/.config/Claude"
if [[ -d "$CLAUDE_DIR" ]] || [[ -f "$CLAUDE_DIR/claude_desktop_config.json" ]]; then
  CLAUDE_CONFIG="$CLAUDE_DIR/claude_desktop_config.json"
  TMP_CLAUDE="$TMP_DIR/claude.json"
  render_template "$MCP_ROOT/config/clients/claude_desktop_config.json" "$TMP_CLAUDE"
  "$PYTHON" "$MERGE_SCRIPT" json "$CLAUDE_CONFIG" "$TMP_CLAUDE"
  echo "[OK] Claude Desktop 설정 병합 완료: $CLAUDE_CONFIG"
fi

# 6. Antigravity (~/.gemini/config/mcp_config.json) 안전 병합
AGY_DIR="$HOME/.gemini/config"
if [[ -d "$AGY_DIR" ]]; then
  AGY_CONFIG="$AGY_DIR/mcp_config.json"
  TMP_AGY="$TMP_DIR/agy.json"
  render_template "$MCP_ROOT/config/clients/antigravity.json" "$TMP_AGY"
  "$PYTHON" "$MERGE_SCRIPT" json "$AGY_CONFIG" "$TMP_AGY"
  echo "[OK] Antigravity 설정 병합 완료: $AGY_CONFIG"
fi

echo "=== MCP 클라이언트 설정 보존 병합 완료 ==="
