"""MCP server for the Public Procurement Service (나라장터) APIs."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.common import as_list, error_result, get_json, int_value, response_body, service_key

mcp = FastMCP("나라장터 공공데이터개방표준서비스")
BASE_URL = "http://apis.data.go.kr/1230000/ao/PubDataOpnStdService"


def format_datetime_for_api(value: str | None = None, *, end: bool = False) -> str:
    """Convert a date or minute-precision timestamp to YYYYMMDDHHMM."""
    if not value:
        return datetime.now().strftime("%Y%m%d2359" if end else "%Y%m%d0000")
    cleaned = value.replace("-", "").replace(":", "").replace(" ", "")
    if len(cleaned) == 8:
        return cleaned + ("2359" if end else "0000")
    if len(cleaned) == 12 and cleaned.isdigit():
        return cleaned
    raise ValueError(f"잘못된 날짜/시간 형식: {value}")


def parse_business_type(value: str) -> str:
    return {"물품": "1", "외자": "2", "공사": "3", "용역": "5"}.get(value, value)


def _items(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in as_list(body.get("items")) if isinstance(item, dict)]


async def _request(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    payload = await get_json(
        f"{BASE_URL}/{endpoint}",
        params={"ServiceKey": service_key(), "type": "json", **params},
    )
    return response_body(payload)


def _result(body: dict[str, Any], *, page_no: int, num_of_rows: int, **extra: Any) -> dict[str, Any]:
    return {
        "success": True,
        "items": _items(body),
        "total_count": int_value(body.get("totalCount"), 0),
        "page_no": int_value(body.get("pageNo"), page_no),
        "num_of_rows": int_value(body.get("numOfRows"), num_of_rows),
        **extra,
    }


@mcp.tool()
async def search_bid_announcements(
    start_date: str | None = None,
    end_date: str | None = None,
    num_of_rows: int = 10,
    page_no: int = 1,
) -> dict[str, Any]:
    """지정한 기간의 나라장터 입찰공고를 조회합니다."""
    try:
        start = format_datetime_for_api(start_date)
        end = format_datetime_for_api(end_date or start_date, end=True)
        body = await _request(
            "getDataSetOpnStdBidPblancInfo",
            {"bidNtceBgnDt": start, "bidNtceEndDt": end, "numOfRows": min(max(num_of_rows, 1), 999), "pageNo": page_no},
        )
        return _result(body, page_no=page_no, num_of_rows=num_of_rows, search_period=f"{start[:8]} ~ {end[:8]}")
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
    """나라장터 낙찰정보를 업무구분별로 조회합니다."""
    try:
        code = parse_business_type(business_type)
        if start_date:
            start = format_datetime_for_api(start_date)
            end = format_datetime_for_api(end_date or start_date, end=True)
        else:
            finish = datetime.now()
            start = (finish - timedelta(days=7)).strftime("%Y%m%d0000")
            end = finish.strftime("%Y%m%d2359")
        body = await _request(
            "getDataSetOpnStdScsbidInfo",
            {"bsnsDivCd": code, "opengBgnDt": start, "opengEndDt": end, "numOfRows": min(max(num_of_rows, 1), 999), "pageNo": page_no},
        )
        names = {"1": "물품", "2": "외자", "3": "공사", "5": "용역"}
        return _result(body, page_no=page_no, num_of_rows=num_of_rows, business_type=names.get(code, code), search_period=f"{start[:8]} ~ {end[:8]}")
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
    """나라장터 계약정보를 기관과 기간으로 조회합니다."""
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
        return _result(body, page_no=page_no, num_of_rows=num_of_rows, search_period=f"{start} ~ {end}", institution_filter=filters)
    except Exception as exc:
        return error_result(exc, success=False, items=[], total_count=0, page_no=page_no, num_of_rows=num_of_rows)


@mcp.tool()
async def get_bid_detail(bid_notice_no: str) -> dict[str, Any]:
    """최근 공고에서 입찰공고번호에 해당하는 상세 항목을 찾습니다."""
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
                return {"success": True, "data": item, "message": f"입찰공고번호 {bid_notice_no}의 상세정보"}
        return {"success": False, "error": f"입찰공고번호 {bid_notice_no}를 찾을 수 없습니다", "data": None}
    except Exception as exc:
        return error_result(exc, success=False, data=None)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
