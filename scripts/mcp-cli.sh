#!/usr/bin/env bash
# =============================================================================
# 파일명: mcp-cli.sh
# 경로: scripts/mcp-cli.sh
# 목적: mcp-platform 관리 CLI를 venv 파이썬 환경으로 실행하는 셸 래퍼임
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MCP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON_EXEC="$MCP_ROOT/.venv/bin/python"

if [[ ! -x "$PYTHON_EXEC" ]]; then
  PYTHON_EXEC="python3"
fi

exec "$PYTHON_EXEC" "$SCRIPT_DIR/mcp-cli.py" "$@"
