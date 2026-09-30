# =============================================================================
# 파일명: fsc.py
# 경로: connectors/mcp_platform/servers/fsc.py
# 목적: 금융위원회 기업 재무제표·재무상태표·손익계산서 데이터 조회 도구를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""금융위원회 기업 재무제표·재무상태표·손익계산서 데이터 조회 도구를 제공함"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import as_list, get_json, int_value, response_body, service_key

mcp = FastMCP("FSC Financial Information")
BASE_URL = "http://apis.data.go.kr/1160100/service/GetFinaStatInfoService_V2"


def _number(value: Any) -> Decimal | None:
    """문자열 금액을 Decimal로 변환함"""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _amount(value: Any, currency: str = "KRW") -> str:
    """금액 단위를 조·억·만 원 단위로 포맷팅함"""
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
    """법인등록번호와 사업연도의 형식을 검증함"""
    clean_crno = crno.replace("-", "").strip() if crno else None
    clean_year = str(biz_year).strip() if biz_year else None
    if clean_crno is not None and (len(clean_crno) != 13 or not clean_crno.isdigit()):
        raise ValueError("법인등록번호는 13자리 숫자여야 함")
    if clean_year is not None and (len(clean_year) != 4 or not clean_year.isdigit() or not 1900 <= int(clean_year) <= 2100):
        raise ValueError("사업연도는 4자리 연도 숫자여야 함")
    return clean_crno, clean_year


async def _query(
    endpoint: str,
    crno: str | None,
    biz_year: str | None,
    page_no: int,
    num_of_rows: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """금융위 재무정보 API를 호출하고 파싱 결과를 반환함"""
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
    """기본 법인 메타데이터 헤더 라인을 구성함"""
    return [
        f"법인등록번호: {item.get('crno') or 'N/A'}",
        f"사업연도: {item.get('bizYear') or 'N/A'}",
        f"기준일자: {item.get('basDt') or 'N/A'}",
        f"재무제표구분: {item.get('fnclDcdNm') or item.get('fnclDcd') or 'N/A'}",
    ]


def _summary_text(body: dict[str, Any], items: list[dict[str, Any]]) -> str:
    """요약 재무제표 텍스트 블록을 구성함"""
    if not items:
        return "조회된 요약 재무제표가 없음. 법인등록번호와 사업연도를 확인해야 함"
    lines = [f"[요약 재무제표 조회 결과] (총 {int_value(body.get('totalCount'))}건)"]
    for item in items:
        currency = item.get("curCd") or "KRW"
        lines.extend([
            "", "=" * 50, *_header(item), "", "주요 재무지표:",
            f"  - 매출액: {_amount(item.get('enpSaleAmt'), currency)}",
            f"  - 영업이익: {_amount(item.get('enpBzopPft'), currency)}",
            f"  - 당기순이익: {_amount(item.get('enpCrtmNpf'), currency)}",
            f"  - 총자산: {_amount(item.get('enpTastAmt'), currency)}",
            f"  - 총부채: {_amount(item.get('enpTdbtAmt'), currency)}",
            f"  - 총자본: {_amount(item.get('enpTcptAmt'), currency)}",
            f"  - 자본금: {_amount(item.get('enpCptlAmt'), currency)}",
            f"  - 부채비율: {item.get('fnclDebtRto') or 'N/A'}%",
        ])
    return "\n".join(lines)


def _account_text(title: str, body: dict[str, Any], items: list[dict[str, Any]]) -> str:
    """계정과목별 상세 명세 텍스트 블록을 구성함"""
    if not items:
        return f"조회된 {title} 항목이 없음. 법인등록번호와 사업연도를 확인해야 함"
    lines = [f"[{title} 조회 결과] (총 {int_value(body.get('totalCount'))}건)"]
    current: str | None = None
    for item in items:
        key = str(item.get("crno") or "")
        if key != current:
            current = key
            lines.extend(["", "=" * 50, *_header(item), "", "계정과목별 금액:"])
        currency = item.get("curCd") or "KRW"
        lines.extend([
            f"\n  [{item.get('acitNm') or item.get('acitId') or 'N/A'}]",
            f"    - 당기: {_amount(item.get('crtmAcitAmt'), currency)}",
            f"    - 전기: {_amount(item.get('pvtrAcitAmt'), currency)}",
        ])
        current_amount = _number(item.get("crtmAcitAmt"))
        previous_amount = _number(item.get("pvtrAcitAmt"))
        if current_amount is not None and previous_amount is not None:
            change = current_amount - previous_amount
            percentage = (change / abs(previous_amount) * 100) if previous_amount else Decimal(0)
            lines.append(f"    - 증감: {_amount(change, currency)} ({percentage:+.1f}%)")
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# MCP Tools (금융위 재무정보 도구)
# -----------------------------------------------------------------------------


@mcp.tool()
async def get_summary_financial_statement(
    crno: str | None = None,
    biz_year: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> str:
    """기업의 요약 재무제표(매출액, 영업이익, 총자산, 부채비율 등)를 조회함"""
    cache_key = api_cache.make_key("fsc_summary", crno=crno, year=biz_year, page=page_no)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return str(cached)

    try:
        body, items = await _query("getSummFinaStat_V2", crno, biz_year, page_no, num_of_rows)
        res = _summary_text(body, items)
        api_cache.set(cache_key, res, ttl_seconds=600)
        return res
    except Exception as exc:
        return f"재무정보 조회 오류 발생함: {exc}"


@mcp.tool()
async def get_balance_sheet(
    crno: str | None = None,
    biz_year: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> str:
    """기업의 상세 재무상태표(자산·부채·자본 세부 계정과목)를 조회함"""
    try:
        body, items = await _query("getBs_V2", crno, biz_year, page_no, num_of_rows)
        return _account_text("재무상태표", body, items)
    except Exception as exc:
        return f"재무정보 조회 오류 발생함: {exc}"


@mcp.tool()
async def get_income_statement(
    crno: str | None = None,
    biz_year: str | None = None,
    page_no: int = 1,
    num_of_rows: int = 10,
) -> str:
    """기업의 상세 손익계산서(매출원가, 판관비, 당기순이익 계정과목)를 조회함"""
    try:
        body, items = await _query("getIncoStat_V2", crno, biz_year, page_no, num_of_rows)
        return _account_text("손익계산서", body, items)
    except Exception as exc:
        return f"재무정보 조회 오류 발생함: {exc}"


@mcp.tool()
async def search_company_financial_info(crno: str, biz_year: str) -> str:
    """법인등록번호와 사업연도로 요약 재무제표와 주요 상태표·손익 항목을 종합 조회함"""
    cache_key = api_cache.make_key("fsc_all", crno=crno, year=biz_year)
    cached = api_cache.get(cache_key)
    if cached is not None:
        return str(cached)

    try:
        clean_crno, clean_year = _validate(crno, biz_year)
        summary_body, summary_items = await _query("getSummFinaStat_V2", clean_crno, clean_year, 1, 5)
        balance_body, balance_items = await _query("getBs_V2", clean_crno, clean_year, 1, 10)
        income_body, income_items = await _query("getIncoStat_V2", clean_crno, clean_year, 1, 10)
        sections = [_summary_text(summary_body, summary_items)]
        if balance_items:
            sections.append(_account_text("재무상태표 주요 항목", balance_body, balance_items[:5]))
        if income_items:
            sections.append(_account_text("손익계산서 주요 항목", income_body, income_items[:5]))
        res = "\n\n".join(sections)
        api_cache.set(cache_key, res, ttl_seconds=600)
        return res
    except Exception as exc:
        return f"재무정보 통합 조회 오류 발생함: {exc}"


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
