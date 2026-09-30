# =============================================================================
# 파일명: nts.py
# 경로: connectors/mcp_platform/servers/nts.py
# 목적: 국세청 사업자등록 진위확인 및 휴폐업 상태 조회 도구를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""국세청 사업자등록 진위확인 및 휴폐업 상태 조회 도구를 제공함"""

from __future__ import annotations

import json
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import DataGoError, error_result, service_key

mcp = FastMCP("NTS Business Verification")
BASE_URL = "https://api.odcloud.kr/api/nts-businessman/v1"


def _clean_number(value: str) -> str:
    """하이픈을 제거하고 공백을 정돈함"""
    return value.replace("-", "").strip()


def _status_view(item: dict[str, Any]) -> dict[str, Any]:
    """국세청 상태 응답 항목을 표준 형식으로 정제함"""
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
    """국세청 진위확인 API에 비동기 POST 요청을 전송함"""
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
            raise DataGoError(f"국세청 API에 연결할 수 없음: {exc}") from exc
        except ValueError as exc:
            raise DataGoError(f"국세청 API가 유효한 JSON을 반환하지 않음: {exc}") from exc
    if data.get("status_code") not in {None, "OK"}:
        raise DataGoError(f"국세청 API 오류: {data.get('status_code')}")
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
    """국세청 단건 검증용 페이로드를 조립함"""
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


# -----------------------------------------------------------------------------
# MCP Tools (국세청 검증 도구)
# -----------------------------------------------------------------------------


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
    """사업자등록정보(사업자번호, 개업일자, 대표자명 등)의 진위 여부를 대조 검증함"""
    number = _clean_number(business_number)
    date = start_date.replace("-", "")
    if len(number) != 10 or not number.isdigit():
        return {"error": "사업자등록번호는 10자리 숫자여야 함", "business_number": number}
    if len(date) != 8 or not date.isdigit():
        return {"error": "개업일자는 YYYYMMDD 형식이어야 함", "start_date": date}
    if corp_number and (len(_clean_number(corp_number)) != 13 or not _clean_number(corp_number).isdigit()):
        return {"error": "법인등록번호는 13자리 숫자여야 함", "corp_number": _clean_number(corp_number)}

    cache_key = api_cache.make_key(
        "nts_validate",
        bno=number,
        date=date,
        pnm=representative_name,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        payload = await _post("validate", {"businesses": [_business_payload(
            number, date, representative_name, representative_name2, business_name,
            corp_number, business_sector, business_type, business_address,
        )]})
        item = (payload.get("data") or [{}])[0]
        request_param = item.get("request_param") or {}
        status = item.get("status")
        res = {
            "business_number": item.get("b_no", number),
            "valid": item.get("valid"),
            "valid_msg": item.get("valid_msg") or ("일치" if item.get("valid") == "01" else "확인할 수 없음"),
            "status": status,
            "request_param": request_param,
        }
        api_cache.set(cache_key, res, ttl_seconds=600)
        return res
    except Exception as exc:
        return error_result(exc, business_number=number)


@mcp.tool()
async def check_business_status(business_numbers: str) -> dict[str, Any]:
    """쉼표(,)로 구분한 사업자등록번호(최대 100건)의 현재 휴폐업 상태 및 과세유형을 일괄 조회함"""
    numbers = [_clean_number(value) for value in business_numbers.split(",")]
    invalid = [value for value in numbers if len(value) != 10 or not value.isdigit()]
    if invalid:
        return {"error": f"잘못된 사업자등록번호: {', '.join(invalid)}", "hint": "10자리 숫자를 입력해야 함"}
    if len(numbers) > 100:
        return {"error": "한 번에 최대 100개까지만 조회할 수 있음"}

    cache_key = api_cache.make_key("nts_status", numbers=",".join(sorted(numbers)))
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        payload = await _post("status", {"b_no": numbers})
        res = {
            "request_count": payload.get("request_cnt", len(numbers)),
            "match_count": payload.get("match_cnt", 0),
            "businesses": [_status_view(item) for item in payload.get("data", [])],
        }
        api_cache.set(cache_key, res, ttl_seconds=300)
        return res
    except Exception as exc:
        return error_result(exc, business_numbers=numbers)


@mcp.tool()
async def batch_validate_businesses(businesses_json: str) -> dict[str, Any]:
    """JSON 배열에 담긴 복수 사업자등록정보를 한 번에 대조 검증함"""
    try:
        raw = json.loads(businesses_json)
    except json.JSONDecodeError as exc:
        return {"error": f"JSON 파싱 오류: {exc}", "hint": "배열 JSON을 입력해야 함"}
    if not isinstance(raw, list):
        return {"error": "입력값은 배열이어야 함", "hint": "[{...}, {...}] 형식을 사용해야 함"}
    if len(raw) > 100:
        return {"error": "한 번에 최대 100개까지만 진위확인할 수 있음"}

    businesses: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict) or not all(key in item for key in ("b_no", "start_dt", "p_nm")):
            return {"error": f"인덱스 {index}: b_no, start_dt, p_nm 항목이 필수임"}
        businesses.append({
            **item,
            "b_no": _clean_number(str(item["b_no"])),
            "start_dt": str(item["start_dt"]).replace("-", ""),
        })

    try:
        payload = await _post("validate", {"businesses": businesses})
        results = []
        for item in payload.get("data", []):
            result = {
                "business_number": item.get("b_no"),
                "valid": item.get("valid"),
                "valid_msg": item.get("valid_msg") or ("일치" if item.get("valid") == "01" else "확인할 수 없음"),
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
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
