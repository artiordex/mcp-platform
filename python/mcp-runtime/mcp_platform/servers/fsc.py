"""MCP server for Financial Services Commission corporate statements."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.common import as_list, get_json, int_value, response_body, service_key

mcp = FastMCP("FSC Financial Information")
BASE_URL = "http://apis.data.go.kr/1160100/service/GetFinaStatInfoService_V2"


def _number(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _amount(value: Any, currency: str = "KRW") -> str:
    number = _number(value)
    if number is None:
        return "N/A"
    absolute = abs(number)
    if absolute >= Decimal("1000000000000"):
        text = f"{number / Decimal('1000000000000'):,.2f}조"
    elif absolute >= Decimal("100000000"):
        text = f"{number / Decimal('100000000'):,.2f}억"
    elif absolute >= Decimal("10000"):
        text = f"{number / Decimal('10000'):,.0f}만"
    else:
        text = f"{number:,.0f}"
    return f"{text}원" if currency == "KRW" else f"{text} {currency}"


def _validate(crno: str | None, biz_year: str | None) -> tuple[str | None, str | None]:
    clean_crno = crno.replace("-", "").strip() if crno else None
    clean_year = str(biz_year).strip() if biz_year else None
    if clean_crno is not None and (len(clean_crno) != 13 or not clean_crno.isdigit()):
        raise ValueError("법인등록번호는 13자리 숫자여야 합니다.")
    if clean_year is not None and (len(clean_year) != 4 or not clean_year.isdigit() or not 1900 <= int(clean_year) <= 2100):
        raise ValueError("사업연도는 4자리 숫자여야 합니다.")
    return clean_crno, clean_year


async def _query(endpoint: str, crno: str | None, biz_year: str | None, page_no: int, num_of_rows: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    clean_crno, clean_year = _validate(crno, biz_year)
    params: dict[str, Any] = {
        "serviceKey": service_key(),
        "pageNo": max(page_no, 1),
        "numOfRows": min(max(num_of_rows, 1), 100),
        "resultType": "json",
    }
    if clean_crno:
        params["crno"] = clean_crno
    if clean_year:
        params["bizYear"] = clean_year
    payload = await get_json(f"{BASE_URL}/{endpoint}", params=params)
    body = response_body(payload)
    return body, [item for item in as_list(body.get("items")) if isinstance(item, dict)]


def _header(item: dict[str, Any]) -> list[str]:
    return [
        f"법인등록번호: {item.get('crno') or 'N/A'}",
        f"사업연도: {item.get('bizYear') or 'N/A'}",
        f"기준일자: {item.get('basDt') or 'N/A'}",
        f"재무제표구분: {item.get('fnclDcdNm') or item.get('fnclDcd') or 'N/A'}",
    ]


def _summary_text(body: dict[str, Any], items: list[dict[str, Any]]) -> str:
    if not items:
        return "조회된 요약 재무제표가 없습니다. 법인등록번호와 사업연도를 확인해주세요."
    lines = [f"📊 요약 재무제표 조회 결과 (총 {int_value(body.get('totalCount'))}건)"]
    for item in items:
        currency = item.get("curCd") or "KRW"
        lines.extend([
            "", "=" * 50, *_header(item), "", "주요 재무지표:",
            f"  • 매출액: {_amount(item.get('enpSaleAmt'), currency)}",
            f"  • 영업이익: {_amount(item.get('enpBzopPft'), currency)}",
            f"  • 당기순이익: {_amount(item.get('enpCrtmNpf'), currency)}",
            f"  • 총자산: {_amount(item.get('enpTastAmt'), currency)}",
            f"  • 총부채: {_amount(item.get('enpTdbtAmt'), currency)}",
            f"  • 총자본: {_amount(item.get('enpTcptAmt'), currency)}",
            f"  • 자본금: {_amount(item.get('enpCptlAmt'), currency)}",
            f"  • 부채비율: {item.get('fnclDebtRto') or 'N/A'}%",
        ])
    return "\n".join(lines)


def _account_text(title: str, body: dict[str, Any], items: list[dict[str, Any]]) -> str:
    if not items:
        return f"조회된 {title}가 없습니다. 법인등록번호와 사업연도를 확인해주세요."
    lines = [f"{title} 조회 결과 (총 {int_value(body.get('totalCount'))}건)"]
    current: str | None = None
    for item in items:
        key = str(item.get("crno") or "")
        if key != current:
            current = key
            lines.extend(["", "=" * 50, *_header(item), "", "계정과목별 금액:"])
        currency = item.get("curCd") or "KRW"
        lines.extend([
            f"\n  [{item.get('acitNm') or item.get('acitId') or 'N/A'}]",
            f"    • 당기: {_amount(item.get('crtmAcitAmt'), currency)}",
            f"    • 전기: {_amount(item.get('pvtrAcitAmt'), currency)}",
        ])
        current_amount = _number(item.get("crtmAcitAmt"))
        previous_amount = _number(item.get("pvtrAcitAmt"))
        if current_amount is not None and previous_amount is not None:
            change = current_amount - previous_amount
            percentage = (change / abs(previous_amount) * 100) if previous_amount else Decimal(0)
            lines.append(f"    • 증감: {_amount(change, currency)} ({percentage:+.1f}%)")
    return "\n".join(lines)


@mcp.tool()
async def get_summary_financial_statement(
    crno: str | None = None,
    biz_year: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> str:
    """기업의 요약 재무제표를 조회합니다."""
    try:
        body, items = await _query("getSummFinaStat_V2", crno, biz_year, page_no, num_of_rows)
        return _summary_text(body, items)
    except Exception as exc:
        return f"재무정보 조회 오류: {exc}"


@mcp.tool()
async def get_balance_sheet(
    crno: str | None = None,
    biz_year: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> str:
    """기업의 재무상태표를 조회합니다."""
    try:
        body, items = await _query("getBs_V2", crno, biz_year, page_no, num_of_rows)
        return _account_text("📋 재무상태표", body, items)
    except Exception as exc:
        return f"재무정보 조회 오류: {exc}"


@mcp.tool()
async def get_income_statement(
    crno: str | None = None,
    biz_year: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> str:
    """기업의 손익계산서를 조회합니다."""
    try:
        body, items = await _query("getIncoStat_V2", crno, biz_year, page_no, num_of_rows)
        return _account_text("💹 손익계산서", body, items)
    except Exception as exc:
        return f"재무정보 조회 오류: {exc}"


@mcp.tool()
async def search_company_financial_info(crno: str, biz_year: str) -> str:
    """법인등록번호와 사업연도로 주요 재무정보를 통합 조회합니다."""
    try:
        clean_crno, clean_year = _validate(crno, biz_year)
        summary_body, summary_items = await _query("getSummFinaStat_V2", clean_crno, clean_year, 1, 5)
        balance_body, balance_items = await _query("getBs_V2", clean_crno, clean_year, 1, 10)
        income_body, income_items = await _query("getIncoStat_V2", clean_crno, clean_year, 1, 10)
        sections = [_summary_text(summary_body, summary_items)]
        if balance_items:
            sections.append(_account_text("📋 재무상태표 주요 항목", balance_body, balance_items[:5]))
        if income_items:
            sections.append(_account_text("💹 손익계산서 주요 항목", income_body, income_items[:5]))
        return "\n\n".join(sections)
    except Exception as exc:
        return f"재무정보 통합 조회 오류: {exc}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
