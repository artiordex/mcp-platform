#!/usr/bin/env bash
# =============================================================================
# 파일명: setup-mcp-go.sh
# 경로: scripts/setup-mcp-go.sh
# 목적: Go MCP 모듈 의존성을 동기화 및 검증함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"

cd "$mcp_root"
go mod tidy
go test ./...
