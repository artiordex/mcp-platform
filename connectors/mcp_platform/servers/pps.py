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

import os
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import (
    as_list,
    error_result,
    get_json,
    int_value,
    post_json,
    response_body,
)
from .pps_api import (
    API_SERVICES,
    call_api as call_openapi_api,
    get_all_api_services_info as list_api_services,
    get_api_operations as list_api_operations,
    pps_service_key,
    protect_context,
)
from .pps_guides import (
    API_PARAMETER_REQUIREMENTS,
    COMMON_SEARCH_PATTERNS,
    EXPLORATION_GUIDES,
    PARAMETER_SELECTION_GUIDE,
    PARAMETER_VALUE_EXAMPLES,
    REAL_WORLD_QUERY_EXAMPLES,
    WORKFLOW_GUIDE,
)

mcp = FastMCP("나라장터 공공데이터개방표준서비스")
BASE_URL = "http://apis.data.go.kr/1230000/ao/PubDataOpnStdService"
G2B_DETAIL_URL = "https://shop.g2b.go.kr/gm/gms/gmsf/GdsDtlInfo/selectPdctAtrbInfo.do"
G2B_DETAIL_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json;charset=UTF-8",
    "Referer": "https://shop.g2b.go.kr/",
    "Origin": "https://shop.g2b.go.kr",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
}

PPS_TOOL_NAMES = [
    "search_bid_announcements",
    "search_successful_bids",
    "search_contracts",
    "get_bid_detail",
    "search_order_plans",
    "crawl_list",
    "get_detailed_attributes",
    "server_info",
    "call_public_data_standard_api",
    "call_procurement_statistics_api",
    "call_product_list_api",
    "call_shopping_mall_api",
    "get_all_api_services_info",
    "get_api_operations",
    "call_api_with_pagination_support",
    "get_data_exploration_guide",
    "get_recent_bid_announcements",
    "get_successful_bids_by_business_type",
    "get_procurement_statistics_by_year",
    "search_shopping_mall_products",
    "health_check",
]


def _date_only(value: str | None, *, end: bool = False) -> str:
    """나라장터 쇼핑몰 API 날짜 파라미터를 YYYYMMDD 형식으로 정규화함"""
    return format_datetime_for_api(value, end=end)[:8]


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
        params={"ServiceKey": pps_service_key(), "type": "json", **params},
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


@mcp.tool()
async def search_order_plans(
    start_date: str | None = None,
    end_date: str | None = None,
    num_of_rows: int = 10,
    page_no: int = 1,
) -> dict[str, Any]:
    """공공기관의 발주계획(사업명, 발주시기, 추정금액, 발주기관) 목록을 조회함

    Args:
        start_date: 발주예정일 검색 시작일임 (YYYYMMDD 또는 YYYY-MM-DD)
        end_date: 발주예정일 검색 종료일임 (YYYYMMDD 또는 YYYY-MM-DD)
        num_of_rows: 페이지당 조회 건수임 (최대 999)
        page_no: 페이지 번호임

    Returns:
        발주계획 목록 및 페이징 메타데이터 객체임
    """
    start = format_datetime_for_api(start_date)[:8]
    end = format_datetime_for_api(end_date or start_date)[:8]
    cache_key = api_cache.make_key("pps_order_plans", start=start, end=end, rows=num_of_rows, page=page_no)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        body = await _request(
            "getDataSetOpnStdOrderPlanInfo",
            {
                "orderPlanBgnDate": start,
                "orderPlanEndDate": end,
                "numOfRows": min(max(num_of_rows, 1), 999),
                "pageNo": page_no,
            },
        )
        res = _result(
            body,
            page_no=page_no,
            num_of_rows=num_of_rows,
            search_period=f"{start} ~ {end}",
        )
        api_cache.set(cache_key, res, ttl_seconds=600)
        return res
    except Exception as exc:
        return error_result(exc, success=False, items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows)


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


# -----------------------------------------------------------------------------
# 3. G2B 상품 조회 및 OpenAPI 도구
# -----------------------------------------------------------------------------


