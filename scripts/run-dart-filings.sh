#!/usr/bin/env bash
# =============================================================================
# 파일명: run-dart-filings.sh
# 경로: scripts/run-dart-filings.sh
# 목적: 금융감독원 전자공시시스템(OpenDART) FastMCP 서버를 단독 stdio 모드로 기동함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail
exec "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/run-data-go-server.sh" dart-filings "$@"
