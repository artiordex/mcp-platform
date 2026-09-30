# =============================================================================
# 파일명: test_dart.py
# 경로: connectors/tests/test_dart.py
# 목적: OpenDART 전자공시 FastMCP 도구, 리소스, 프롬프트 동작을 검증함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""OpenDART 전자공시 FastMCP 도구, 리소스, 프롬프트 동작을 검증함"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp_platform.servers import dart


def run_async(coro):
    """비동기 코루틴을 동기 방식으로 실행함"""
    return asyncio.run(coro)


def test_dart_filings_success(monkeypatch):
    """DART 최근 공시 목록 조회가 올바르게 파싱 및 필터링되는지 검증함"""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "status": "000",
                "message": "정상",
                "total_count": 1,
                "list": [
                    {
                        "corp_code": "00126380",
                        "corp_name": "삼성전자",
                        "report_nm": "사업보고서 (2025.12)",
                        "rcept_no": "20260330000123",
                        "flr_nm": "삼성전자",
                        "rcept_dt": "20260330",
                        "rm": "연",
                    }
                ],
            }

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def get(self, url, params):
            return FakeResponse()

    monkeypatch.setattr(dart.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(dart.search_dart_filings(corp_name="삼성전자"))
    assert result["success"] is True
    assert result["total_count"] == 1
    assert result["items"][0]["report_nm"] == "사업보고서 (2025.12)"
    assert result["items"][0]["corp_name"] == "삼성전자"


def test_dart_filings_no_data(monkeypatch):
    """공시 내역이 없을 때(상태코드 013) 빈 목록으로 정상 처리되는지 검증함"""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {"status": "013", "message": "조회된 데이터가 없습니다."}

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def get(self, url, params):
            return FakeResponse()

    monkeypatch.setattr(dart.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(dart.search_dart_filings(corp_code="99999999"))
    assert result["success"] is True
    assert result["total_count"] == 0
    assert len(result["items"]) == 0


def test_get_company_overview_success(monkeypatch):
    """DART 기업 개요 조회가 정상 반환되는지 검증함"""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "status": "000",
                "message": "정상",
                "corp_code": "00126380",
                "corp_name": "삼성전자(주)",
                "ceo_nm": "한종희, 경계현",
                "corp_cls": "Y",
                "jurir_no": "130111-0006246",
                "bizr_no": "124-81-00998",
                "adres": "경기도 수원시 영통구 삼성로 129",
            }

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def get(self, url, params):
            return FakeResponse()

    monkeypatch.setattr(dart.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(dart.get_company_overview("00126380"))
    assert result["success"] is True
    assert result["corp_name"] == "삼성전자(주)"
    assert result["bizr_no"] == "124-81-00998"


def test_dart_report_types_resource():
    """DART 공시 유형 명세 리소스 반환을 검증함"""
    resource_text = dart.get_dart_report_types()
    assert "A: 정기공시" in resource_text
    assert "B: 주요사항보고" in resource_text


def test_audit_company_disclosure_prompt():
    """기업 공시 위험 심사 프롬프트 생성을 검증함"""
    prompt = dart.audit_company_disclosure("삼성전자")
    assert "삼성전자" in prompt
    assert "search_dart_filings" in prompt
    assert "get_summary_financial_statement" in prompt