@mcp.tool()
async def crawl_list(
    category: str,
    page_no: int = 1,
    num_rows: int = 100,
    days_back: int = 7,
    inqry_bgn_date: str | None = None,
    inqry_end_date: str | None = None,
) -> dict[str, Any]:
    """종합쇼핑몰에서 품명별 상품 목록을 조회함

    Args:
        category: 상품 품명 또는 검색할 분류명임
        page_no: 조회 페이지 번호임
        num_rows: 페이지당 조회 건수임
        days_back: 날짜를 지정하지 않았을 때 조회할 과거 일수임
        inqry_bgn_date: 조회 시작일(YYYYMMDD)임
        inqry_end_date: 조회 종료일(YYYYMMDD)임
    """
    end = datetime.now()
    if not inqry_bgn_date or not inqry_end_date:
        start = end - timedelta(days=max(0, min(days_back, 3650)))
        inqry_bgn_date = start.strftime("%Y%m%d")
        inqry_end_date = end.strftime("%Y%m%d")

    result = await call_openapi_api(
        "shopping_mall",
        "getShoppingMallPrdctInfoList",
        {
            "prdctClsfcNoNm": category,
            "inqryBgnDate": _date_only(inqry_bgn_date),
            "inqryEndDate": _date_only(inqry_end_date, end=True),
        },
        num_of_rows=num_rows,
        page_no=page_no,
    )
    if not result.get("success"):
        return {**result, "category": category, "current_page": page_no}
    return {
        "success": True,
        "items": result["items"],
        "total_count": result["total_count"],
        "current_page": result["page_no"],
        "category": category,
        "search_period": f"{inqry_bgn_date} ~ {inqry_end_date}",
    }


@mcp.tool()
async def get_detailed_attributes(api_item: dict[str, Any]) -> dict[str, Any]:
    """상품 목록의 품명·규격으로 나라장터 쇼핑몰 상세 속성을 조회함

    Args:
        api_item: `crawl_list` 또는 쇼핑몰 검색 결과에서 받은 상품 객체임
    """
    if not isinstance(api_item, dict) or not api_item:
        return {
            "success": False,
            "error": "api_item은 비어 있지 않은 상품 객체여야 함",
            "error_type": "validation_error",
            "attributes": {},
        }

    payload = {
        key: api_item[key]
        for key in ("prdctClsfcNoNm", "prdctStndrdNm")
        if api_item.get(key) is not None
    }
    if not payload:
        return {
            "success": False,
            "api_item": api_item,
            "error": "상품 객체에 prdctClsfcNoNm 또는 prdctStndrdNm 값이 필요함",
            "error_type": "missing_fields",
            "payload_attempted": payload,
        }

    cache_key = api_cache.make_key("pps_product_attributes", **payload)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        response_data = await post_json(
            G2B_DETAIL_URL,
            json_body=payload,
            headers=G2B_DETAIL_HEADERS,
        )
        if isinstance(response_data, dict):
            attributes = response_data.get("data", response_data.get("result", response_data))
        else:
            attributes = response_data
        attribute_count = len(attributes) if isinstance(attributes, (dict, list)) else 0
        result = {
            "success": True,
            "api_item": api_item,
            "attributes": attributes,
            "metadata": {
                "item_keys": list(api_item),
                "attributes_count": attribute_count,
                "source": "G2B 종합쇼핑몰 상세 속성 API",
            },
        }
        api_cache.set(cache_key, result, ttl_seconds=600)
        return result
    except Exception as exc:
        return error_result(
            exc,
            success=False,
            api_item=api_item,
            error_type=type(exc).__name__,
            payload_attempted=payload,
        )


