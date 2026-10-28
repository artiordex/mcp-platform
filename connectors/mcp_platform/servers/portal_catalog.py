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

import math
import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import DataGoError, HTTP_TIMEOUT, error_result, int_value, post_json, service_key

mcp = FastMCP("Public Data Portal Catalog")
BASE_URL = "https://api.odcloud.kr/api/GetSearchDataList/v1/searchData"
DEFAULT_DATA_TYPES = ["API", "FILE", "STD"]
MAX_PAGE_SIZE = 100
PORTAL_SEARCH_URL = "https://www.data.go.kr/tcs/dss/selectDataSetList.do"
PORTAL_PAGE_SIZE = 10


class _HtmlNode:
    """공공데이터포털 검색 결과 HTML 일부를 탐색하기 위한 경량 노드임"""

    def __init__(self, tag: str, attrs: Mapping[str, str | None] | None = None) -> None:
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.parts: list[str | _HtmlNode] = []

    def walk(self):
        yield self
        for part in self.parts:
            if isinstance(part, _HtmlNode):
                yield from part.walk()

    def text(self) -> str:
        return "".join(part.text() if isinstance(part, _HtmlNode) else part for part in self.parts)


class _PortalSearchParser(HTMLParser):
    """공공데이터포털 검색 페이지에서 결과 카드 DOM만 간단히 구성함"""

    _VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _HtmlNode("document")
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _HtmlNode(tag, dict(attrs))
        self.stack[-1].parts.append(node)
        if tag not in self._VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.stack[-1].parts.append(_HtmlNode(tag, dict(attrs)))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self.stack[-1].parts.append(data)


def _class_has(node: _HtmlNode, class_name: str) -> bool:
    return class_name in str(node.attrs.get("class") or "").split()


def _text(node: _HtmlNode) -> str:
    return re.sub(r"\s+", " ", node.text()).strip()


def _portal_items(page_html: str, requested_type: str) -> tuple[list[dict[str, Any]], int]:
    """공식 포털 검색 페이지의 결과 카드와 해당 유형의 전체 건수를 추출함"""
    parser = _PortalSearchParser()
    parser.feed(page_html)
    nodes = list(parser.root.walk())
    result: list[dict[str, Any]] = []
    total_count = 0

    for node in nodes:
        if node.tag == "a" and node.attrs.get("data-type") == requested_type:
            match = re.search(r"([\d,]+)\s*건", _text(node))
            if match:
                total_count = int(match.group(1).replace(",", ""))
                break

    for card in nodes:
        if card.tag != "div" or not _class_has(card, "apply-result-item"):
            continue
        descendants = list(card.walk())
        link = next(
            (
                child
                for child in descendants
                if child.tag == "a"
                and re.match(r"^/data/\d+/(openapi|fileData|standard)\.do$", str(child.attrs.get("href") or ""))
            ),
            None,
        )
        if link is None:
            continue

        href = str(link.attrs.get("href"))
        route = href.rsplit("/", 1)[-1].split(".", 1)[0]
        data_type = {"openapi": "API", "fileData": "FILE", "standard": "STD"}.get(route)
        if data_type != requested_type:
            continue

        summary_node = next(
            (child for child in descendants if _class_has(child, "apply-result-summary")),
            None,
        )
        category_node = next(
            (child for child in descendants if _class_has(child, "apply-result-category")),
            None,
        )
        badges = [
            _text(child)
            for child in (category_node.walk() if category_node else [])
            if child.tag == "span" and _text(child)
        ]
        metadata: dict[str, str] = {}
        for child in descendants:
            if child.tag != "li":
                continue
            label_node = next((part for part in child.walk() if part.tag == "strong"), None)
            if label_node is None:
                continue
            label = _text(label_node)
            value = _text(child).replace(label, "", 1).strip()
            metadata[label] = value

        keywords = [value.strip() for value in metadata.get("키워드", "").split(",") if value.strip()]
        view_match = re.search(r"[\d,]+", metadata.get("조회수", ""))
        item = {
            "name": _text(link),
            "description": _text(summary_node) if summary_node else None,
            "organization": metadata.get("제공기관"),
            "categories": badges[:1],
            "keywords": keywords,
            "data_type": data_type,
            "provision_type": None,
            "institution_type": badges[1] if len(badges) > 1 else None,
            "update_date": metadata.get("수정일"),
            "detail_url": urljoin("https://www.data.go.kr", href),
            "columns": [],
            "is_corporate_api": False,
            "is_core_data": "국가중점" in badges,
            "view_count": int(view_match.group(0).replace(",", "")) if view_match else 0,
        }
        result.append(item)
    return result, total_count


