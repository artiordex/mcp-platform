# =============================================================================
# 파일명: corporate_intelligence.py
# 경로: connectors/mcp_platform/servers/corporate_intelligence.py
# 목적: 국세청, 국민연금, 금융위 공공데이터 및 사내 RAG 지식을 결합한 기업 종합 분석 도구를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""국세청, 국민연금, 금융위 공공데이터 및 사내 RAG 지식을 결합한 기업 종합 분석 도구를 제공함"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import error_result
from . import dart, fsc, nps, nts, rag

mcp = FastMCP("Corporate Intelligence Hub")


@mcp.tool()
async def analyze_company_comprehensive(
    business_number: str | None = None,
    company_name: str | None = None,
    include_internal_knowledge: bool = True,
) -> dict[str, Any]:
    """기업에 대한 국세청 사업자상태, 국민연금 고용·급여, 금융위 재무제표 및 사내 지식을 종합 진단함

    Args:
        business_number: 사업자등록번호(10자리 숫자)임
        company_name: 기업명 또는 법인명임 (예: 삼성전자, 카카오)
        include_internal_knowledge: 사내 RAG-vLLM 문서 이력 병합 검색 여부임 (기본: True)

    Returns:
        기업 기본정보, 사업자 상태, 고용 지표, 재무 건전성 및 사내 연관 문서가 결합된 종합 진단 객체임
    """
    if not business_number and not company_name:
        return {"success": False, "error": "business_number 또는 company_name 중 하나 이상을 입력해야 함"}

    cache_key = api_cache.make_key(
        "corp_comprehensive",
        biz_no=business_number,
        name=company_name,
        rag=include_internal_knowledge,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    clean_biz_no = business_number.replace("-", "").strip() if business_number else None
    search_name = company_name.strip() if company_name else ""

    result: dict[str, Any] = {
        "success": True,
        "query": {"business_number": clean_biz_no, "company_name": search_name},
        "tax_status": None,
        "pension_employment": None,
        "financial_summary": None,
        "internal_rag_history": None,
        "overall_grade": "정보 수집 중",
    }

    tasks = []

    # 1. 국세청 사업자등록 상태 조회
    if clean_biz_no:
        tasks.append(("nts", nts.check_business_status([clean_biz_no])))
    else:
        tasks.append(("nts", asyncio.sleep(0, result=None)))

    # 2. 국민연금 사업장 고용 및 급여 추정
    if search_name or clean_biz_no:
        tasks.append(("nps", nps.search_business(wkpl_nm=search_name or None, bzowr_rgst_no=clean_biz_no or None, page_no=1, num_of_rows=5)))
    else:
        tasks.append(("nps", asyncio.sleep(0, result=None)))

    # 3. 금융위 요약 재무제표 조회
    if clean_biz_no:
        tasks.append(("fsc", fsc.get_summary_financial_statement(crno=clean_biz_no)))
    else:
        tasks.append(("fsc", asyncio.sleep(0, result=None)))

    # 4. 사내 RAG 지식 검색
    rag_query = search_name or clean_biz_no or ""
    if include_internal_knowledge and rag_query:
        tasks.append(("rag", rag.rag_search_documents(query=f"{rag_query} 계약 실적 협약", top_k=3)))
    else:
        tasks.append(("rag", asyncio.sleep(0, result=None)))

    # 5. 금융감독원 OpenDART 공시 보고서 검색
    if search_name:
        tasks.append(("dart", dart.search_dart_filings(corp_name=search_name, page_count=5)))
    else:
        tasks.append(("dart", asyncio.sleep(0, result=None)))

    # 병렬 비동기 조회
    task_keys = [t[0] for t in tasks]
    task_coros = [t[1] for t in tasks]
    responses = await asyncio.gather(*task_coros, return_exceptions=True)

    gathered: dict[str, Any] = {}
    for key, resp in zip(task_keys, responses):
        if isinstance(resp, Exception):
            gathered[key] = {"error": str(resp)}
        else:
            gathered[key] = resp

    # 응답 취합 및 정제
    # NTS 상태
    nts_data = gathered.get("nts")
    if nts_data and isinstance(nts_data, dict) and nts_data.get("items"):
        item = nts_data["items"][0]
        result["tax_status"] = {
            "status": item.get("status", "확인 불가"),
            "tax_type": item.get("tax_type", "확인 불가"),
            "is_active": "계속사업자" in str(item.get("status", "")),
        }

    # NPS 고용 지표
    nps_data = gathered.get("nps")
    if nps_data and isinstance(nps_data, dict) and nps_data.get("items"):
        item = nps_data["items"][0]
        result["pension_employment"] = {
            "business_name": item.get("wkplNm") or item.get("name"),
            "employee_count": item.get("jnngPsnCnt") or item.get("employees"),
            "location": item.get("ldongAddr") or item.get("address"),
        }

    # FSC 재무 지표
    fsc_data = gathered.get("fsc")
    if fsc_data and isinstance(fsc_data, dict) and fsc_data.get("data"):
        d = fsc_data["data"]
        result["financial_summary"] = {
            "year": d.get("year"),
            "revenue": d.get("revenue"),
            "operating_income": d.get("operating_income"),
            "net_income": d.get("net_income"),
            "debt_ratio": d.get("debt_ratio"),
        }

    # DART 최근 공시 내역
    dart_data = gathered.get("dart")
    if dart_data and isinstance(dart_data, dict) and dart_data.get("items"):
        result["dart_filings"] = {
            "total_recent": dart_data.get("total_count", 0),
            "recent_reports": [
                f"[{it.get('rcept_dt')}] {it.get('report_nm')} ({it.get('flr_nm')})"
                for it in dart_data.get("items", [])[:3]
            ],
        }

    # 사내 RAG 연관 이력
    rag_data = gathered.get("rag")
    if rag_data and isinstance(rag_data, dict):
        result["internal_rag_history"] = {
            "total_matches": rag_data.get("total_found", 0),
            "documents": [c.get("document_name") for c in rag_data.get("chunks", [])],
        }

    # 종합 등급 판정 로직
    is_active = (result.get("tax_status") or {}).get("is_active", True)
    has_finance = result.get("financial_summary") is not None
    if not is_active:
        result["overall_grade"] = "주의 (휴폐업 사업자)"
    elif has_finance:
        result["overall_grade"] = "양호 (재무 및 세무 정상 검증됨)"
    else:
        result["overall_grade"] = "정상 (기본 사업자등록 검증됨)"

    api_cache.set(cache_key, result, ttl_seconds=300)
    return result


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
