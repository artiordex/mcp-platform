# =============================================================================
# 파일명: smes.py
# 경로: connectors/mcp_platform/servers/smes.py
# 목적: 중소벤처기업부 기업마당 지원사업 공고 및 정책자금 정보 조회를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""중소벤처기업부 기업마당 지원사업 공고 및 정책자금 정보 조회를 제공함"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import error_result

mcp = FastMCP("중소벤처기업부 기업마당 지원사업 정보 서비스")

BIZINFO_BASE_URL = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
BIZINFO_API_KEY = os.getenv("BIZINFO_API_KEY", os.getenv("DATA_GO_API_KEY", "dev_test_key"))

SUPPORT_CATEGORIES = {
    "FIN": "금융 (융자/보증/이차보전)",
    "TECH": "기술 (R&D/특허/기술이전)",
    "HR": "인력 (일자리/채용지원/교육)",
    "EXPORT": "수출 (해외진출/수출바우처)",
    "DOMESTIC": "내수 (판로/유통/마케팅)",
    "STARTUP": "창업 (사업화/인큐베이팅/액셀러레이팅)",
    "MGMT": "경영 (컨설팅/스마트공장/ESG)",
}


@mcp.tool()
async def search_support_programs(
    keyword: str = "",
    category: str = "",
    page_no: int = 1,
    num_of_rows: int = 10,
) -> dict[str, Any]:
    """중소벤처기업부 기업마당에 등록된 중앙부처 및 지자체 지원사업 공고를 검색함

    Args:
        keyword: 검색 키워드임 (예: 스마트공장, AI바우처, 수출바우처, 창업패키지)
        category: 지원분야 코드임 (FIN, TECH, HR, EXPORT, DOMESTIC, STARTUP, MGMT)
        page_no: 페이지 번호임 (기본값: 1)
        num_of_rows: 반환할 공고 수임 (기본 10건, 최대 50건)

    Returns:
        지원사업 공고 목록, 접수기간, 소관부처, 지원분야를 담은 결과 객체임
    """
    clean_keyword = keyword.strip()
    clean_category = category.strip().upper()

    cache_key = api_cache.make_key(
        "smes_programs",
        kw=clean_keyword,
        cat=clean_category,
        p=page_no,
        rows=num_of_rows,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "crtfcKey": BIZINFO_API_KEY,
        "dataType": "json",
        "pageUnit": min(max(num_of_rows, 1), 50),
        "pageIndex": page_no,
    }
    if clean_keyword:
        params["searchWrd"] = clean_keyword
    if clean_category in SUPPORT_CATEGORIES:
        params["searchPldir"] = clean_category

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(BIZINFO_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            json_array = data.get("jsonArray", [])
            total_count = data.get("totalCount", len(json_array))

            items = []
            for item in json_array:
                items.append(
                    {
                        "pblanc_id": item.get("pblancId", ""),
                        "title": item.get("pblancNm", ""),
                        "category_name": item.get("pldirExatNm", ""),
                        "executing_agency": item.get("excAgency", item.get("jrsdInsttNm", "")),
                        "application_period": f"{item.get('reqstBeginEndDe', '별도 공고 참조')}",
                        "target_company": item.get("trgetNm", "중소·벤처기업"),
                        "detail_url": item.get("pblancUrl", ""),
                    }
                )

            result = {
                "success": True,
                "total_count": total_count,
                "page_no": page_no,
                "items": items,
                "category_filter": clean_category or "전체",
            }
            api_cache.set(cache_key, result, ttl_seconds=1800)
            return result

    except httpx.HTTPError as exc:
        return error_result(
            operation="smes.search_support_programs",
            service_name="중소벤처기업부 기업마당 API",
            target_id=clean_keyword or "전체",
            cause=exc,
        )
    except Exception as exc:
        return {
            "success": False,
            "error": f"지원사업 조회 중 오류 발생함: {exc}",
            "items": [],
        }


@mcp.tool()
async def get_support_program_detail(
    pblanc_id: str,
) -> dict[str, Any]:
    """공고 고유 식별자(pblanc_id)로 지원사업의 상세 지원내용 및 신청자격을 조회함

    Args:
        pblanc_id: 지원사업 공고 고유 식별자임

    Returns:
        상세 사업목적, 지원대상, 지원규모, 신청방법 및 문의처 정보 객체임
    """
    clean_id = pblanc_id.strip()
    if not clean_id:
        return {"success": False, "error": "pblanc_id 매개변수가 필수임"}

    cache_key = api_cache.make_key("smes_detail", pid=clean_id)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "crtfcKey": BIZINFO_API_KEY,
        "dataType": "json",
        "pblancId": clean_id,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(BIZINFO_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            json_array = data.get("jsonArray", [])
            if not json_array:
                return {
                    "success": False,
                    "error": f"공고 식별자 {clean_id}에 해당하는 상세 정보를 찾을 수 없음",
                }

            detail = json_array[0]
            result = {
                "success": True,
                "pblanc_id": clean_id,
                "title": detail.get("pblancNm", ""),
                "business_summary": detail.get("bsnsCn", ""),
                "target_description": detail.get("trgetNm", ""),
                "support_content": detail.get("sportCn", ""),
                "application_method": detail.get("reqstMthd", ""),
                "contact_info": detail.get("inqryTelno", ""),
                "detail_url": detail.get("pblancUrl", ""),
            }
            api_cache.set(cache_key, result, ttl_seconds=3600)
            return result

    except httpx.HTTPError as exc:
        return error_result(
            operation="smes.get_support_program_detail",
            service_name="중소벤처기업부 기업마당 API",
            target_id=clean_id,
            cause=exc,
        )
    except Exception as exc:
        return {"success": False, "error": f"상세 정보 조회 중 오류 발생함: {exc}"}


@mcp.resource("smes://categories")
def get_support_categories() -> str:
    """기업마당 표준 지원분야 분류 체계 및 지원 대상을 반환함"""
    lines = ["# 중소벤처기업부 기업마당 7대 지원분야 체계", ""]
    for code, desc in SUPPORT_CATEGORIES.items():
        lines.append(f"- **{code}**: {desc}")
    lines.append("")
    lines.append("## 주요 수혜 대상 분류")
    lines.append("- 예비창업자 및 3년 미만 초기창업기업")
    lines.append("- 벤처기업, 이노비즈, 메인비즈 인증기업")
    lines.append("- 업력 7년 이내 도약기 중소기업")
    lines.append("- 소상공인 및 전통시장 상인")
    return "\n".join(lines)


@mcp.prompt()
def match_company_policy_funds(
    company_name: str,
    business_sector: str,
    employee_count: int,
    focus_area: str = "R&D 및 사업화",
) -> str:
    """기업의 주요 제원(업종, 인원, 중점 희망분야)에 기초한 맞춤형 정부지원사업 매칭 기안 프롬프트임"""
    return (
        f"당신은 공공 정책자금 및 R&D 지원사업 수주 전문 컨설턴트입니다.\n\n"
        f"대상 기업 정보:\n"
        f"- 기업명: {company_name}\n"
        f"- 주력 업종: {business_sector}\n"
        f"- 상시 근로자수: {employee_count}인\n"
        f"- 희망 지원 분야: {focus_area}\n\n"
        f"작업 지침:\n"
        f"1. 위 기업의 규모와 업종 특성을 분석하여 가장 적합한 정부 지원사업(중기부, 과기부, 산업부) 유형 3가지를 추천하세요.\n"
        f"2. 각 지원사업별 가점 취득 방안(특허 출원, 벤처인증, 청년고용 등)을 제시하세요.\n"
        f"3. 사업계획서 기안 시 기술성 및 시장성 강조 포인트를 구체적으로 작성하세요.\n"
        f"4. 사내 RAG 문서 및 조달청 나라장터 유사 공고와 연계하여 추진 일정을 4단계 로드맵으로 구성하세요."
    )
