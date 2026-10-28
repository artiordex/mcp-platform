"""나라장터 조달 OpenAPI 작업과 API 메타데이터를 제공함"""

from __future__ import annotations

import json
import os
from typing import Any

from ..core.cache import api_cache
from ..core.common import as_list, int_value, response_body, service_key, get_json


def pps_service_key() -> str:
    """나라장터 전용 별칭을 우선 사용하고 기존 공공데이터 키를 fallback으로 사용함"""
    return os.getenv("NARAMARKET_SERVICE_KEY") or service_key()


API_SERVICES: dict[str, dict[str, Any]] = {
    "public_data_standard": {
        "name": "공공데이터개방표준서비스",
        "base_url": "http://apis.data.go.kr/1230000/ao/PubDataOpnStdService",
        "operations": {
            "getDataSetOpnStdBidPblancInfo": "입찰공고정보 조회",
            "getDataSetOpnStdScsbidInfo": "낙찰정보 조회",
            "getDataSetOpnStdCntrctInfo": "계약정보 조회",
            "getDataSetOpnStdOrderPlanInfo": "발주계획정보 조회",
        },
    },
    "procurement_statistics": {
        "name": "공공조달통계정보서비스",
        "base_url": "http://apis.data.go.kr/1230000/at/PubPrcrmntStatInfoService",
        "operations": {
            "getTotlPubPrcrmntSttus": "전체 공공조달 현황",
            "getInsttDivAccotPrcrmntSttus": "기관구분별 조달 현황",
            "getEntrprsDivAccotPrcrmntSttus": "기업구분별 조달 현황",
            "getCntrctMthdAccotSttus": "계약방법별 현황",
            "getRgnLmtSttus": "지역제한 현황",
            "getRgnDutyCmmnCntrctSttus": "지역의무공동계약 현황",
            "getPrcrmntObjectBsnsObjAccotSttus": "조달목적물별 현황",
            "getDminsttAccotEntrprsDivAccotArslt": "수요기관별 기업구분별 실적",
            "getDminsttAccotCntrctMthdAccotArslt": "수요기관별 계약방법별 실적",
            "getDminsttAccotBsnsObjAccotArslt": "수요기관별 업무대상별 실적",
            "getDminsttAccotSystmTyAccotArslt": "수요기관별 시스템유형별 실적",
            "getPrcrmntEntrprsAccotCntrctMthdAccotArslt": "조달기업별 계약방법별 실적",
            "getPrcrmntEntrprsAccotBsnsObjAccotArslt": "조달기업별 업무대상별 실적",
            "getPrdctIdntNoServcAccotArslt": "품목 및 서비스별 실적",
        },
    },
    "product_list": {
        "name": "조달청 물품목록정보서비스",
        "base_url": "http://apis.data.go.kr/1230000/ao/ThngListInfoService",
        "operations": {
            "getThngGuidanceMapInfo": "물품안내지도 조회",
            "getThngPrdnmLocplcAccotListInfoInfoPrdlstSearch": "품목 목록 조회",
            "getThngPrdnmLocplcAccotListInfoInfoPrdnmSearch": "품명 목록 조회",
            "getThngPrdnmLocplcAccotListInfoInfoLocplcSearch": "소재지 목록 조회",
            "getThngListClChangeHistInfo": "분류변경이력 조회",
            "getLsfgdNdPrdlstChghstlnfoSttus": "품목변경이력 조회",
            "getPrdctClsfcNoUnit2Info": "물품분류 2단위 내역조회",
            "getPrdctClsfcNoUnit4Info": "물품분류 4단위 내역조회",
            "getPrdctClsfcNoUnit6Info": "물품분류 6단위 내역조회",
            "getPrdctClsfcNoUnit8Info": "물품분류 8단위 내역조회",
            "getPrdctClsfcNoUnit10Info": "물품분류 10단위 내역조회",
            "getPrdctClsfcNoChgHstry": "물품분류 변경이력 조회",
        },
    },
    "shopping_mall": {
        "name": "나라장터 종합쇼핑몰 품목정보 서비스",
        "base_url": "http://apis.data.go.kr/1230000/at/ShoppingMallPrdctInfoService",
        "operations": {
            "getMASCntrctPrdctInfoList": "다수공급자계약 품목정보 조회",
            "getUcntrctPrdctInfoList": "일반단가계약 품목정보 조회",
            "getThptyUcntrctPrdctInfoList": "제3자단가계약 품목정보 조회",
            "getDlvrReqInfoList": "납품요구정보 현황 조회",
            "getDlvrReqDtlInfoList": "납품요구상세 현황 조회",
            "getShoppingMallPrdctInfoList": "종합쇼핑몰 품목정보 조회",
            "getVntrPrdctOrderDealDtlsInfoList": "벤처나라 물품 주문거래 조회",
            "getSpcifyPrdlstPrcureInfoList": "특정품목 조달내역 조회",
            "getSpcifyPrdlstPrcureTotList": "특정품목 조달집계 조회",
        },
    },
}

