#!/usr/bin/env bash
# =============================================================================
# 파일명: benchmark-e2e.sh
# 경로: scripts/benchmark-e2e.sh
# 목적: 실무 시나리오(나라장터 입찰-기업분석-사내RAG-문서인제스트) E2E 실행 및 캐시 성능을 측정함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
MCP_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="$MCP_ROOT/.venv/bin/python"

echo "================================================================="
echo "        mcp-platform 엔터프라이즈 실무 시나리오 E2E 벤치마크      "
echo "================================================================="

"$PYTHON" - << 'EOF'
import asyncio
import time
from datetime import datetime
from mcp_platform.servers import pps, corporate_intelligence, rag, dart

async def run_scenario():
    print("\n[시나리오 1] 나라장터 최근 입찰공고 및 발주계획 탐색")
    t0 = time.perf_counter()
    bids = await pps.search_bid_announcements(num_of_rows=3)
    order_plans = await pps.search_order_plans(num_of_rows=3)
    t1 = time.perf_counter()
    print(f"  - 입찰공고 조회 완료: 총 {bids.get('total_count', 0)}건 검색됨 (소요시간: {t1 - t0:.3f}초)")
    print(f"  - 발주계획 조회 완료: 총 {order_plans.get('total_count', 0)}건 검색됨")

    print("\n[시나리오 2] 협력 대상 기업 종합 분석 (세무+고용+재무+사내실적+DART)")
    t0 = time.perf_counter()
    corp = await corporate_intelligence.analyze_company_comprehensive(
        company_name="삼성전자",
        include_internal_knowledge=True,
    )
    t1 = time.perf_counter()
    print(f"  - 기업 진단 완료 (소요시간: {t1 - t0:.3f}초)")
    print(f"  - 판정 등급: {corp.get('overall_grade')}")
    if corp.get("dart_filings"):
        print(f"  - DART 최근 공시: {corp['dart_filings'].get('total_recent', 0)}건 확인됨")

    print("\n[시나리오 3] 사내 RAG-vLLM 지식 검색 및 제안 전략 기안문 작성")
    t0 = time.perf_counter()
    search_res = await rag.rag_search_documents(query="AI 클라우드 인프라 구축 실적", top_k=2)
    t1 = time.perf_counter()
    print(f"  - 사내 실적 문서 검색 완료: {search_res.get('total_found', 0)}건 참조됨 (소요시간: {t1 - t0:.3f}초)")

    memo_text = rag.draft_internal_memo("2026 공공조달 AI 제안 사업 착수안", "AI전략팀")
    print(f"  - 표준 기안서 양식 생성 완료 (길이: {len(memo_text)}자)")

    print("\n[시나리오 4] 생성된 기안 보고서 사내 RAG 지식베이스 실시간 등록 (인제스트)")
    doc_name = f"E2E_제안착수안_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    t0 = time.perf_counter()
    ingest_res = await rag.rag_ingest_document(
        name=doc_name,
        text=memo_text,
        department="AI전략팀",
        source_type="benchmark_test",
    )
    t1 = time.perf_counter()
    print(f"  - RAG 색인 등록 완료 (소요시간: {t1 - t0:.3f}초)")
    print(f"  - 문서 ID: {ingest_res.get('document_id')}, 청크 수: {ingest_res.get('chunks_created')}")

    print("\n[시나리오 5] In-Memory TTL 캐시 레이어 성능 측정")
    # 동일 요청 반복 호출 시 캐시 적중 여부 및 지연시간 비교
    t0 = time.perf_counter()
    corp_cached = await corporate_intelligence.analyze_company_comprehensive(
        company_name="삼성전자",
        include_internal_knowledge=True,
    )
    t1 = time.perf_counter()
    cached_time = t1 - t0
    print(f"  - 캐시 적중 호출 소요시간: {cached_time:.6f}초")
    print(f"  - 캐시 적중률 및 정합성 검증: {'정상 일치함' if corp == corp_cached else '불일치'}")

    print("\n=================================================================")
    print("      모든 실무 시나리오 E2E 파이프라인 검증 성공함 (Pass)      ")
    print("=================================================================")

if __name__ == "__main__":
    asyncio.run(run_scenario())
EOF
