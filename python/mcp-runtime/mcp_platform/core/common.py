"""Shared HTTP and response helpers for the local Data.go.kr servers."""

from __future__ import annotations

import os
import logging
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote, quote_plus

import httpx
from dotenv import load_dotenv
from xmltodict import parse as parse_xml

load_dotenv()

HTTP_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

# API keys are commonly sent as query parameters by Korean public APIs.
# Keep request URLs out of normal logs so credentials are not copied into
# terminal output or MCP client logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


class DataGoError(RuntimeError):
    """An API or configuration error that can be shown to an MCP caller."""


_SECRET_ENV_NAMES = (
    "API_KEY",
    "DATA_GO_API_KEY",
    "FOOD_SAFETY_API_KEY",
    "FOOD_API_KEY",
)


def redact_sensitive(value: Any) -> str:
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
    key = os.getenv("DATA_GO_API_KEY") or os.getenv("API_KEY")
    if not key:
        raise DataGoError(
            "DATA_GO_API_KEY is not configured. Put it in the repository .env "
            "or export it before starting the MCP server."
        )
    return key


def as_list(value: Any) -> list[Any]:
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
    """Unwrap the common data.go.kr ``response.body`` envelope."""
    if not isinstance(payload, Mapping):
        raise DataGoError("API response was not a JSON object")

    response = payload.get("response", payload)
    if not isinstance(response, Mapping):
        raise DataGoError("API response has an invalid response envelope")

    header = response.get("header")
    if isinstance(header, Mapping):
        code = str(header.get("resultCode", header.get("result_code", "00")))
        if code not in {"00", "0", "OK", "ok"}:
            message = header.get("resultMsg", header.get("result_msg", "Unknown API error"))
            raise DataGoError(redact_sensitive(f"API error [{code}]: {message}"))

    body = response.get("body", response)
    if not isinstance(body, Mapping):
        raise DataGoError("API response has an invalid body")
    return dict(body)


def parse_xml_envelope(text: str) -> dict[str, Any]:
    try:
        return response_body(parse_xml(text))
    except DataGoError:
        raise
    except Exception as exc:  # pragma: no cover - parser-specific detail
        raise DataGoError("Could not parse XML API response") from exc


async def get_json(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.get(url, params=dict(params or {}), headers=dict(headers or {}))
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            raise DataGoError(
                f"HTTP {exc.response.status_code} from configured API endpoint"
            ) from exc
        except httpx.RequestError as exc:
            raise DataGoError("Could not reach configured API endpoint") from exc
        except ValueError as exc:
            raise DataGoError("API returned invalid JSON") from exc


async def post_json(
    url: str,
    *,
    json_body: Any,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> Any:
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
                f"HTTP {exc.response.status_code} from configured API endpoint"
            ) from exc
        except httpx.RequestError as exc:
            raise DataGoError("Could not reach configured API endpoint") from exc
        except ValueError as exc:
            raise DataGoError("API returned invalid JSON") from exc


async def get_xml(
    url: str,
    *,
    params: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
        try:
            response = await client.get(url, params=dict(params or {}), headers=dict(headers or {}))
            response.raise_for_status()
            return parse_xml_envelope(response.text)
        except DataGoError:
            raise
        except httpx.HTTPStatusError as exc:
            raise DataGoError(
                f"HTTP {exc.response.status_code} from configured API endpoint"
            ) from exc
        except httpx.RequestError as exc:
            raise DataGoError("Could not reach configured API endpoint") from exc


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def text_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def error_result(exc: Exception, **fields: Any) -> dict[str, Any]:
    return {"error": redact_sensitive(exc), **fields}