_RESERVED_PARAMETER_NAMES = {"servicekey", "numofrows", "pageno", "type"}
_SUMMARY_FIELDS: dict[str, tuple[str, ...]] = {
    "public_data_standard": (
        "bidNtceNo", "bidNtceNm", "ntceKindNm", "bidNtceDt", "bidClseDt",
        "opengDt", "cntrctCnclsDate", "cntrctamt", "sucsfbidAmt", "presmptPrce",
    ),
    "procurement_statistics": (
        "bssMnth", "statDivNm", "bssYearAmt", "dminsttNm", "entrprsNm",
        "cntrctMthdNm", "bsnsObjNm", "prdctClsfcNm",
    ),
    "product_list": (
        "prdctClsfcNo", "prdctClsfcNoNm", "prdctIdntNo", "dtilPrdctClsfcNo",
        "mnfctCorpNm", "rgnNm", "chgDt",
    ),
    "shopping_mall": (
        "prdctIdntNo", "prdctClsfcNoNm", "cntrctCorpNm", "cntrctUntprc",
        "rgstDt", "chgDt", "dlvrReqNo", "dminsttNm", "prcrmntDiv",
    ),
}


def get_all_api_services_info() -> dict[str, Any]:
    """지원 서비스, 엔드포인트, 오퍼레이션과 총 개수를 반환함"""
    services = {
        service_type: {
            "name": service["name"],
            "base_url": service["base_url"],
            "operations_count": len(service["operations"]),
            "operations": [
                {"name": name, "description": description}
                for name, description in service["operations"].items()
            ],
        }
        for service_type, service in API_SERVICES.items()
    }
    return {
        "success": True,
        "services": services,
        "total_services": len(services),
        "total_operations": sum(service["operations_count"] for service in services.values()),
    }


def get_api_operations(service_type: str) -> dict[str, Any]:
    """한 서비스에서 사용할 수 있는 오퍼레이션을 반환함"""
    service = API_SERVICES.get(service_type)
    if service is None:
        return {
            "success": False,
            "service_type": service_type,
            "error": f"지원하지 않는 서비스임. 선택 가능: {', '.join(API_SERVICES)}",
        }
    return {
        "success": True,
        "service_type": service_type,
        "name": service["name"],
        "base_url": service["base_url"],
        "available_operations": [
            {"name": name, "description": description}
            for name, description in service["operations"].items()
        ],
        "total_operations": len(service["operations"]),
    }


def _summary_value(value: Any, *, max_chars: int = 500) -> Any:
    """응답 요약 값이 단일 필드만으로 컨텍스트 한도를 넘지 않도록 제한함"""
    if isinstance(value, str):
        return value if len(value) <= max_chars else value[:max_chars] + "…"
    if isinstance(value, (dict, list)):
        rendered = json.dumps(value, ensure_ascii=False, default=str)
        return value if len(rendered) <= max_chars else rendered[:max_chars] + "…"
    return value


