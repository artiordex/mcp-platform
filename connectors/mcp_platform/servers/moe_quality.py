"""Thin MCP adapter for the local MOE data-quality HTTP API."""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import httpx
from dotenv import dotenv_values
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("MOE Data Quality")

_MCP_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_API_BASE_URL = "http://127.0.0.1:18080"
_MAX_TEXT_CHARACTERS = 200_000
_MAX_RULES_PER_RESPONSE = 200
_HTTP_TIMEOUT = httpx.Timeout(120.0, connect=3.0)
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _api_base_url() -> str:
    """Resolve only a loopback API endpoint; no remote forwarding is allowed."""
    file_values = dotenv_values(_MCP_ROOT / ".env")
    configured = os.getenv("MOE_DQ_DIAG_API_BASE_URL") or file_values.get(
        "MOE_DQ_DIAG_API_BASE_URL"
    )
    value = (configured or _DEFAULT_API_BASE_URL).strip().rstrip("/")
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        is_loopback = host == "localhost" or (
            host is not None and ipaddress.ip_address(host).is_loopback
        )
        if (
            parsed.scheme not in {"http", "https"}
            or not is_loopback
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError
        _ = parsed.port
    except (ValueError, TypeError):
        raise RuntimeError(
            "MOE_DQ_DIAG_API_BASE_URL must be a loopback HTTP(S) origin, "
            "such as http://127.0.0.1:18080"
        ) from None
    return value


API_BASE_URL = _api_base_url()


def _safe_error_detail(response: httpx.Response) -> dict[str, Any]:
    """Return bounded API error metadata without reflecting request content."""
    code: str | None = None
    try:
        payload = response.json()
    except (ValueError, TypeError):
        payload = None

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, dict):
        candidate = detail.get("code")
        if isinstance(candidate, str) and _SAFE_CODE.fullmatch(candidate):
            code = candidate

    result: dict[str, Any] = {
        "ok": False,
        "http_status": response.status_code,
    }
    if code:
        result["error_code"] = code
    else:
        result["error_code"] = "api_request_rejected"
    return result


