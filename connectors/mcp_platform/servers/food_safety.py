# =============================================================================
# 파일명: food_safety.py
# 경로: connectors/mcp_platform/servers/food_safety.py
# 목적: 식품안전나라 API 카탈로그 탐색과 전체 JSON API 조회를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-10-27
# =============================================================================

"""식품안전나라 공식 API 카탈로그 탐색과 JSON API 조회를 제공함"""

from __future__ import annotations

import asyncio
import os
import re
from collections.abc import Mapping
from html.parser import HTMLParser
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import (
    HTTP_TIMEOUT,
    DataGoError,
    error_result,
    get_json,
    int_value,
)

mcp = FastMCP("Food Safety Korea")
BASE_URL = "https://openapi.foodsafetykorea.go.kr/api"
PORTAL_BASE_URL = "https://www.foodsafetykorea.go.kr/api"
CATALOG_URL = f"{PORTAL_BASE_URL}/searchDatasetList.do"
SERVICE_INFO_URL = f"{PORTAL_BASE_URL}/openApiInfo.do"
MAX_ROWS = 1000
CATALOG_PAGE_SIZE = 50
MAX_FILTERS = 40
_SERVICE_ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9-]{1,31}$")
_FILTER_NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_FOOD_API_REQUEST_LOCK = asyncio.Lock()


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