async def call_api(
    service_type: str,
    operation: str,
    parameters: dict[str, Any] | None = None,
    *,
    num_of_rows: int = 5,
    page_no: int = 1,
) -> dict[str, Any]:
    """허용된 나라장터 OpenAPI 오퍼레이션을 조회하고 응답을 정규화함"""
    service = API_SERVICES.get(service_type)
    if service is None:
        return {
            "success": False,
            "service_type": service_type,
            "operation": operation,
            "error": f"지원하지 않는 서비스임. 선택 가능: {', '.join(API_SERVICES)}",
        }
    if operation not in service["operations"]:
        return {
            "success": False,
            "service_type": service_type,
            "operation": operation,
            "error": "해당 서비스에서 지원하지 않는 오퍼레이션임",
            "available_operations": list(service["operations"]),
        }

    page = max(int_value(page_no, 1), 1)
    rows = min(max(int_value(num_of_rows, 5), 1), 999)
    extra = {
        str(key): value
        for key, value in (parameters or {}).items()
        if value is not None and str(key).lower() not in _RESERVED_PARAMETER_NAMES
    }
    request_params = {"numOfRows": rows, "pageNo": page, **extra}
    cache_key = api_cache.make_key(
        "pps_openapi",
        service=service_type,
        operation=operation,
        params=request_params,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        payload = await get_json(
            f"{service['base_url']}/{operation}",
            params={"ServiceKey": pps_service_key(), "type": "json", **request_params},
        )
        body = response_body(payload)
        items = [item for item in as_list(body.get("items")) if isinstance(item, dict)]
        result = {
            "success": True,
            "service_type": service_type,
            "service": service["name"],
            "operation": operation,
            "data": body,
            "items": items,
            "total_count": int_value(body.get("totalCount"), len(items)),
            "page_no": int_value(body.get("pageNo"), page),
            "num_of_rows": int_value(body.get("numOfRows"), rows),
            "params_used": request_params,
        }
        api_cache.set(cache_key, result, ttl_seconds=300)
        return result
    except Exception as exc:
        return {
            "success": False,
            "service_type": service_type,
            "service": service["name"],
            "operation": operation,
            "error": str(exc),
            "error_type": type(exc).__name__,
        }


def protect_context(result: dict[str, Any], *, max_chars: int = 50_000) -> dict[str, Any]:
    """큰 API 응답을 핵심 필드 중심으로 줄이고 압축 사실을 기록함"""
    try:
        response_size = len(json.dumps(result, ensure_ascii=False, default=str))
    except Exception:
        return result
    if response_size <= max_chars or not result.get("success"):
        return result

    protected = dict(result)
    raw_items = result.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    fields = _SUMMARY_FIELDS.get(str(result.get("service_type")), ())
    summarized: list[dict[str, Any]] = []
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        summary = {key: _summary_value(item[key]) for key in fields if key in item}
        if len(summary) < 5:
            for key, value in item.items():
                if key not in summary:
                    summary[key] = _summary_value(value)
                if len(summary) >= min(10, len(item)):
                    break
        summarized.append(summary)

    data = result.get("data")
    if isinstance(data, dict):
        protected_data = dict(data)
        raw_container = data.get("items")
        if isinstance(raw_container, dict) and "item" in raw_container:
            protected_data["items"] = {"item": summarized}
        elif isinstance(raw_container, list):
            protected_data["items"] = summarized
        protected["data"] = protected_data
    protected["items"] = summarized
    protected["context_protection"] = {
        "applied": True,
        "original_size_chars": response_size,
        "total_items": len(items),
        "showing_items": len(summarized),
        "note": "응답 크기 제한에 따라 상위 5개 항목의 핵심 필드만 반환함",
    }

    if len(json.dumps(protected, ensure_ascii=False, default=str)) > max_chars:
        return {
            "success": True,
            "service_type": result.get("service_type"),
            "service": result.get("service"),
            "operation": result.get("operation"),
            "total_count": result.get("total_count", len(items)),
            "page_no": result.get("page_no"),
            "num_of_rows": result.get("num_of_rows"),
            "items": summarized,
            "context_protection": protected["context_protection"],
            "summary": "원본 데이터가 존재하며 응답 크기 제한으로 핵심 필드만 표시함",
        }
    return protected
