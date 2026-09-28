"""MCP server for selected Food Safety Korea public APIs."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from mcp.server.fastmcp import FastMCP

from ..core.common import DataGoError, error_result, get_json, int_value

mcp = FastMCP("Food Safety Korea")
BASE_URL = "https://openapi.foodsafetykorea.go.kr/api"
MAX_ROWS = 1000


def food_safety_key() -> str:
    key = os.getenv("FOOD_SAFETY_API_KEY") or os.getenv("FOOD_API_KEY")
    if not key:
        raise DataGoError(
            "FOOD_SAFETY_API_KEY is not configured. Food Safety Korea issues "
            "a separate key from DATA_GO_API_KEY."
        )
    return key


def _date(value: str | None, field_name: str) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip().replace("-", "")
    if len(clean) != 8 or not clean.isdigit():
        raise ValueError(f"{field_name}는 YYYYMMDD 또는 YYYY-MM-DD 형식이어야 합니다.")
    return clean


def _request_url(
    service_id: str,
    start_index: int,
    end_index: int,
    filters: Mapping[str, str],
) -> str:
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
    clean_page = max(page_no, 1)
    clean_rows = min(max(num_of_rows, 1), MAX_ROWS)
    start_index = (clean_page - 1) * clean_rows + 1
    end_index = start_index + clean_rows - 1
    payload = await get_json(
        _request_url(service_id, start_index, end_index, filters)
    )
    if not isinstance(payload, Mapping):
        raise DataGoError("식품안전나라 응답이 JSON 객체가 아닙니다.")

    service = payload.get(service_id)
    if not isinstance(service, Mapping):
        raise DataGoError(f"식품안전나라 응답에 {service_id} 서비스 결과가 없습니다.")

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
        "message": message or ("정상 처리되었습니다." if items else "조회된 데이터가 없습니다."),
    }


@mcp.tool()
async def search_food_products(
    report_no: str | None = None,
    barcode: str | None = None,
    changed_after: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """식품안전나라 바코드연계제품정보(C005)를 조회합니다."""
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
        return await _request(
            "C005",
            page_no=page_no,
            num_of_rows=num_of_rows,
            filters=filters,
        )
    except Exception as exc:
        return error_result(exc, service_id="C005", items=[])


@mcp.tool()
async def search_food_manufacturing_reports(
    product_name: str | None = None,
    manufacturer_name: str | None = None,
    report_no: str | None = None,
    license_no: str | None = None,
    reported_on: str | None = None,
    changed_after: str | None = None,
    product_type: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """식품(첨가물) 품목제조보고(I1250)를 조회합니다."""
    try:
        filters = {
            key: value
            for key, value in {
                "CHNG_DT": _date(changed_after, "changed_after"),
                "PRDLST_REPORT_NO": report_no.strip() if report_no else None,
                "BSSH_NM": manufacturer_name.strip() if manufacturer_name else None,
                "PRDLST_NM": product_name.strip() if product_name else None,
                "LCNS_NO": license_no.strip() if license_no else None,
                "PRMS_DT": _date(reported_on, "reported_on"),
                "PRDLST_DCNM": product_type.strip() if product_type else None,
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
        return error_result(exc, service_id="I1250", items=[])


@mcp.tool()
async def search_food_recalls(
    report_no: str | None = None,
    registered_on: str | None = None,
    changed_after: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """식품 부적합 회수·폐기 정보(I0490)를 조회합니다."""
    try:
        filters = {
            key: value
            for key, value in {
                "CRET_DTM": _date(registered_on, "registered_on"),
                "PRDLST_REPORT_NO": report_no.strip() if report_no else None,
                "CHNG_DT": _date(changed_after, "changed_after"),
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
        return error_result(exc, service_id="I0490", items=[])


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