async def _search_portal_page(
    *,
    keyword: str | None,
    data_type: str,
    page: int,
    organization: str | None = None,
    categories: list[str] | None = None,
    provision_types: list[str] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """인증이 필요한 카탈로그 API가 거부될 때 공식 공개 검색 페이지를 조회함"""
    params: list[tuple[str, str | int]] = [
        ("sType", "total"),
        ("dType", data_type),
        ("keyword", (keyword or "").strip()),
        ("currentPage", page),
        # 포털 검색 결과는 페이지당 10건을 제공함. size는 MCP 응답에서 조절함.
        ("size", PORTAL_PAGE_SIZE),
    ]
    if organization and organization.strip():
        params.append(("instt", organization.strip()))
    params.extend(("brm", value) for value in _values(categories))
    params.extend(("svcType", value) for value in _values(provision_types))

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        response = await client.get(
            PORTAL_SEARCH_URL,
            params=params,
            headers={"Accept": "text/html", "User-Agent": "mcp-platform-data-catalog/1.0"},
        )
        response.raise_for_status()
        return _portal_items(response.text, data_type)


def _values(values: list[str] | None) -> list[str]:
    """유효한 공백 제거 문자열 리스트를 필터링함"""
    return [value.strip() for value in values or [] if value and value.strip()]


def _result_container(payload: Any) -> dict[str, Any]:
    """공공데이터포털 검색 응답의 result 컨테이너를 추출함"""
    if not isinstance(payload, Mapping):
        raise DataGoError("공공데이터포털 검색 응답이 JSON 객체가 아님")

    status_code = payload.get("statusCode", payload.get("code"))
    if status_code is not None and str(status_code) not in {"200", "0", "OK"}:
        message = payload.get("message") or payload.get("resultMsg") or payload.get("msg") or "검색 API 오류임"
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
        categories=",".join(sorted(categories or [])),
        provision_types=",".join(sorted(provision_types or [])),
        page=page,
        size=size,
        sort=sort,
        sort_order=sort_order,
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

        selected_types = [
            value.upper()
            for value in (_values(data_types) or DEFAULT_DATA_TYPES)
            if value.upper() in DEFAULT_DATA_TYPES
        ]
        if not selected_types:
            raise ValueError("data_types는 API, FILE, STD 중 하나 이상이어야 함")

        body: dict[str, Any] = {
            "page": clean_page,
            "size": clean_size,
            "dataType": selected_types,
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

        try:
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
            catalog_source = "catalog_api"
            source_note = None
        except DataGoError:
            # 공공데이터포털 목록은 공개 페이지도 제공하므로 검색 API 인증이 실패해도 목록 검색을 이어감.
            # 데이터셋 상세 OpenAPI 호출은 각 데이터셋의 활용신청 권한을 그대로 따름.
            per_type_limit = math.ceil(clean_size / len(selected_types))
            scan_pages = min(10, max(1, math.ceil(per_type_limit / PORTAL_PAGE_SIZE)))
            per_type_items: dict[str, list[dict[str, Any]]] = {}
            type_counts: dict[str, int] = {}
            for data_type in selected_types:
                gathered: list[dict[str, Any]] = []
                type_count = 0
                for offset in range(scan_pages):
                    page_items, page_count = await _search_portal_page(
                        keyword=keyword,
                        data_type=data_type,
                        page=clean_page + offset,
                        organization=organization,
                        categories=categories,
                        provision_types=provision_types,
                    )
                    type_count = page_count
                    for item in page_items:
                        if organization and organization.casefold() not in str(item.get("organization") or "").casefold():
                            continue
                        if categories and not any(
                            requested.casefold() in category.casefold()
                            for requested in _values(categories)
                            for category in item.get("categories", [])
                        ):
                            continue
                        gathered.append(item)
                        if len(gathered) >= per_type_limit:
                            break
                    if len(gathered) >= per_type_limit or (type_count and (clean_page + offset) * PORTAL_PAGE_SIZE >= type_count):
                        break
                per_type_items[data_type] = gathered
                type_counts[data_type] = type_count

            items = []
            for item_index in range(per_type_limit):
                for data_type in selected_types:
                    typed_items = per_type_items.get(data_type, [])
                    if item_index < len(typed_items):
                        items.append(typed_items[item_index])
                        if len(items) >= clean_size:
                            break
                if len(items) >= clean_size:
                    break
            if sort == "modified":
                items.sort(key=lambda item: str(item.get("update_date") or ""), reverse=clean_sort_order == "desc")
            elif sort == "viewCount":
                items.sort(key=lambda item: int_value(item.get("view_count"), 0), reverse=clean_sort_order == "desc")
            total_count = sum(type_counts.values())
            if organization or categories:
                total_count = len(items)
            catalog_source = "portal_search_page"
            source_note = "공개 검색 페이지를 사용함. 데이터 조회 권한은 각 OpenAPI의 활용신청 상태에 따름."

        res = {
            "success": True,
            "page": clean_page,
            "size": clean_size,
            "total_count": total_count,
            "returned_count": len(items),
            "items": items[:clean_size],
            "catalog_source": catalog_source,
            "message": f"데이터셋 {len(items[:clean_size])}건을 조회함" if items else "조건에 맞는 데이터셋이 없음",
        }
        if source_note:
            res["note"] = source_note
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
