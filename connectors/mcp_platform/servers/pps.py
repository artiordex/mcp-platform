# =============================================================================
# 파일명: pps.py
# 경로: connectors/mcp_platform/servers/pps.py
# 목적: 조달청 나라장터 입찰공고·낙찰·계약 정보 조회 및 제안서 초안 작성을 지원함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""조달청 나라장터 입찰공고·낙찰·계약 정보 조회 및 제안서 초안 작성을 지원함"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import as_list, error_result, get_json, int_value, response_body, service_key

mcp = FastMCP("나라장터 공공데이터개방표준서비스")
BASE_URL = "http://apis.data.go.kr/1230000/ao/PubDataOpnStdService"


def format_datetime_for_api(value: str | None = None, *, end: bool = False) -> str:
    """날짜 또는 분 단위 타임스탬프를 YYYYMMDDHHMM 형식으로 변환함"""
    if not value:
        return datetime.now().strftime("%Y%m%d2359" if end else "%Y%m%d0000")
    cleaned = value.replace("-", "").replace(":", "").replace(" ", "")
    if len(cleaned) == 8:
        return cleaned + ("2359" if end else "0000")
    if len(cleaned) == 12 and cleaned.isdigit():
        return cleaned
    raise ValueError(f"잘못된 날짜/시간 형식: {value}")


def parse_business_type(value: str) -> str:
    """한글 업무구분을 나라장터 표준 코드(1, 2, 3, 5)로 변환함"""
    return {"물품": "1", "외자": "2", "공사": "3", "용역": "5"}.get(value, value)


def _items(body: dict[str, Any]) -> list[dict[str, Any]]:
    """응답 본문에서 항목 목록을 안전하게 추출함"""
    return [item for item in as_list(body.get("items")) if isinstance(item, dict)]


async def _request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """나라장터 공공데이터 API를 호출하고 응답을 파싱함"""
    payload = await get_json(
        f"{BASE_URL}/{endpoint}",
        params={"ServiceKey": service_key(), "type": "json", **params},
    )
    return response_body(payload)


def _result(body: dict[str, Any], *, page_no: int, num_of_rows: int, **extra: Any) -> dict[str, Any]:
    """공통 결과 페이징 매핑을 반환함"""
    return {
        "success": True,
        "items": _items(body),
        "total_count": int_value(body.get("totalCount"), 0),
        "page_no": int_value(body.get("pageNo"), page_no),
        "num_of_rows": int_value(body.get("numOfRows"), num_of_rows),
        **extra,
    }


# -----------------------------------------------------------------------------
# 1. MCP Tools (나라장터 데이터 도구)
# -----------------------------------------------------------------------------


