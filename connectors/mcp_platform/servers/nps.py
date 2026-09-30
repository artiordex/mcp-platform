# =============================================================================
# 파일명: nps.py
# 경로: connectors/mcp_platform/servers/nps.py
# 목적: 국민연금 가입 사업장 정보, 고용 인원, 추정 급여 및 자격변동 내역을 조회함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""국민연금 가입 사업장 정보, 고용 인원, 추정 급여 및 자격변동 내역을 조회함"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import as_list, error_result, get_json, int_value, response_body, service_key

mcp = FastMCP("NPS Business Enrollment")
BASE_URL = "http://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2"


def _camel(name: str) -> str:
    """스네이크 케이스 문자열을 카멜 케이스로 변환함"""
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _item_fields(item: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
    """사업장 정보 필드를 매핑하고 가입자 수를 정수형으로 정제함"""
    names = (
        [
            "data_crt_ym",
            "seq",
            "wkpl_nm",
            "bzowr_rgst_no",
            "wkpl_road_nm_dtl_addr",
            "wkpl_jnng_stcd",
            "wkpl_styl_dvcd",
            "ldong_addr_mgpl_dg_cd",
            "ldong_addr_mgpl_sggu_cd",
            "ldong_addr_mgpl_sggu_emd_cd",
        ]
        if not detail
        else [
            "wkpl_nm",
            "bzowr_rgst_no",
            "wkpl_road_nm_dtl_addr",
            "wkpl_jnng_stcd",
            "ldong_addr_mgpl_dg_cd",
            "ldong_addr_mgpl_sggu_cd",
            "ldong_addr_mgpl_sggu_emd_cd",
            "wkpl_styl_dvcd",
            "wkpl_intp_cd",
            "vldt_vl_krn_nm",
            "adpt_dt",
            "scsn_dt",
            "jnngp_cnt",
            "crrmm_ntc_amt",
        ]
    )
    output: dict[str, Any] = {}
    for name in names:
        output[name] = item.get(_camel(name), item.get(name))
    if output.get("jnngp_cnt") is not None:
        output["jnngp_cnt"] = int_value(output["jnngp_cnt"], 0)
    return output


async def _request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    """국민연금 공공데이터 API를 호출하고 응답 본문을 추출함"""
    query = {"serviceKey": service_key(), "dataType": "json", **params}
    payload = await get_json(f"{BASE_URL}/{endpoint}", params=query)
    return response_body(payload)


def _page(body: dict[str, Any], fallback_page: int, fallback_rows: int) -> dict[str, Any]:
    """페이징 정보를 매핑함"""
    return {
        "page_no": int_value(body.get("pageNo"), fallback_page),
        "num_of_rows": int_value(body.get("numOfRows"), fallback_rows),
        "total_count": int_value(body.get("totalCount"), 0),
    }


# -----------------------------------------------------------------------------
# MCP Tools (국민연금 데이터 도구)
# -----------------------------------------------------------------------------


@mcp.tool()
async def search_business(
    ldong_addr_mgpl_dg_cd: str | None = None,
    ldong_addr_mgpl_sggu_cd: str | None = None,
    ldong_addr_mgpl_sggu_emd_cd: str | None = None,
    wkpl_nm: str | None = None,
    bzowr_rgst_no: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 100,
) -> dict[str, Any]:
    """국민연금 사업장 기본정보를 상호명이나 사업자등록번호 조건으로 조회함"""
    cache_key = api_cache.make_key(
        "nps_search",
        name=wkpl_nm,
        bno=bzowr_rgst_no,
        page=page_no,
        rows=num_of_rows,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        body = await _request(
            "getBassInfoSearchV2",
            {
                _camel(key): value
                for key, value in {
                    "ldong_addr_mgpl_dg_cd": ldong_addr_mgpl_dg_cd,
                    "ldong_addr_mgpl_sggu_cd": ldong_addr_mgpl_sggu_cd,
                    "ldong_addr_mgpl_sggu_emd_cd": ldong_addr_mgpl_sggu_emd_cd,
                    "wkpl_nm": wkpl_nm,
                    "bzowr_rgst_no": bzowr_rgst_no,
                    "page_no": page_no,
                    "num_of_rows": min(max(num_of_rows, 1), 100),
                }.items()
                if value is not None
            },
        )
        page = _page(body, page_no, num_of_rows)
        page["items"] = [_item_fields(item) for item in as_list(body.get("items")) if isinstance(item, dict)]
        page["message"] = f"사업장 {page['total_count']}건을 조회함" if page["items"] else "조회된 사업장이 없음"
        api_cache.set(cache_key, page, ttl_seconds=300)
        return page
    except Exception as exc:
        return error_result(exc, items=[], page_no=page_no, num_of_rows=num_of_rows, total_count=0)


@mcp.tool()
async def get_business_detail(seq: int, page_no: int = 1, num_of_rows: int = 10) -> dict[str, Any]:
    """사업장 식별번호(seq)로 가입자 수 및 추정 월평균 급여를 상세 조회함"""
    cache_key = api_cache.make_key("nps_detail", seq=seq, page=page_no)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        body = await _request(
            "getDetailInfoSearchV2",
            {"seq": seq, "pageNo": page_no, "numOfRows": num_of_rows},
        )
        page = _page(body, page_no, num_of_rows)
        page["items"] = [_item_fields(item, detail=True) for item in as_list(body.get("items")) if isinstance(item, dict)]
        for item in page["items"]:
            try:
                people = int(item.get("jnngp_cnt") or 0)
                amount = int(str(item.get("crrmm_ntc_amt") or 0).replace(",", ""))
                if people > 0 and amount > 0:
                    item["estimated_avg_monthly_salary"] = round(amount / people / 0.09)
                    item["estimated_avg_monthly_salary_note"] = "추정값임 (당월고지금액 기준)"
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        page["message"] = f"사업장 #{seq} 상세정보를 조회함" if page["items"] else f"사업장 #{seq} 정보를 찾지 못함"
        api_cache.set(cache_key, page, ttl_seconds=600)
        return page
    except Exception as exc:
        return error_result(exc, items=[], page_no=page_no, num_of_rows=num_of_rows, total_count=0)


@mcp.tool()
async def get_period_status(
    seq: int,
    data_crt_ym: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> dict[str, Any]:
    """국민연금 사업장의 월별 신규 취득자 및 상실자(퇴사자) 현황을 조회함"""
    try:
        body = await _request(
            "getPdAcctoSttusInfoSearchV2",
            {
                "seq": seq,
                "dataCrtYm": data_crt_ym,
                "pageNo": page_no,
                "numOfRows": num_of_rows,
            },
        )
        page = _page(body, page_no, num_of_rows)
        page["items"] = [
            {
                "nw_acqzr_cnt": int_value(item.get("nwAcqzrCnt"), 0),
                "lss_jnngp_cnt": int_value(item.get("lssJnngpCnt"), 0),
            }
            for item in as_list(body.get("items"))
            if isinstance(item, dict)
        ]
        page["message"] = f"사업장 #{seq} 기간별 자격변동 현황을 조회함"
        return page
    except Exception as exc:
        return error_result(exc, items=[], page_no=page_no, num_of_rows=num_of_rows, total_count=0)


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
