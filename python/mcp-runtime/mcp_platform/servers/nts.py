"""MCP server for the National Tax Service business verification API."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..core.common import DataGoError, error_result, service_key

mcp = FastMCP("NTS Business Verification")
BASE_URL = "https://api.odcloud.kr/api/nts-businessman/v1"


def _clean_number(value: str) -> str:
    return value.replace("-", "").strip()


def _status_view(item: dict[str, Any]) -> dict[str, Any]:
    result = {
        "business_number": item.get("b_no"),
        "status": item.get("b_stt"),
        "status_code": item.get("b_stt_cd"),
        "tax_type": item.get("tax_type"),
        "tax_type_code": item.get("tax_type_cd"),
    }
    optional = {
        "end_date": "end_dt",
        "utcc_yn": "utcc_yn",
        "tax_type_change_date": "tax_type_change_dt",
        "invoice_apply_date": "invoice_apply_dt",
        "rbf_tax_type": "rbf_tax_type",
        "rbf_tax_type_code": "rbf_tax_type_cd",
    }
    for output_name, source_name in optional.items():
        if item.get(source_name):
            result[output_name] = item[source_name]
    return result


async def _post(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    # Keep POST separate from the shared GET helper; the public API requires a JSON body.
    import httpx

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        try:
            response = await client.post(
                f"{BASE_URL}/{endpoint}",
                params={"serviceKey": service_key(), "returnType": "JSON"},
                json=body,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise DataGoError(f"HTTP {exc.response.status_code}: {exc.response.text[:500]}") from exc
        except httpx.RequestError as exc:
            raise DataGoError(f"Could not reach NTS API: {exc}") from exc
        except ValueError as exc:
            raise DataGoError(f"NTS API returned invalid JSON: {exc}") from exc
    if data.get("status_code") not in {None, "OK"}:
        raise DataGoError(f"NTS API error: {data.get('status_code')}")
    return data


def _business_payload(
    business_number: str,
    start_date: str,
    representative_name: str,
    representative_name2: str | None = None,
    business_name: str | None = None,
    corp_number: str | None = None,
    business_sector: str | None = None,
    business_type: str | None = None,
    business_address: str | None = None,
) -> dict[str, Any]:
    return {
        "b_no": _clean_number(business_number),
        "start_dt": start_date.replace("-", ""),
        "p_nm": representative_name,
        "p_nm2": representative_name2 or "",
        "b_nm": business_name or "",
        "corp_no": _clean_number(corp_number) if corp_number else "",
        "b_sector": business_sector or "",
        "b_type": business_type or "",
        "b_adr": business_address or "",
    }


@mcp.tool()
async def validate_business(
    business_number: str,
    start_date: str,
    representative_name: str,
    representative_name2: str | None = None,
    business_name: str | None = None,
    corp_number: str | None = None,
    business_sector: str | None = None,
    business_type: str | None = None,
    business_address: str | None = None,
) -> dict[str, Any]:
    """사업자등록정보의 진위 여부를 확인합니다."""
    number = _clean_number(business_number)
    date = start_date.replace("-", "")
    if len(number) != 10 or not number.isdigit():
        return {"error": "사업자등록번호는 10자리 숫자여야 합니다.", "business_number": number}
    if len(date) != 8 or not date.isdigit():
        return {"error": "개업일자는 YYYYMMDD 형식이어야 합니다.", "start_date": date}
    if corp_number and (len(_clean_number(corp_number)) != 13 or not _clean_number(corp_number).isdigit()):
        return {"error": "법인등록번호는 13자리 숫자여야 합니다.", "corp_number": _clean_number(corp_number)}
    try:
        payload = await _post("validate", {"businesses": [_business_payload(
            number, date, representative_name, representative_name2, business_name,
            corp_number, business_sector, business_type, business_address,
        )]})
        item = (payload.get("data") or [{}])[0]
        request_param = item.get("request_param") or {}
        status = item.get("status")
        return {
            "business_number": item.get("b_no", number),
            "valid": item.get("valid"),
            "valid_msg": item.get("valid_msg") or ("일치" if item.get("valid") == "01" else "확인할 수 없습니다"),
            "status": status,
            "request_param": request_param,
        }
    except Exception as exc:
        return error_result(exc, business_number=number)


@mcp.tool()
async def check_business_status(business_numbers: str) -> dict[str, Any]:
    """쉼표로 구분한 사업자등록번호의 현재 상태를 조회합니다."""
    numbers = [_clean_number(value) for value in business_numbers.split(",")]
    invalid = [value for value in numbers if len(value) != 10 or not value.isdigit()]
    if invalid:
        return {"error": f"잘못된 사업자등록번호: {', '.join(invalid)}", "hint": "10자리 숫자를 입력하세요."}
    if len(numbers) > 100:
        return {"error": "한 번에 최대 100개까지 조회할 수 있습니다."}
    try:
        payload = await _post("status", {"b_no": numbers})
        return {
            "request_count": payload.get("request_cnt", len(numbers)),
            "match_count": payload.get("match_cnt", 0),
            "businesses": [_status_view(item) for item in payload.get("data", [])],
        }
    except Exception as exc:
        return error_result(exc, business_numbers=numbers)


@mcp.tool()
async def batch_validate_businesses(businesses_json: str) -> dict[str, Any]:
    """JSON 배열에 담긴 여러 사업자등록정보를 한 번에 검증합니다."""
    try:
        raw = json.loads(businesses_json)
    except json.JSONDecodeError as exc:
        return {"error": f"JSON 파싱 오류: {exc}", "hint": "배열 JSON을 입력하세요."}
    if not isinstance(raw, list):
        return {"error": "입력은 배열이어야 합니다.", "hint": "[{...}, {...}] 형식을 사용하세요."}
    if len(raw) > 100:
        return {"error": "한 번에 최대 100개까지 진위확인할 수 있습니다."}
    businesses: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not all(key in item for key in ("b_no", "start_dt", "p_nm")):
            return {"error": f"인덱스 {index}: b_no, start_dt, p_nm이 필요합니다."}
        businesses.append({**item, "b_no": _clean_number(str(item["b_no"])), "start_dt": str(item["start_dt"]).replace("-", "")})
    try:
        payload = await _post("validate", {"businesses": businesses})
        results = []
        for item in payload.get("data", []):
            result = {
                "business_number": item.get("b_no"),
                "valid": item.get("valid"),
                "valid_msg": item.get("valid_msg") or ("일치" if item.get("valid") == "01" else "확인할 수 없습니다"),
            }
            if item.get("status"):
                result["status"] = item["status"]
            results.append(result)
        return {
            "request_count": payload.get("request_cnt", len(businesses)),
            "valid_count": payload.get("valid_cnt", 0),
            "results": results,
        }
    except Exception as exc:
        return error_result(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