async def _request_json(
    method: Literal["GET", "POST"],
    path: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(
            timeout=_HTTP_TIMEOUT,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.request(
                method,
                f"{API_BASE_URL}{path}",
                params=params,
                json=json_body,
                headers={"Accept": "application/json"},
            )
    except httpx.TimeoutException:
        return {"ok": False, "error_code": "api_timeout"}
    except httpx.RequestError:
        return {"ok": False, "error_code": "api_unavailable"}

    if response.is_error:
        return _safe_error_detail(response)
    try:
        payload = response.json()
    except (ValueError, TypeError):
        return {"ok": False, "error_code": "api_invalid_json"}
    if not isinstance(payload, dict):
        return {"ok": False, "error_code": "api_response_shape_invalid"}
    return payload


@mcp.tool()
async def get_quality_api_capabilities() -> dict[str, Any]:
    """Read the API's current development capabilities and explicit workflow limits."""
    return await _request_json("GET", "/api/v2/quality/capabilities")


@mcp.tool()
async def get_quality_catalog_summary() -> dict[str, Any]:
    """Read counts and dimensions from the MOE quality-rule catalog."""
    return await _request_json("GET", "/api/v1/diagnostics/catalog/summary")


@mcp.tool()
async def list_quality_catalog_rules(
    kind: Literal["structured", "semi_structured", "unstructured"] | None = None,
    dimension: str | None = None,
    severity: str | None = None,
    required_only: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """List filtered catalog rules; results contain rule metadata, not document text."""
    bounded_limit = min(max(limit, 1), _MAX_RULES_PER_RESPONSE)
    params: dict[str, Any] = {"required_only": required_only}
    if kind:
        params["kind"] = kind
    if dimension:
        params["dimension"] = dimension
    if severity:
        params["severity"] = severity

    result = await _request_json(
        "GET", "/api/v1/diagnostics/catalog/rules", params=params
    )
    if result.get("ok") is False:
        return result
    rules = result.get("rules")
    if not isinstance(rules, list):
        return {"ok": False, "error_code": "catalog_response_shape_invalid"}
    result["rules"] = rules[:bounded_limit]
    result["returned_count"] = len(result["rules"])
    result["truncated"] = len(rules) > bounded_limit
    return result


@mcp.tool()
async def get_quality_catalog_rule(rule_id: str) -> dict[str, Any]:
    """Read one quality rule by its catalog identifier."""
    clean_id = rule_id.strip()
    if not clean_id or len(clean_id) > 128:
        return {"ok": False, "error_code": "rule_id_invalid"}
    return await _request_json(
        "GET", f"/api/v1/diagnostics/catalog/rules/{quote(clean_id, safe='')}"
    )


@mcp.tool()
async def diagnose_unstructured_text(
    document_name: str,
    text: str,
) -> dict[str, Any]:
    """Run the catalog-backed text diagnosis; the API omits source samples and metadata."""
    clean_name = document_name.strip()
    if not clean_name or len(clean_name) > 256:
        return {"ok": False, "error_code": "document_name_invalid"}
    if not text or len(text) > _MAX_TEXT_CHARACTERS:
        return {
            "ok": False,
            "error_code": "text_length_invalid",
            "max_characters": _MAX_TEXT_CHARACTERS,
        }
    return await _request_json(
        "POST",
        "/api/v1/diagnostics/catalog/diagnose",
        json_body={"document_name": clean_name, "text": text, "metadata": {}},
    )


@mcp.tool()
async def rediagnose_text_pair(
    source_document_name: str,
    source_text: str,
    derived_document_name: str,
    derived_text: str,
) -> dict[str, Any]:
    """Compare source and derived text with the same catalog rules, without applying changes."""
    clean_source_name = source_document_name.strip()
    clean_derived_name = derived_document_name.strip()
    if (
        not clean_source_name
        or len(clean_source_name) > 256
        or not clean_derived_name
        or len(clean_derived_name) > 256
    ):
        return {"ok": False, "error_code": "document_name_invalid"}
    if (
        not source_text
        or not derived_text
        or len(source_text) > _MAX_TEXT_CHARACTERS
        or len(derived_text) > _MAX_TEXT_CHARACTERS
    ):
        return {
            "ok": False,
            "error_code": "text_length_invalid",
            "max_characters_per_text": _MAX_TEXT_CHARACTERS,
        }
    return await _request_json(
        "POST",
        "/api/v1/diagnostics/catalog/re-diagnose",
        json_body={
            "source_document_name": clean_source_name,
            "source_text": source_text,
            "derived_document_name": clean_derived_name,
            "derived_text": derived_text,
            "source_metadata": {},
            "derived_metadata": {},
        },
    )


@mcp.tool()
async def submit_unstructured_text_job(
    document_name: str,
    text: str,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Submit text to the durable diagnosis queue; API retention approval remains mandatory."""
    clean_name = document_name.strip()
    if not clean_name or len(clean_name) > 256:
        return {"ok": False, "error_code": "document_name_invalid"}
    if not text or len(text) > _MAX_TEXT_CHARACTERS:
        return {
            "ok": False,
            "error_code": "text_length_invalid",
            "max_characters": _MAX_TEXT_CHARACTERS,
        }
    bounded_attempts = min(max(max_attempts, 1), 10)
    return await _request_json(
        "POST",
        "/api/v1/quality/unstructured/jobs",
        json_body={
            "document_name": clean_name,
            "text": text,
            "max_attempts": bounded_attempts,
            "enable_ai_review": False,
            "metadata": {},
        },
    )


@mcp.tool()
async def get_unstructured_text_job_status(job_id: str) -> dict[str, Any]:
    """Read a safe job-status projection without retrieving source text."""
    clean_id = job_id.strip()
    if not clean_id or len(clean_id) > 100:
        return {"ok": False, "error_code": "job_id_invalid"}
    return await _request_json("GET", f"/jobs/{quote(clean_id, safe='')}")


def main() -> None:
    """Run the MOE quality adapter over stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
