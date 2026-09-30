# =============================================================================
# 파일명: address.py
# 경로: connectors/mcp_platform/servers/address.py
# 목적: 행정안전부 도로명주소 및 행정표준 연동을 통해 주소 검색 및 관할 구역 코드를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""행정안전부 도로명주소 및 행정표준 연동을 통해 주소 검색 및 관할 구역 코드를 제공함"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import error_result

mcp = FastMCP("행정안전부 도로명주소 및 행정구역 표준 서비스")

ADDRESS_BASE_URL = "https://business.juso.go.kr/addrlink/addrLinkApi.do"
JUSO_CONFIRM_KEY = os.getenv("JUSO_API_KEY", os.getenv("DATA_GO_API_KEY", "dev_test_key"))


@mcp.tool()
async def search_address(
    keyword: str,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> dict[str, Any]:
    """도로명 또는 건물명 키워드로 표준 도로명주소, 지번, 우편번호 목록을 조회함

    Args:
        keyword: 검색할 도로명, 건물명, 지번 주소 키워드임 (예: 테헤란로 152, 판교역로 166)
        page_no: 페이지 번호임
        num_of_rows: 페이지당 건수임 (기본 10건, 최대 100건)

    Returns:
        정제된 도로명주소, 지번주소, 우편번호(5자리), 행정구역코드 목록 객체임
    """
    clean_keyword = keyword.strip()
    if not clean_keyword:
        return {"success": False, "error": "keyword 매개변수가 필수임", "items": []}

    cache_key = api_cache.make_key("juso_search", kw=clean_keyword, p=page_no, rows=num_of_rows)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    params = {
        "confmKey": JUSO_CONFIRM_KEY,
        "currentPage": page_no,
        "countPerPage": min(max(num_of_rows, 1), 100),
        "keyword": clean_keyword,
        "resultType": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(ADDRESS_BASE_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", {})
            common = results.get("common", {})
            error_code = common.get("errorCode")

            if error_code != "0":
                return {
                    "success": False,
                    "error": common.get("errorMessage", "주소 검색 오류 발생함"),
                    "error_code": error_code,
                    "items": [],
                }

            items = [
                {
                    "road_address": j.get("roadAddr"),
                    "jibun_address": j.get("jibunAddr"),
                    "zip_code": j.get("zipNo"),
                    "building_name": j.get("bdNm"),
                    "sido": j.get("siNm"),
                    "sigungu": j.get("sggNm"),
                    "emd_name": j.get("emdNm"),
                    "adm_code": j.get("admCd"),
                }
                for j in results.get("juso", [])
            ]

            result = {
                "success": True,
                "total_count": int(common.get("totalCount", len(items))),
                "page_no": int(common.get("currentPage", page_no)),
                "items": items,
            }
            api_cache.set(cache_key, result, ttl_seconds=3600)
            return result
    except Exception as exc:
        return error_result(exc, success=False, total_count=0, items=[])


@mcp.tool()
async def get_administrative_district(
    address: str,
) -> dict[str, Any]:
    """주소 문자열을 분석하여 광역시도, 시군구, 읍면동 및 관할 행정구역 코드를 분리함

    Args:
        address: 분석할 주소 텍스트임

    Returns:
        시도, 시군구, 법정동/행정동 구조화 매핑 객체임
    """
    clean_addr = address.strip()
    if not clean_addr:
        return {"success": False, "error": "address 매개변수가 필수임"}

    # 1단계: 검색 API를 통해 정규화
    search_res = await search_address(clean_addr, page_no=1, num_of_rows=1)
    if search_res.get("success") and search_res.get("items"):
        top = search_res["items"][0]
        return {
            "success": True,
            "sido": top.get("sido"),
            "sigungu": top.get("sigungu"),
            "emd_name": top.get("emd_name"),
            "adm_code": top.get("adm_code"),
            "road_address": top.get("road_address"),
            "zip_code": top.get("zip_code"),
        }

    # API 미응답 시 휴리스틱 분리
    parts = clean_addr.split()
    sido = parts[0] if len(parts) > 0 else ""
    sigungu = parts[1] if len(parts) > 1 else ""
    emd = parts[2] if len(parts) > 2 else ""

    return {
        "success": True,
        "sido": sido,
        "sigungu": sigungu,
        "emd_name": emd,
        "adm_code": None,
        "road_address": clean_addr,
        "zip_code": None,
    }


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
