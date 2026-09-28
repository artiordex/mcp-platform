"""MCP server for National Pension Service workplace information."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.common import as_list, error_result, get_json, int_value, response_body, service_key

mcp = FastMCP("NPS Business Enrollment")
BASE_URL = "http://apis.data.go.kr/B552015/NpsBplcInfoInqireServiceV2"


def _camel(name: str) -> str:
    head, *tail = name.split("_")
    return head + "".join(part[:1].upper() + part[1:] for part in tail)


def _item_fields(item: dict[str, Any], *, detail: bool = False) -> dict[str, Any]:
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
    query = {"serviceKey": service_key(), "dataType": "json", **params}
    payload = await get_json(f"{BASE_URL}/{endpoint}", params=query)
    return response_body(payload)


def _page(body: dict[str, Any], fallback_page: int, fallback_rows: int) -> dict[str, Any]:
    return {
        "page_no": int_value(body.get("pageNo"), fallback_page),
        "num_of_rows": int_value(body.get("numOfRows"), fallback_rows),
        "total_count": int_value(body.get("totalCount"), 0),
    }


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
    """국민연금 사업장 기본정보를 조건별로 조회합니다."""
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
        page["message"] = f"Found {page['total_count']} business(es)" if page["items"] else "No businesses found"
        return page
    except Exception as exc:
        return error_result(exc, items=[], page_no=page_no, num_of_rows=num_of_rows, total_count=0)


@mcp.tool()
async def get_business_detail(seq: int, page_no: int = 1, num_of_rows: int = 10) -> dict[str, Any]:
    """식별번호로 국민연금 사업장 상세정보를 조회합니다."""
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
                    item["estimated_avg_monthly_salary_note"] = "추정값 (당월고지금액 기준)"
            except (TypeError, ValueError, ZeroDivisionError):
                pass
        page["message"] = f"Successfully retrieved details for business #{seq}" if page["items"] else f"No details found for business #{seq}"
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
    """국민연금 사업장의 월별 취득·상실 현황을 조회합니다."""
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
        page["message"] = f"Successfully retrieved period status for business #{seq}"
        return page
    except Exception as exc:
        return error_result(exc, items=[], page_no=page_no, num_of_rows=num_of_rows, total_count=0)


def main() -> None:
    # The key is checked when a tool is called so the MCP schema remains discoverable.
    mcp.run()


if __name__ == "__main__":
    main()
