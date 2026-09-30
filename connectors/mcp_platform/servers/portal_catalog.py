# =============================================================================
# 파일명: portal_catalog.py
# 경로: connectors/mcp_platform/servers/portal_catalog.py
# 목적: 공공데이터포털(Data.go.kr) 오픈API 및 파일 데이터셋 카탈로그 검색 도구를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""공공데이터포털(Data.go.kr) 오픈API 및 파일 데이터셋 카탈로그 검색 도구를 제공함"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import DataGoError, error_result, int_value, post_json, service_key

mcp = FastMCP("Public Data Portal Catalog")
BASE_URL = "https://api.odcloud.kr/api/GetSearchDataList/v1/searchData"
DEFAULT_DATA_TYPES = ["API", "FILE", "STD"]
MAX_PAGE_SIZE = 100


def _values(values: list[str] | None) -> list[str]:
    """유효한 공백 제거 문자열 리스트를 필터링함"""
    return [value.strip() for value in values or [] if value and value.strip()]


def _result_container(payload: Any) -> dict[str, Any]:
    """공공데이터포털 검색 응답의 result 컨테이너를 추출함"""
    if not isinstance(payload, Mapping):
        raise DataGoError("공공데이터포털 검색 응답이 JSON 객체가 아님")

    status_code = payload.get("statusCode")
    if status_code is not None and str(status_code) not in {"200", "0"}:
        message = payload.get("message") or payload.get("resultMsg") or "검색 API 오류임"
        raise DataGoError(f"공공데이터포털 검색 오류 [{status_code}]: {message}")

    result = payload.get("result")
    if isinstance(result, Mapping):
        return dict(result)
    if isinstance(result, list):
        for item in result:
            if isinstance(item, Mapping):
                return dict(item)
    raise DataGoError("공공데이터포털 검색 응답에 result 필드가 없음")


def _dataset(item: Mapping[str, Any]) -> dict[str, Any]:
    """데이터셋 단건 명세를 표준 형식으로 변환함"""
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


# -----------------------------------------------------------------------------
# 1. MCP Tools (카탈로그 검색 도구)
# -----------------------------------------------------------------------------


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
    """공공데이터포털에 등록된 수만 건의 오픈API·파일·표준데이터셋 목록을 검색함"""
    cache_key = api_cache.make_key(
        "portal_catalog",
        kw=keyword,
        org=organization,
        types=",".join(sorted(data_types or [])),
        page=page,
        size=size,
        sort=sort,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        clean_page = max(page, 1)
        clean_size = min(max(size, 1), MAX_PAGE_SIZE)
        clean_sort_order = sort_order.lower().strip()
        if clean_sort_order not in {"asc", "desc"}:
            raise ValueError("sort_order는 asc 또는 desc여야 함")

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
        res = {
            "page": clean_page,
            "size": clean_size,
            "total_count": total_count,
            "returned_count": int_value(result.get("dataCount"), len(items)),
            "items": items,
            "message": f"데이터셋 {len(items)}건을 조회함" if items else "조건에 맞는 데이터셋이 없음",
        }
        api_cache.set(cache_key, res, ttl_seconds=600)
        return res
    except Exception as exc:
        return error_result(exc, page=max(page, 1), size=min(max(size, 1), MAX_PAGE_SIZE), items=[])


# -----------------------------------------------------------------------------
# 2. MCP Resources (카탈로그 메타데이터)
# -----------------------------------------------------------------------------


@mcp.resource("catalog://data-go/types")
def get_dataset_types() -> str:
    """공공데이터포털 검색 시 지원하는 데이터 유형 및 제공 방식 명세 리소스임"""
    return (
        "지원 데이터 유형:\n"
        "- API: 오픈API(REST/JSON/XML)\n"
        "- FILE: 파일데이터(CSV, XLS, JSON, XML 등)\n"
        "- STD: 국가공공표준데이터셋\n"
        "정렬 기준: _score (정확도순), modified (수정일순), viewCount (조회수순)"
    )


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
