#!/usr/bin/env bash
# =============================================================================
# 파일명: run-data-go-portal.sh
# 경로: scripts/run-data-go-portal.sh
# 목적: 공공데이터포털 및 식품안전나라 하위 서버 집합을 선별 기동함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export DATA_GO_SERVERS="${DATA_GO_SERVERS:-nps,fsc,public_data_catalog,food_safety}"

exec "$script_dir/run-data-go-gateway.sh" "$@"