@mcp.tool()
async def search_bid_announcements(
    start_date: str | None = None,
    end_date: str | None = None,
    num_of_rows: int = 10,
    page_no: int = 1,
) -> dict[str, Any]:
    """지정한 기간의 나라장터 입찰공고 목록을 조회함

    Args:
        start_date: 검색 시작 일시 (YYYYMMDD 또는 YYYY-MM-DD)
        end_date: 검색 종료 일시 (YYYYMMDD 또는 YYYY-MM-DD)
        num_of_rows: 페이지당 조회 건수 (최대 999)
        page_no: 페이지 번호

    Returns:
        입찰공고 목록 및 페이징 메타데이터 객체임
    """
    start = format_datetime_for_api(start_date)
    end = format_datetime_for_api(end_date or start_date, end=True)
    cache_key = api_cache.make_key(
        "pps_bids",
        start=start,
        end=end,
        rows=num_of_rows,
        page=page_no,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        body = await _request(
            "getDataSetOpnStdBidPblancInfo",
            {
                "bidNtceBgnDt": start,
                "bidNtceEndDt": end,
                "numOfRows": min(max(num_of_rows, 1), 999),
                "pageNo": page_no,
            },
        )
        res = _result(
            body,
            page_no=page_no,
            num_of_rows=num_of_rows,
            search_period=f"{start[:8]} ~ {end[:8]}",
        )
        api_cache.set(cache_key, res, ttl_seconds=300)
        return res
    except Exception as exc:
        return error_result(exc, success=False, items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows)


@mcp.tool()
async def search_successful_bids(
    business_type: str = "1",
    start_date: str | None = None,
    end_date: str | None = None,
    num_of_rows: int = 10,
    page_no: int = 1,
) -> dict[str, Any]:
    """나라장터 낙찰정보를 업무구분(물품/외자/공사/용역)별로 조회함"""
    code = parse_business_type(business_type)
    if start_date:
        start = format_datetime_for_api(start_date)
        end = format_datetime_for_api(end_date or start_date, end=True)
    else:
        finish = datetime.now()
        start = (finish - timedelta(days=7)).strftime("%Y%m%d0000")
        end = finish.strftime("%Y%m%d2359")

    cache_key = api_cache.make_key(
        "pps_success",
        code=code,
        start=start,
        end=end,
        rows=num_of_rows,
        page=page_no,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        body = await _request(
            "getDataSetOpnStdScsbidInfo",
            {
                "bsnsDivCd": code,
                "opengBgnDt": start,
                "opengEndDt": end,
                "numOfRows": min(max(num_of_rows, 1), 999),
                "pageNo": page_no,
            },
        )
        names = {"1": "물품", "2": "외자", "3": "공사", "5": "용역"}
        res = _result(
            body,
            page_no=page_no,
            num_of_rows=num_of_rows,
            business_type=names.get(code, code),
            search_period=f"{start[:8]} ~ {end[:8]}",
        )
        api_cache.set(cache_key, res, ttl_seconds=300)
        return res
    except Exception as exc:
        return error_result(exc, success=False, items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows)


@mcp.tool()
async def search_contracts(
    start_date: str | None = None,
    end_date: str | None = None,
    institution_type: str | None = None,
    institution_code: str | None = None,
    num_of_rows: int = 10,
    page_no: int = 1,
) -> dict[str, Any]:
    """나라장터 체결 계약정보를 발주기관과 기간 조건으로 조회함"""
    try:
        start = format_datetime_for_api(start_date)[:8]
        end = format_datetime_for_api(end_date or start_date)[:8]
        body = await _request(
            "getDataSetOpnStdCntrctInfo",
            {
                "cntrctCnclsBgnDate": start,
                "cntrctCnclsEndDate": end,
                "insttDivCd": institution_type,
                "insttCd": institution_code,
                "numOfRows": min(max(num_of_rows, 1), 999),
                "pageNo": page_no,
            },
        )
        filters = {"type": institution_type, "code": institution_code} if institution_type or institution_code else None
        return _result(
            body,
            page_no=page_no,
            num_of_rows=num_of_rows,
            search_period=f"{start} ~ {end}",
            institution_filter=filters,
        )
    except Exception as exc:
        return error_result(exc, success=False, items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows)


@mcp.tool()
async def get_bid_detail(bid_notice_no: str) -> dict[str, Any]:
    """입찰공고번호에 해당하는 공고의 상세 명세를 조회함"""
    cache_key = api_cache.make_key("pps_detail", no=bid_notice_no)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        finish = datetime.now()
        start = (finish - timedelta(days=30)).strftime("%Y%m%d0000")
        end = finish.strftime("%Y%m%d2359")
        body = await _request(
            "getDataSetOpnStdBidPblancInfo",
            {"bidNtceBgnDt": start, "bidNtceEndDt": end, "numOfRows": 999, "pageNo": 1},
        )
        for item in _items(body):
            if item.get("bidNtceNo") == bid_notice_no:
                res = {"success": True, "data": item, "message": f"입찰공고번호 {bid_notice_no}의 상세정보를 조회함"}
                api_cache.set(cache_key, res, ttl_seconds=600)
                return res
        return {"success": False, "error": f"입찰공고번호 {bid_notice_no}를 찾지 못함", "data": None}
    except Exception as exc:
        return error_result(exc, success=False, data=None)


# -----------------------------------------------------------------------------
# 2. MCP Prompts (입찰 분석 워크플로우 지원)
# -----------------------------------------------------------------------------


@mcp.prompt()
def analyze_bid_proposal(bid_notice_no: str) -> str:
    """나라장터 입찰공고를 분석하고 제안서 작성 전략을 수립하는 프롬프트임"""
    return (
        f"당신은 공공조달 입찰 제안 컨설턴트입니다. 입찰공고번호 '{bid_notice_no}'에 대해 분석을 수행하십시오.\n\n"
        f"수행 순서:\n"
        f"1. `get_bid_detail` 도구를 호출하여 공고의 발주처, 배정 예산, 입찰 마감일, 참가 자격을 확인하십시오.\n"
        f"2. 사내 `rag_search_documents` 도구를 통해 사내 유사 실적 증명서나 관련 기술 규정이 있는지 검색하십시오.\n"
        f"3. 다음 항목으로 구성된 제안 전략 요약표를 작성하십시오:\n"
        f"   - 사업 개요 및 추정 가격\n"
        f"   - 제안 참가 필수 요건 체크리스트\n"
        f"   - 주요 평가 요소 및 가점 전략\n"
        f"   - 사내 RAG 기반 활용 가능 실적 및 보유 기술 매핑"
    )


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
