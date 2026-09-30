# =============================================================================
# 파일명: common.py
# 경로: connectors/mcp_platform/core/common.py
# 목적: 공공데이터 API 통신, 민감정보 마스킹, 응답 엔벨로프 파싱 공통 유틸리티를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""공공데이터 API 통신, 민감정보 마스킹, 응답 엔벨로프 파싱 공통 유틸리티를 제공함"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, quote_plus

import httpx
from dotenv import load_dotenv
from xmltodict import parse as parse_xml

load_dotenv()

HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# 공공데이터 API 키 노출 방지를 위해 HTTP 클라이언트 상세 로그 레벨을 WARNING으로 상향함
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class DataGoError(RuntimeError):
    """MCP 호출자에게 반환 가능한 공공데이터 API 또는 설정 오류임"""


_SECRET_ENV_NAMES = (
    "API_KEY",
    "DATA_GO_API_KEY",
    "FOOD_SAFETY_API_KEY",
    "FOOD_API_KEY",
)


def redact_sensitive(value: Any) -> str:
    """오류 메시지나 로그에 포함된 인증 키 문자열을 마스킹 처리함"""
    text = str(value)
    secrets: set[str] = set()
    for name in _SECRET_ENV_NAMES:
        secret = os.getenv(name)
        if secret and len(secret) >= 4:
            secrets.update(
                {
                    secret,
                    quote(secret, safe=""),
                    quote_plus(secret, safe=""),
                }
            )
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def service_key() -> str:
    """공공데이터포털 디코딩 인증키를 반환함

    Raises:
        DataGoError: 환경변수에 인증키가 설정되지 않았을 때 발생함
    """
    key = os.getenv("DATA_GO_API_KEY") or os.getenv("API_KEY")
    if not key:
        raise DataGoError(
            "DATA_GO_API_KEY 환경변수가 설정되지 않음. 저장소의 .env 파일에 키를 설정해야 함"
        )
    return key


def as_list(value: Any) -> list[Any]:
    """단일 항목 또는 매핑 구조를 리스트 형태로 표준화함"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, Mapping):
        item = value.get("item")
        if item is None:
            return []
        return item if isinstance(item, list) else [item]
    return [value]


def response_body(payload: Any) -> dict[str, Any]:
    """공공데이터 표준 응답의 response.body 엔벨로프를 해제하고 본문을 반환함

    Raises:
        DataGoError: 유효하지 않은 응답 구조이거나 API 오류 코드가 수신되었을 때 발생함
    """
    if not isinstance(payload, Mapping):
        raise DataGoError("API 응답이 JSON 객체 형식이 아님")

    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise DataGoError("API 응답에 유효한 response 엔벨로프가 없음")

    header = response.get("header")
    if isinstance(header, Mapping):
        code = str(header.get("resultCode", header.get("result_code", "00")))
        if code not in {"00", "0", "OK", "ok"}:
            message = header.get("resultMsg", header.get("result_msg", "알 수 없는 API 오류임"))
            raise DataGoError(redact_sensitive(f"공공데이터 API 오류 [{code}]: {message}"))

    body = response.get("body", response)
    if not isinstance(body, Mapping):
        raise DataGoError("API 응답에 유효한 body 항목이 없음")
    return dict(body)


def parse_xml_envelope(text: str) -> dict[str, Any]:
    """XML 응답을 딕셔너리로 변환한 뒤 표준 본문 래핑을 해제함"""
    try:
        return response_body(parse_xml(text))
    except DataGoError:
        raise
    except Exception as exc:
        raise DataGoError("XML API 응답 파싱에 실패함") from exc


async def get_json(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    """비동기 GET 요청으로 JSON 데이터를 수신함"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.get(url, params=dict(params or {}), headers=dict(headers or {}))
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise DataGoError(
                f"API 엔드포인트에서 HTTP {exc.response.status_code} 오류를 반환함"
            ) from exc
        except httpx.RequestError as exc:
            raise DataGoError("API 엔드포인트에 연결할 수 없음") from exc
        except ValueError as exc:
            raise DataGoError("API가 올바른 JSON 데이터를 반환하지 않음") from exc


async def post_json(
    url: str,
    *,
    json_body: Any,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    """비동기 POST 요청으로 JSON 데이터를 전송하고 수신함"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.post(
                url,
                params=dict(params or {}),
                json=json_body,
                headers=dict(headers or {}),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise DataGoError(
                f"API 엔드포인트에서 HTTP {exc.response.status_code} 오류를 반환함"
            ) from exc
        except httpx.RequestError as exc:
            raise DataGoError("API 엔드포인트에 연결할 수 없음") from exc
        except ValueError as exc:
            raise DataGoError("API가 올바른 JSON 데이터를 반환하지 않음") from exc


async def get_xml(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """비동기 GET 요청으로 XML 데이터를 수신하여 파싱함"""
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.get(url, params=dict(params or {}), headers=dict(headers or {}))
            response.raise_for_status()
            return parse_xml_envelope(response.text)
        except DataGoError:
            raise
        except httpx.HTTPStatusError as exc:
            raise DataGoError(
                f"API 엔드포인트에서 HTTP {exc.response.status_code} 오류를 반환함"
            ) from exc
        except httpx.RequestError as exc:
            raise DataGoError("API 엔드포인트에 연결할 수 없음") from exc


def int_value(value: Any, default: int = 0) -> int:
    """값을 정수형으로 안전하게 변환하며 실패 시 기본값을 반환함"""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def text_value(value: Any) -> str | None:
    """값을 문자열로 안전하게 변환함"""
    if value is None:
        return None
    return str(value)


def error_result(exc: Exception, **fields: Any) -> dict[str, Any]:
    """예외 정보를 마스킹하여 안전한 에러 딕셔너리를 구성함"""
    return {"error": redact_sensitive(exc), **fields}
