# =============================================================================
# 파일명: food_safety.py
# 경로: connectors/mcp_platform/servers/food_safety.py
# 목적: 식품안전나라(식약처) 바코드연계제품, 품목제조보고, 회수·판매중지 식품 정보 조회를 담당함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""식품안전나라(식약처) 바코드연계제품, 품목제조보고, 회수·판매중지 식품 정보 조회를 담당함"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import DataGoError, error_result, get_json, int_value

mcp = FastMCP("Food Safety Korea")
BASE_URL = "https://openapi.foodsafetykorea.go.kr/api"
MAX_ROWS = 1000


def food_safety_key() -> str:
    """식품안전나라 전용 인증키를 반환함"""
    key = os.getenv("FOOD_SAFETY_API_KEY") or os.getenv("FOOD_API_KEY")
    if not key:
        raise DataGoError(
            "FOOD_SAFETY_API_KEY 환경변수가 설정되지 않음. 식품안전나라는 별도 인증키가 필요함"
        )
    return key


def _date(value: str | None, field_name: str) -> str | None:
    """날짜 문자열을 YYYYMMDD 형식으로 검증 및 정제함"""
    if value is None or not value.strip():
        return None
    clean = value.strip().replace("-", "")
    if len(clean) != 8 or not clean.isdigit():
        raise ValueError(f"{field_name} 항목은 YYYYMMDD 또는 YYYY-MM-DD 형식이어야 함")
    return clean


def _request_url(
    service_id: str,
    start_index: int,
    end_index: int,
    filters: Mapping[str, str],
) -> str:
    """식품안전나라 REST 엔드포인트 URL 경로를 조립함"""
    path = "/".join(
        [
            BASE_URL,
            quote(food_safety_key(), safe=""),
            quote(service_id, safe=""),
            "json",
            str(start_index),
            str(end_index),
        ]
    )
    if filters:
        suffix = "&".join(
            f"{quote(name, safe='')}={quote(value, safe='')}"
            for name, value in filters.items()
        )
        path = f"{path}/{suffix}"
    return path


def _rows(value: Any) -> list[dict[str, Any]]:
    """응답 row 리스트를 딕셔너리 배열로 정규화함"""
    if isinstance(value, Mapping):
        return [dict(value)]
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, Mapping)]
    return []


async def _request(
    service_id: str,
    *,
    page_no: int,
    num_of_rows: int,
    filters: Mapping[str, str],
) -> dict[str, Any]:
    """식품안전나라 오픈API를 호출하고 페이징된 결과를 반환함"""
    clean_page = max(page_no, 1)
    clean_rows = min(max(num_of_rows, 1), MAX_ROWS)
    start_index = (clean_page - 1) * clean_rows + 1
    end_index = start_index + clean_rows - 1
    payload = await get_json(
        _request_url(service_id, start_index, end_index, filters)
    )
    if not isinstance(payload, Mapping):
        raise DataGoError("식품안전나라 응답이 JSON 객체가 아님")

    service = payload.get(service_id)
    if not isinstance(service, Mapping):
        raise DataGoError(f"식품안전나라 응답에 {service_id} 서비스 결과가 없음")

    result = service.get("RESULT")
    if isinstance(result, Mapping):
        code = str(result.get("CODE") or "")
        message = str(result.get("MSG") or "")
    else:
        code = ""
        message = ""
    if code and code not in {"INFO-000", "INFO-200"}:
        raise DataGoError(f"식품안전나라 API 오류 [{code}]: {message}")

    items = _rows(service.get("row"))
    return {
        "service_id": service_id,
        "page_no": clean_page,
        "num_of_rows": clean_rows,
        "start_index": start_index,
        "end_index": end_index,
        "total_count": int_value(service.get("total_count"), 0),
        "items": items,
        "result_code": code or None,
        "message": message or ("정상 처리됨" if items else "조회된 데이터가 없음"),
    }


# -----------------------------------------------------------------------------
# MCP Tools (식품안전나라 도구)
# -----------------------------------------------------------------------------


@mcp.tool()
async def search_food_products(
    report_no: str | None = None,
    barcode: str | None = None,
    changed_after: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """식품안전나라 바코드연계제품정보(C005)를 품목보고번호나 바코드 조건으로 조회함"""
    cache_key = api_cache.make_key(
        "food_c005",
        rep=report_no,
        bar=barcode,
        chg=changed_after,
        page=page_no,
        rows=num_of_rows,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        filters = {
            key: value
            for key, value in {
                "CHNG_DT": _date(changed_after, "changed_after"),
                "PRDLST_REPORT_NO": report_no.strip() if report_no else None,
                "BAR_CD": barcode.strip() if barcode else None,
            }.items()
            if value
        }
        res = await _request(
            "C005",
            page_no=page_no,
            num_of_rows=num_of_rows,
            filters=filters,
        )
        api_cache.set(cache_key, res, ttl_seconds=600)
        return res
    except Exception as exc:
        return error_result(
            exc,
            service_id="C005",
            page_no=max(page_no, 1),
            num_of_rows=min(max(num_of_rows, 1), MAX_ROWS),
            items=[],
            total_count=0,
        )


@mcp.tool()
async def search_food_manufacturing_reports(
    product_name: str | None = None,
    report_no: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """식품 품목제조보고(I1270) 등록 내역을 제품명이나 품목제조보고번호로 조회함"""
    try:
        filters = {
            key: value
            for key, value in {
                "PRDLST_NM": product_name.strip() if product_name else None,
                "PRDLST_REPORT_NO": report_no.strip() if report_no else None,
            }.items()
            if value
        }
        return await _request(
            "I1250",
            page_no=page_no,
            num_of_rows=num_of_rows,
            filters=filters,
        )
    except Exception as exc:
        return error_result(
            exc,
            service_id="I1250",
            page_no=max(page_no, 1),
            num_of_rows=min(max(num_of_rows, 1), MAX_ROWS),
            items=[],
            total_count=0,
        )


# 이전 호환성을 위한 별칭 도구임
search_food_reports = search_food_manufacturing_reports


@mcp.tool()
async def search_recalled_foods(
    product_name: str | None = None,
    barcode: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """회수 및 판매중지 대상 불량·위해식품(I0490) 목록을 조회함"""
    try:
        filters = {
            key: value
            for key, value in {
                "PRDLST_NM": product_name.strip() if product_name else None,
                "BAR_CD": barcode.strip() if barcode else None,
            }.items()
            if value
        }
        return await _request(
            "I0490",
            page_no=page_no,
            num_of_rows=num_of_rows,
            filters=filters,
        )
    except Exception as exc:
        return error_result(
            exc,
            service_id="I0490",
            page_no=max(page_no, 1),
            num_of_rows=min(max(num_of_rows, 1), MAX_ROWS),
            items=[],
            total_count=0,
        )


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
