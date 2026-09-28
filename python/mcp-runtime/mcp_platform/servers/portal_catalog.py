"""MCP server for searching the Data.go.kr public data catalog."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.common import DataGoError, error_result, int_value, post_json, service_key

mcp = FastMCP("Public Data Portal Catalog")
BASE_URL = "https://api.odcloud.kr/api/GetSearchDataList/v1/searchData"
DEFAULT_DATA_TYPES = ["API", "FILE", "STD"]
MAX_PAGE_SIZE = 100


def _values(values: list[str] | None) -> list[str]:
    return [value.strip() for value in values or [] if value and value.strip()]


def _result_container(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise DataGoError("공공데이터포털 검색 응답이 JSON 객체가 아닙니다.")

    status_code = payload.get("statusCode")
    if status_code is not None and str(status_code) not in {"200", "0"}:
        message = payload.get("message") or payload.get("resultMsg") or "검색 API 오류"
        raise DataGoError(f"공공데이터포털 검색 오류 [{status_code}]: {message}")

    result = payload.get("result")
    if isinstance(result, Mapping):
        return dict(result)
    if isinstance(result, list):
        for item in result:
            if isinstance(item, Mapping):
                return dict(item)
    raise DataGoError("공공데이터포털 검색 응답에 result가 없습니다.")


def _dataset(item: Mapping[str, Any]) -> dict[str, Any]:
    categories = [
        value
        for value in (item.get("firstBrmName"), item.get("secondBrmName"))
        if value not in (None, "")
    ]
    keywords = item.get("keywords")
    if isinstance(keywords, str):
        keywords = [keywords]
    elif not isinstance(keywords, list):
        keywords = []

    columns = item.get("columns")
    if not isinstance(columns, list):
        columns = []

    return {
        "name": item.get("dataName"),
        "description": item.get("dataDescription"),
        "organization": item.get("organization"),
        "categories": categories,
        "keywords": keywords,
        "data_type": item.get("dataType"),
        "provision_type": item.get("dataProvisionType"),
        "institution_type": item.get("institutionType"),
        "update_date": item.get("updateDate"),
        "detail_url": item.get("detailPageUrl"),
        "columns": columns,
        "is_corporate_api": bool(item.get("corpApi")),
        "is_core_data": bool(item.get("coreData")),
    }


@mcp.tool()
async def search_public_datasets(
    keyword: str | None = None,
    organization: str | None = None,
    data_types: list[str] | None = None,
    categories: list[str] | None = None,
    provision_types: list[str] | None = None,
    page: int = 1,
    size: int = 20,
    sort: str = "_score",
    sort_order: str = "desc",
) -> dict[str, Any]:
    """공공데이터포털의 데이터셋·오픈API 카탈로그를 검색합니다."""
    try:
        clean_page = max(page, 1)
        clean_size = min(max(size, 1), MAX_PAGE_SIZE)
        clean_sort_order = sort_order.lower().strip()
        if clean_sort_order not in {"asc", "desc"}:
            raise ValueError("sort_order는 asc 또는 desc여야 합니다.")

        body: dict[str, Any] = {
            "page": clean_page,
            "size": clean_size,
            "dataType": _values(data_types) or DEFAULT_DATA_TYPES,
            "sort": sort.strip() or "_score",
            "sortOrder": clean_sort_order,
        }
        if keyword and keyword.strip():
            body["keyword"] = keyword.strip()
        if organization and organization.strip():
            body["organizations"] = [organization.strip()]
        if values := _values(categories):
            body["brm"] = values
        if values := _values(provision_types):
            body["serviceType"] = values

        payload = await post_json(
            BASE_URL,
            params={"serviceKey": service_key()},
            json_body=body,
            headers={"Content-Type": "application/json"},
        )
        result = _result_container(payload)
        raw_items = result.get("data", [])
        if isinstance(raw_items, Mapping):
            raw_items = [raw_items]
        if not isinstance(raw_items, list):
            raw_items = []
        items = [_dataset(item) for item in raw_items if isinstance(item, Mapping)]
        total_count = int_value(result.get("sum"), int_value(result.get("totalCount"), 0))
        return {
            "page": clean_page,
            "size": clean_size,
            "total_count": total_count,
            "returned_count": int_value(result.get("dataCount"), len(items)),
            "items": items,
            "message": f"{len(items)}개 데이터셋을 찾았습니다." if items else "조건에 맞는 데이터셋이 없습니다.",
        }
    except Exception as exc:
        return error_result(exc, page=max(page, 1), size=min(max(size, 1), MAX_PAGE_SIZE), items=[])


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