class _TableParser(HTMLParser):
    """서비스 상세 HTML의 표 행을 표준 배열로 읽음"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table_depth = 0
        self._table_rows: list[list[str]] = []
        self._row: list[str] = []
        self._cell_parts: list[str] = []
        self._in_cell = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if self._table_depth == 0:
                self._table_rows = []
            self._table_depth += 1
        elif self._table_depth and tag == "tr":
            self._row = []
        elif self._table_depth and tag in {"td", "th"}:
            self._in_cell = True
            self._cell_parts = []
        elif self._in_cell and tag in {"br", "p", "div"}:
            self._cell_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if self._table_depth and tag in {"td", "th"} and self._in_cell:
            self._row.append(" ".join("".join(self._cell_parts).split()))
            self._in_cell = False
        elif self._table_depth and tag == "tr" and self._row:
            self._table_rows.append(self._row)
            self._row = []
        elif tag == "table" and self._table_depth:
            self._table_depth -= 1
            if self._table_depth == 0:
                self.tables.append(self._table_rows)

    def handle_data(self, data: str) -> None:
        if self._in_cell:
            self._cell_parts.append(data)


async def _catalog_page(keyword: str, page_no: int) -> dict[str, Any]:
    """식품안전나라 공개 서비스 카탈로그의 한 페이지를 조회함"""
    cache_key = api_cache.make_key(
        "food_safety_catalog_page",
        keyword=keyword,
        page=page_no,
        rows=CATALOG_PAGE_SIZE,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    # start_idx는 행 오프셋이 아니라 포털의 페이지 번호임.
    form = {
        "menu_no": "661",
        "menu_grp": "MENU_GRP31",
        "svc_type_cd": "API_TYPE06",
        "show_cnt": str(CATALOG_PAGE_SIZE),
        "start_idx": "" if page_no == 1 else str(page_no),
        "search_keyword": keyword,
    }
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.post(CATALOG_URL, data=form)
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            raise DataGoError(
                f"식품안전나라 서비스 카탈로그 HTTP {exc.response.status_code} 오류"
            ) from exc
        except httpx.RequestError as exc:
            raise DataGoError("식품안전나라 서비스 카탈로그에 연결할 수 없음") from exc
        except ValueError as exc:
            raise DataGoError("식품안전나라 서비스 카탈로그가 JSON을 반환하지 않음") from exc

    if not isinstance(payload, Mapping):
        raise DataGoError("식품안전나라 서비스 카탈로그 응답이 JSON 객체가 아님")
    entries = _rows(payload.get("list"))
    result = {
        "provider_total_count": int_value(payload.get("total_cnt"), 0),
        "entries": entries,
    }
    api_cache.set(cache_key, result, ttl_seconds=3600)
    return result


async def _catalog_entries(keyword: str = "") -> tuple[int, list[dict[str, Any]]]:
    """검색어에 해당하는 전체 카탈로그 결과를 최대 페이지 수만큼 조회함"""
    first = await _catalog_page(keyword, 1)
    provider_total = int_value(first.get("provider_total_count"), 0)
    page_count = max(1, (provider_total + CATALOG_PAGE_SIZE - 1) // CATALOG_PAGE_SIZE)
    entries = list(first.get("entries", []))
    for page_no in range(2, page_count + 1):
        page = await _catalog_page(keyword, page_no)
        entries.extend(page.get("entries", []))
    return provider_total, entries


def _catalog_view(entry: Mapping[str, Any]) -> dict[str, Any]:
    """포털 카탈로그 레코드에서 호출에 필요한 공개 메타정보만 추림"""
    return {
        "service_id": str(entry.get("svc_no") or ""),
        "service_name": str(entry.get("svc_nm") or ""),
        "category": str(entry.get("cl_cd_nm") or ""),
        "provider": str(entry.get("provd_instt_nm") or ""),
        "openapi": str(entry.get("openapi_yn") or "").upper() == "Y",
        "status": str(entry.get("use_stats_cd_nm") or ""),
        "last_updated": str(entry.get("last_updt_dtm") or ""),
        "documentation_url": (
            f"{SERVICE_INFO_URL}?svc_no={quote(str(entry.get('svc_no') or ''), safe='')}"
        ),
    }


def _table_rows(
    tables: list[list[list[str]]], header_label: str
) -> list[list[str]]:
    """특정 헤더를 가진 첫 번째 표의 행을 반환함"""
    for table in tables:
        if table and header_label in table[0]:
            return table
    return []


def _service_id(value: str) -> str:
    """서비스 ID를 URL 경로에 안전하게 사용할 수 있는지 확인함"""
    clean = value.strip()
    if not _SERVICE_ID_PATTERN.fullmatch(clean):
        raise ValueError("service_id는 카탈로그에서 확인한 영문·숫자 서비스 ID여야 함")
    return clean


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
    url = _request_url(service_id, start_index, end_index, filters)
    async with _FOOD_API_REQUEST_LOCK:
        for attempt in range(3):
            payload = await get_json(url)
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
            if code == "INFO-500" and attempt < 2:
                await asyncio.sleep(0.75 * (attempt + 1))
                continue
            if code and code not in {"INFO-000", "INFO-200"}:
                raise DataGoError(f"식품안전나라 API 오류 [{code}]: {message}")
            break

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
async def search_food_safety_services(
    keyword: str | None = None,
    category: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
    openapi_only: bool = True,
) -> dict[str, Any]:
    """식품안전나라 공식 카탈로그에서 API 서비스와 서비스 ID를 검색함"""
    clean_keyword = (keyword or "").strip()
    clean_category = (category or "").strip()
    clean_page = max(page_no, 1)
    clean_rows = min(max(num_of_rows, 1), CATALOG_PAGE_SIZE)
    if len(clean_keyword) > 100:
        return error_result(
            ValueError("keyword는 100자 이하여야 함"),
            keyword=clean_keyword[:100],
            items=[],
            total_count=0,
        )

    try:
        provider_total, entries = await _catalog_entries(clean_keyword)
        if openapi_only:
            entries = [
                entry
                for entry in entries
                if str(entry.get("openapi_yn") or "").upper() == "Y"
            ]
        if clean_category:
            category_key = clean_category.casefold()
            entries = [
                entry
                for entry in entries
                if category_key in str(entry.get("cl_cd_nm") or "").casefold()
            ]

        total_count = len(entries)
        offset = (clean_page - 1) * clean_rows
        return {
            "success": True,
            "keyword": clean_keyword or None,
            "category": clean_category or None,
            "openapi_only": openapi_only,
            "page_no": clean_page,
            "num_of_rows": clean_rows,
            "total_count": total_count,
            "provider_total_count": provider_total,
            "items": [_catalog_view(item) for item in entries[offset : offset + clean_rows]],
            "message": "식품안전나라 서비스 카탈로그 조회 성공",
        }
    except Exception as exc:
        return error_result(
            exc,
            keyword=clean_keyword or None,
            category=clean_category or None,
            page_no=clean_page,
            num_of_rows=clean_rows,
            items=[],
            total_count=0,
        )


@mcp.tool()
async def get_food_safety_service_info(service_id: str) -> dict[str, Any]:
    """식품안전나라 서비스 상세 문서에서 검색 필드와 출력 항목을 조회함"""
    try:
        clean_id = _service_id(service_id)
        _, entries = await _catalog_entries()
        selected = next(
            (
                entry
                for entry in entries
                if str(entry.get("svc_no") or "").casefold() == clean_id.casefold()
            ),
            None,
        )
        if selected is None:
            raise DataGoError(
                f"서비스 ID {clean_id}를 공식 카탈로그에서 찾지 못함. "
                "search_food_safety_services로 유효한 ID를 먼저 확인하십시오"
            )
        if str(selected.get("openapi_yn") or "").upper() != "Y":
            raise DataGoError(f"서비스 {clean_id}는 JSON/XML OpenAPI가 아님")

        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            try:
                response = await client.get(SERVICE_INFO_URL, params={"svc_no": clean_id})
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise DataGoError(
                    f"식품안전나라 서비스 상세 문서 HTTP {exc.response.status_code} 오류"
                ) from exc
            except httpx.RequestError as exc:
                raise DataGoError("식품안전나라 서비스 상세 문서에 연결할 수 없음") from exc

        parser = _TableParser()
        parser.feed(response.text)
        request_rows = _table_rows(parser.tables, "변수명")
        output_rows = _table_rows(parser.tables, "항목")
        message_rows = _table_rows(parser.tables, "메세지코드")

        path_parameters = {"keyId", "serviceId", "dataType", "startIdx", "endIdx"}
        parameters: list[dict[str, Any]] = []
        required_parameters: list[dict[str, Any]] = []
        for row in request_rows[1:]:
            if len(row) < 4 or not row[1] or row[1] in path_parameters:
                continue
            parameter = {
                "name": row[1],
                "type": row[2] if len(row) > 2 else "",
                "description": row[3] if len(row) > 3 else "",
                "value_description": row[4] if len(row) > 4 else "",
                "required": "필수" in (row[2] if len(row) > 2 else ""),
            }
            parameters.append(parameter)
            if parameter["required"]:
                required_parameters.append(parameter)

        output_fields = [
            {"name": row[1], "description": row[2] if len(row) > 2 else ""}
            for row in output_rows[1:]
            if len(row) >= 2 and row[1]
        ]
        message_codes = [
            {"code": row[1], "description": row[2] if len(row) > 2 else ""}
            for row in message_rows[1:]
            if len(row) >= 2 and row[1]
        ]
        sample_match = re.search(
            r"https?://openapi\.foodsafetykorea\.go\.kr/api/sample/[^\"'<>\s]+",
            response.text,
            flags=re.IGNORECASE,
        )
        sample_url = sample_match.group(0) if sample_match else None
        if sample_url:
            sample_url = sample_url.replace("http://", "https://", 1)

        return {
            "success": True,
            **_catalog_view(selected),
            "endpoint_template": (
                f"{BASE_URL}/<FOOD_SAFETY_API_KEY>/{quote(clean_id, safe='')}/"
                "json/{startIdx}/{endIdx}"
            ),
            "sample_url": sample_url,
            "required_parameters": required_parameters,
            "optional_parameters": [
                parameter for parameter in parameters if not parameter["required"]
            ],
            "output_fields": output_fields,
            "message_codes": message_codes,
        }
    except Exception as exc:
        return error_result(exc, service_id=service_id, parameters=[], output_fields=[])


@mcp.tool()
async def call_food_safety_api(
    service_id: str,
    filters: dict[str, str] | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """공식 서비스 ID와 상세 문서의 필드명으로 식품안전나라 JSON API를 직접 호출함"""
    try:
        clean_id = _service_id(service_id)
        _, entries = await _catalog_entries()
        registered = next(
            (
                entry
                for entry in entries
                if str(entry.get("svc_no") or "").casefold() == clean_id.casefold()
                and str(entry.get("openapi_yn") or "").upper() == "Y"
            ),
            None,
        )
        if registered is None:
            raise DataGoError(
                f"서비스 ID {clean_id}를 JSON/XML OpenAPI 카탈로그에서 찾지 못함. "
                "search_food_safety_services로 공식 ID를 먼저 검색하십시오"
            )
        if filters is not None and not isinstance(filters, Mapping):
            raise ValueError("filters는 API 필드명과 문자열 값으로 이루어진 객체여야 함")
        if filters and len(filters) > MAX_FILTERS:
            raise ValueError(f"filters는 최대 {MAX_FILTERS}개까지 전달할 수 있음")
        clean_filters: dict[str, str] = {}
        for name, value in (filters or {}).items():
            clean_name = str(name).strip()
            if not _FILTER_NAME_PATTERN.fullmatch(clean_name):
                raise ValueError(f"허용되지 않는 API 필드명임: {clean_name[:80]}")
            if not isinstance(value, str):
                raise ValueError(f"{clean_name} 값은 문자열이어야 함")
            if len(value) > 500:
                raise ValueError(f"{clean_name} 값은 500자 이하여야 함")
            clean_filters[clean_name] = value.strip()

        return await _request(
            clean_id,
            page_no=page_no,
            num_of_rows=num_of_rows,
            filters=clean_filters,
        )
    except Exception as exc:
        return error_result(
            exc,
            service_id=service_id,
            page_no=max(page_no, 1),
            num_of_rows=min(max(num_of_rows, 1), MAX_ROWS),
            items=[],
            total_count=0,
        )


@mcp.tool()
async def search_food_raw_material_codes(
    raw_material_name: str,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """식품원재료코드(I2520)에서 원재료명이나 대표 원재료명으로 검색함"""
    clean_name = raw_material_name.strip()
    if not clean_name:
        return error_result(
            ValueError("raw_material_name을 입력해야 함"),
            service_id="I2520",
            items=[],
            total_count=0,
        )
    try:
        return await _request(
            "I2520",
            page_no=page_no,
            num_of_rows=num_of_rows,
            filters={"RPRSNT_RAWMTRL_NM": clean_name},
        )
    except Exception as exc:
        return error_result(
            exc,
            service_id="I2520",
            page_no=max(page_no, 1),
            num_of_rows=min(max(num_of_rows, 1), MAX_ROWS),
            items=[],
            total_count=0,
        )


@mcp.tool()
async def search_food_recipes(
    recipe_name: str | None = None,
    ingredient_keyword: str | None = None,
    category: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 20,
) -> dict[str, Any]:
    """조리식품 레시피 DB(COOKRCP01)를 메뉴명, 재료, 요리종류로 검색함"""
    try:
        filters = {
            key: value.strip()
            for key, value in {
                "RCP_NM": recipe_name,
                "RCP_PARTS_DTLS": ingredient_keyword,
                "RCP_PAT2": category,
            }.items()
            if value and value.strip()
        }
        return await _request(
            "COOKRCP01",
            page_no=page_no,
            num_of_rows=num_of_rows,
            filters=filters,
        )
    except Exception as exc:
        return error_result(
            exc,
            service_id="COOKRCP01",
            page_no=max(page_no, 1),
            num_of_rows=min(max(num_of_rows, 1), MAX_ROWS),
            items=[],
            total_count=0,
        )


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
    """식품 품목제조보고(I1250) 등록 내역을 제품명이나 품목제조보고번호로 조회함"""
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
