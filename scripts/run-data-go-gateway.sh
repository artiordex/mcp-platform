#!/usr/bin/env bash
# =============================================================================
# 파일명: run-data-go-gateway.sh
# 경로: scripts/run-data-go-gateway.sh
# 목적: 공공데이터포털 다중 서버를 stdio로 집합 프록시하는 게이트웨이를 기동함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec node "$script_dir/../dist/servers/data-go-gateway.js" "$@"
