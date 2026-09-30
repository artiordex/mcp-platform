# =============================================================================
# 파일명: dart.py
# 경로: connectors/mcp_platform/servers/dart.py
# 목적: 금융감독원 전자공시시스템(OpenDART) 연동을 통해 기업 공시 보고서 및 기업 개요를 조회함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""금융감독원 전자공시시스템(OpenDART) 연동을 통해 기업 공시 보고서 및 기업 개요를 조회함"""

from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import error_result

mcp = FastMCP("전자공시시스템(OpenDART) 서비스")

DART_BASE_URL = "https://opendart.fss.or.kr/api"
DART_API_KEY = os.getenv("DART_API_KEY", os.getenv("OPENDART_API_KEY", ""))


def _get_api_key() -> str:
    """OpenDART API 인증키를 반환함"""
    return DART_API_KEY or os.getenv("DATA_GO_API_KEY", "")


# -----------------------------------------------------------------------------
# 1. MCP Tools (공시 데이터 도구)
# -----------------------------------------------------------------------------


@mcp.tool()
async def search_dart_filings(
    corp_name: str | None = None,
    corp_code: str | None = None,
    bgn_de: str | None = None,
    end_de: str | None = None,
    pblntf_ty: str | None = None,
    page_no: int = 1,
    page_count: int = 10,
) -> dict[str, Any]:
    """기업의 최근 공시 보고서(사업보고서, 분기보고서, 주요사항 등) 목록을 조회함

    Args:
        corp_name: 공시대상 회사명임 (예: 삼성전자, 카카오)
        corp_code: DART 고유번호(8자리)임
        bgn_de: 검색 시작일자 (YYYYMMDD)임 (미지정 시 최근 3개월)
        end_de: 검색 종료일자 (YYYYMMDD)임 (미지정 시 당일)
        pblntf_ty: 공시유형 (A: 정기공시, B: 주요사항, C: 발행공시, D: 지분공시, E: 기타)임
        page_no: 페이지 번호임
        page_count: 페이지당 건수 (기본 10건, 최대 100건)임

    Returns:
        공시 보고서 목록 및 페이징 객체임
    """
    now = datetime.now()
    end_date = end_de.replace("-", "") if end_de else now.strftime("%Y%m%d")
    bgn_date = bgn_de.replace("-", "") if bgn_de else (now - timedelta(days=90)).strftime("%Y%m%d")

    cache_key = api_cache.make_key(
        "dart_list",
        name=corp_name,
        code=corp_code,
        bgn=bgn_date,
        end=end_date,
        ty=pblntf_ty,
        page=page_no,
        cnt=page_count,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params: dict[str, Any] = {
        "crtfc_key": _get_api_key(),
        "bgn_de": bgn_date,
        "end_de": end_date,
        "page_no": page_no,
        "page_count": min(max(page_count, 1), 100),
    }
    if corp_code:
        params["corp_code"] = corp_code
    if pblntf_ty:
        params["pblntf_ty"] = pblntf_ty

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(f"{DART_BASE_URL}/list.json", params=params)
            resp.raise_for_status()
            data = resp.json()

            status = data.get("status")
            if status != "000":
                # 013: 데이터 없음
                if status == "013":
                    return {
                        "success": True,
                        "total_count": 0,
                        "items": [],
                        "message": "해당 조건의 공시 내역이 존재하지 않음",
                    }
                return {
                    "success": False,
                    "error": data.get("message", "DART API 응답 오류임"),
                    "status_code": status,
                }

            items = [
                {
                    "corp_code": item.get("corp_code"),
                    "corp_name": item.get("corp_name"),
                    "report_nm": item.get("report_nm"),
                    "rcept_no": item.get("rcept_no"),
                    "flr_nm": item.get("flr_nm"),
                    "rcept_dt": item.get("rcept_dt"),
                    "rm": item.get("rm"),
                }
                for item in data.get("list", [])
            ]

            # 회사명 필터 적용 (corp_name이 전달된 경우)
            if corp_name:
                items = [it for it in items if corp_name in it["corp_name"]]

            result = {
                "success": True,
                "total_count": int(data.get("total_count", len(items))),
                "page_no": int(data.get("page_no", page_no)),
                "total_page": int(data.get("total_page", 1)),
                "items": items,
            }
            api_cache.set(cache_key, result, ttl_seconds=600)
            return result
    except Exception as exc:
        return error_result(exc, success=False, total_count=0, items=[])


@mcp.tool()
async def get_company_overview(
    corp_code: str,
) -> dict[str, Any]:
    """DART 기업 고유번호(8자리)에 해당하는 회사의 정관 개요 및 기본 등록 정보를 조회함

    Args:
        corp_code: DART 8자리 기업 고유번호임

    Returns:
        기업 정식 명칭, 대표자명, 법인구분, 법인등록번호, 사업자등록번호, 주소, 업종 객체임
    """
    clean_code = corp_code.strip()
    cache_key = api_cache.make_key("dart_company", code=clean_code)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "crtfc_key": _get_api_key(),
        "corp_code": clean_code,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{DART_BASE_URL}/company.json", params=params)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "000":
                return {
                    "success": False,
                    "error": data.get("message", "기업 정보 조회 실패함"),
                    "status_code": data.get("status"),
                }

            result = {
                "success": True,
                "corp_code": data.get("corp_code"),
                "corp_name": data.get("corp_name"),
                "corp_name_eng": data.get("corp_name_eng"),
                "stock_name": data.get("stock_name"),
                "stock_code": data.get("stock_code"),
                "ceo_nm": data.get("ceo_nm"),
                "corp_cls": data.get("corp_cls"),
                "jurir_no": data.get("jurir_no"),
                "bizr_no": data.get("bizr_no"),
                "adres": data.get("adres"),
                "hm_url": data.get("hm_url"),
                "ir_url": data.get("ir_url"),
                "phn_no": data.get("phn_no"),
                "est_dt": data.get("est_dt"),
                "acc_mt": data.get("acc_mt"),
            }
            api_cache.set(cache_key, result, ttl_seconds=86400) # 기본 정보는 24시간 캐시
            return result
    except Exception as exc:
        return error_result(exc, success=False, corp_code=clean_code)


# -----------------------------------------------------------------------------
# 2. MCP Resources (공시 분류 체계)
# -----------------------------------------------------------------------------


@mcp.resource("dart://report-types")
def get_dart_report_types() -> str:
    """DART 주요 공시 유형 및 분류 코드 체계 리소스를 반환함"""
    return (
        "DART 공시 유형 분류 코드 체계:\n"
        "- A: 정기공시 (사업보고서, 반기보고서, 분기보고서)\n"
        "- B: 주요사항보고 (부도, 영업정지, 회생, 합병, 분할, 주총결의)\n"
        "- C: 발행공시 (증권신고서, 투자설명서, 유상증자, 전환사채발행)\n"
        "- D: 지분공시 (대량보유상황보고서, 임원·주요주주 특정증권등 소유상황보고서)\n"
        "- E: 기타공시 (감사보고서, 의결권대리행사권유, 거래소공시유예)\n"
        "- F: 외부감사관련 (감사보고서, 결산서)\n"
    )


# -----------------------------------------------------------------------------
# 3. MCP Prompts (기업 공시 위험 심사 워크플로우)
# -----------------------------------------------------------------------------


@mcp.prompt()
def audit_company_disclosure(corp_name: str) -> str:
    """기업의 최근 DART 공시와 재무 상태를 분석하여 계약 리스크를 심사하는 프롬프트임"""
    return (
        f"당신은 사내 리스크 심사역입니다. 대상 기업 '{corp_name}'에 대해 공시 기반 신용 심사를 수행하십시오.\n\n"
        f"심사 순서:\n"
        f"1. `search_dart_filings` 도구를 호출하여 최근 1년간의 공시 보고서를 확인하십시오.\n"
        f"2. 주요사항보고(유형 B) 중 자본잠식, 소송, 감자의결, 전환사채(CB) 대량 발행 등 위험 요소가 있는지 점검하십시오.\n"
        f"3. `get_summary_financial_statement` 도구를 결합하여 최근 연도 영업손실 및 부채비율 추이를 파악하십시오.\n"
        f"4. 종합 의견서에 위험 등급(정상 / 관찰 / 주의 / 위험) 및 계약 체결 시 보증보험 추가 징구 권고를 제시하십시오."
    )


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
