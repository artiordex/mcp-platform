#!/usr/bin/env bash
# =============================================================================
# 파일명: run-mcp-go-server.sh
# 경로: scripts/run-mcp-go-server.sh
# 목적: Go 기반 고속 stdio MCP 서버를 기동함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"

cd "$mcp_root"
exec go run ./cmd/mcp-go-server "$@"