@mcp.tool()
def server_info() -> dict[str, Any]:
    """나라장터 서버 정보와 사용 가능한 도구 및 API 서비스 목록을 반환함"""
    return {
        "success": True,
        "app": "mcp-platform-pps",
        "version": "0.1.0",
        "tools": PPS_TOOL_NAMES,
        "services": {
            service_type: {
                "name": service["name"],
                "operations_count": len(service["operations"]),
            }
            for service_type, service in API_SERVICES.items()
        },
        "resources": [
            "guide://api-parameter-requirements",
            "guide://parameter-value-examples",
            "guide://common-search-patterns",
        ],
        "prompts": [
            "workflow_guide",
            "parameter_selection_guide",
            "real_world_query_examples",
            "analyze_bid_proposal",
        ],
    }


async def _call_service_tool(
    service_type: str,
    operation: str,
    parameters: dict[str, Any] | None,
    num_of_rows: int,
    page_no: int,
) -> dict[str, Any]:
    """서비스 API를 호출하고 컨텍스트 크기를 보호함"""
    result = await call_openapi_api(
        service_type,
        operation,
        parameters,
        num_of_rows=num_of_rows,
        page_no=page_no,
    )
    return protect_context(result)


@mcp.tool()
async def call_public_data_standard_api(
    operation: str,
    num_of_rows: int = 5,
    page_no: int = 1,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """입찰·낙찰·계약·발주계획 공공데이터개방표준 API를 호출함

    Args:
        operation: get_api_operations("public_data_standard")로 찾은 작업명임
        num_of_rows: 페이지당 결과 수임
        page_no: 조회할 페이지임
        parameters: `bidNtceBgnDt`, `bsnsDivCd`, `insttCd` 등 API 원래 파라미터임
    """
    return await _call_service_tool(
        "public_data_standard", operation, parameters, num_of_rows, page_no
    )


@mcp.tool()
async def call_procurement_statistics_api(
    operation: str,
    num_of_rows: int = 5,
    page_no: int = 1,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """14개 오퍼레이션을 지원하는 공공조달통계 API를 호출함

    Args:
        operation: get_api_operations("procurement_statistics")로 찾은 작업명임
        num_of_rows: 페이지당 결과 수임
        page_no: 조회할 페이지임
        parameters: `srchBssYear`, `dminsttNm`, `corpNm`, `prdctClsfcNo` 등 API 파라미터임
    """
    return await _call_service_tool(
        "procurement_statistics", operation, parameters, num_of_rows, page_no
    )


@mcp.tool()
async def call_product_list_api(
    operation: str,
    num_of_rows: int = 5,
    page_no: int = 1,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """12개 오퍼레이션을 지원하는 조달청 물품목록 API를 호출함

    Args:
        operation: get_api_operations("product_list")로 찾은 작업명임
        num_of_rows: 페이지당 결과 수임
        page_no: 조회할 페이지임
        parameters: `upPrdctClsfcNo`, `prdctIdntNo`, `mnfctCorpNm` 등 API 파라미터임
    """
    return await _call_service_tool(
        "product_list", operation, parameters, num_of_rows, page_no
    )


@mcp.tool()
async def call_shopping_mall_api(
    operation: str,
    num_of_rows: int = 5,
    page_no: int = 1,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """9개 오퍼레이션을 지원하는 나라장터 종합쇼핑몰 API를 호출함

    Args:
        operation: get_api_operations("shopping_mall")로 찾은 작업명임
        num_of_rows: 페이지당 결과 수임
        page_no: 조회할 페이지임
        parameters: `prdctClsfcNoNm`, `cntrctCorpNm`, `dlvrReqNo` 등 API 파라미터임
    """
    return await _call_service_tool(
        "shopping_mall", operation, parameters, num_of_rows, page_no
    )


@mcp.tool()
def get_all_api_services_info() -> dict[str, Any]:
    """지원하는 나라장터 API 서비스와 오퍼레이션 전체 목록을 반환함"""
    return list_api_services()


@mcp.tool()
def get_api_operations(service_type: str) -> dict[str, Any]:
    """서비스 유형별 API 오퍼레이션과 설명을 반환함"""
    return list_api_operations(service_type)


@mcp.tool()
async def call_api_with_pagination_support(
    service_type: str,
    operation: str,
    num_of_rows: int = 5,
    page_no: int = 1,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """나라장터 API 한 페이지를 조회하고 다음 페이지 호출 정보를 함께 반환함

    Args:
        service_type: `public_data_standard`, `procurement_statistics`, `product_list`, `shopping_mall` 중 하나임
        operation: 해당 서비스가 지원하는 오퍼레이션명임
        num_of_rows: 한 페이지 결과 수임
        page_no: 현재 페이지 번호임
        parameters: API 원래 이름을 키로 사용하는 추가 검색 조건임
    """
    result = await _call_service_tool(
        service_type, operation, parameters, num_of_rows, page_no
    )
    if not result.get("success"):
        return result

    total_count = int_value(result.get("total_count"), 0)
    rows = min(max(int_value(num_of_rows, 5), 1), 999)
    page = max(int_value(page_no, 1), 1)
    total_pages = max((total_count + rows - 1) // rows, 1)
    has_next = page < total_pages
    pagination: dict[str, Any] = {
        "current_page": page,
        "total_pages": total_pages,
        "total_items": total_count,
        "items_per_page": rows,
        "has_next_page": has_next,
        "next_page": page + 1 if has_next else None,
    }
    if has_next:
        pagination["next_request_example"] = {
            "service_type": service_type,
            "operation": operation,
            "num_of_rows": rows,
            "page_no": page + 1,
            "parameters": parameters or {},
        }
    return {
        "success": True,
        "service_type": service_type,
        "operation": operation,
        "data": result,
        "pagination": pagination,
        "params_used": {
            "num_of_rows": rows,
            "page_no": page,
            "parameters": parameters or {},
        },
        "remote_server_note": "전체 결과는 pagination.next_page 값으로 이어서 조회함",
    }


@mcp.tool()
def get_data_exploration_guide(
    service_type: str,
    operation: str,
    expected_data_size: str = "medium",
) -> dict[str, Any]:
    """서비스와 데이터 규모에 맞는 검색 및 페이징 전략을 반환함

    Args:
        service_type: 지원 서비스 식별자임
        operation: 서비스가 제공하는 오퍼레이션명임
        expected_data_size: 예상 규모인 `small`, `medium`, `large` 중 하나임
    """
    service = API_SERVICES.get(service_type)
    if service is None:
        return list_api_operations(service_type)
    if operation not in service["operations"]:
        return {
            "success": False,
            "service_type": service_type,
            "operation": operation,
            "error": "해당 서비스에서 지원하지 않는 오퍼레이션임",
            "available_operations": list(service["operations"]),
        }
    size = expected_data_size if expected_data_size in EXPLORATION_GUIDES else "medium"
    config = EXPLORATION_GUIDES[size]
    return {
        "success": True,
        "service_type": service_type,
        "service": service["name"],
        "operation": operation,
        "expected_data_size": size,
        "recommended_config": config,
        "sample_first_request": {"num_of_rows": config["num_of_rows"], "page_no": 1},
        "exploration_tips": [
            "첫 페이지로 응답 구조와 전체 건수를 확인함",
            "전체 페이지 수를 기준으로 필요한 범위를 나누어 조회함",
            "검색 조건을 추가해 범위를 좁힘",
        ],
    }


@mcp.tool()
async def get_recent_bid_announcements(
    num_rows: int = 5,
    days_back: int = 7,
) -> dict[str, Any]:
    """기간을 자동 계산해 최근 입찰공고를 조회함

    Args:
        num_rows: 반환할 공고 수임
        days_back: 며칠 전까지 조회할지 지정함
    """
    end = datetime.now()
    start = end - timedelta(days=max(0, min(days_back, 3650)))
    return await search_bid_announcements(
        start_date=start.strftime("%Y%m%d0000"),
        end_date=end.strftime("%Y%m%d2359"),
        num_of_rows=num_rows,
        page_no=1,
    )


@mcp.tool()
async def get_successful_bids_by_business_type(
    business_type: str = "물품",
    num_rows: int = 5,
    days_back: int = 30,
) -> dict[str, Any]:
    """업무구분 한글명 또는 코드를 받아 최근 낙찰정보를 조회함

    Args:
        business_type: `물품`, `외자`, `공사`, `용역` 또는 해당 코드임
        num_rows: 반환할 결과 수임
        days_back: 개찰일 기준으로 조회할 과거 일수임
    """
    end = datetime.now()
    start = end - timedelta(days=max(0, min(days_back, 3650)))
    return await search_successful_bids(
        business_type=business_type,
        start_date=start.strftime("%Y%m%d0000"),
        end_date=end.strftime("%Y%m%d2359"),
        num_of_rows=num_rows,
        page_no=1,
    )


@mcp.tool()
async def get_procurement_statistics_by_year(
    year: str,
    num_rows: int = 10,
) -> dict[str, Any]:
    """기준연도를 지정해 전체 공공조달 통계를 조회함

    Args:
        year: 조회 기준연도(YYYY)임
        num_rows: 반환할 통계 결과 수임
    """
    clean_year = year.strip()
    if len(clean_year) != 4 or not clean_year.isdigit():
        return {"success": False, "error": "year는 YYYY 형식이어야 함"}
    return await _call_service_tool(
        "procurement_statistics",
        "getTotlPubPrcrmntSttus",
        {"srchBssYear": clean_year},
        num_rows,
        1,
    )


@mcp.tool()
async def search_shopping_mall_products(
    product_name: str | None = None,
    company_name: str | None = None,
    num_rows: int = 5,
) -> dict[str, Any]:
    """제품명 또는 계약업체명으로 종합쇼핑몰 MAS 상품을 검색함

    Args:
        product_name: 품명 또는 제품 검색어임
        company_name: 계약업체명 검색어임
        num_rows: 반환할 결과 수임
    """
    parameters: dict[str, Any] = {}
    if product_name and product_name.strip():
        parameters["prdctClsfcNoNm"] = product_name.strip()
    if company_name and company_name.strip():
        parameters["cntrctCorpNm"] = company_name.strip()
    return await _call_service_tool(
        "shopping_mall",
        "getMASCntrctPrdctInfoList",
        parameters,
        num_rows,
        1,
    )


@mcp.tool()
def health_check() -> dict[str, Any]:
    """나라장터 커넥터 프로세스와 API 키 설정 여부를 반환함"""
    return {
        "success": True,
        "status": "healthy",
        "server": "mcp-platform-pps",
        "transport": "stdio",
        "api_key_configured": bool(
            os.getenv("NARAMARKET_SERVICE_KEY") or os.getenv("DATA_GO_API_KEY") or os.getenv("API_KEY")
        ),
        "tools_available": True,
    }


# -----------------------------------------------------------------------------
# 4. MCP 가이드 리소스와 워크플로우 프롬프트
# -----------------------------------------------------------------------------


@mcp.resource("guide://api-parameter-requirements")
def get_api_parameter_requirements() -> str:
    """서비스별 필수·권장 파라미터 설명을 반환함"""
    return API_PARAMETER_REQUIREMENTS


@mcp.resource("guide://parameter-value-examples")
def get_parameter_value_examples() -> str:
    """업무구분, 기관구분, 날짜와 검색어 값 예시를 반환함"""
    return PARAMETER_VALUE_EXAMPLES


@mcp.resource("guide://common-search-patterns")
def get_common_search_patterns() -> str:
    """나라장터에서 자주 사용하는 검색 조합과 탐색 순서를 반환함"""
    return COMMON_SEARCH_PATTERNS


@mcp.prompt()
def workflow_guide() -> str:
    """나라장터 조달 데이터 분석 워크플로우 가이드를 제공함"""
    return WORKFLOW_GUIDE


@mcp.prompt()
def parameter_selection_guide() -> str:
    """조달 API 파라미터를 선택하고 검색 범위를 좁히는 가이드를 제공함"""
    return PARAMETER_SELECTION_GUIDE


@mcp.prompt()
def real_world_query_examples() -> str:
    """공공조달 분석을 위한 실전 질의 예시를 제공함"""
    return REAL_WORLD_QUERY_EXAMPLES


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
