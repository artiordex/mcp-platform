# =============================================================================
# 파일명: test_corporate_intelligence.py
# 경로: connectors/tests/test_corporate_intelligence.py
# 목적: 기업 종합 분석 커넥터의 병렬 비동기 조회 및 결과 병합 로직을 검증함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""기업 종합 분석 커넥터의 병렬 비동기 조회 및 결과 병합 로직을 검증함"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp_platform.servers import corporate_intelligence


def run_async(coro):
    """비동기 코루틴을 동기 방식으로 실행함"""
    return asyncio.run(coro)


def test_analyze_company_comprehensive_validation():
    """사업자번호와 기업명이 모두 없을 때 유효성 오류를 반환하는지 검증함"""
    result = run_async(corporate_intelligence.analyze_company_comprehensive())
    assert result["success"] is False
    assert "하나 이상" in result["error"]


def test_analyze_company_comprehensive_success(monkeypatch):
    """국세청, 국민연금, 금융위 및 사내 RAG 결과를 통합하여 정상 반환하는지 검증함"""
    async def fake_nts(numbers):
        return {
            "success": True,
            "items": [{"b_no": "1234567890", "status": "계속사업자", "tax_type": "일반과세자"}],
        }

    async def fake_nps(**kwargs):
        return {
            "success": True,
            "items": [{"wkplNm": "주식회사 테스트", "jnngPsnCnt": 150, "ldongAddr": "서울특별시 영등포구"}],
        }

    async def fake_fsc(**kwargs):
        return {
            "success": True,
            "data": {
                "year": "2025",
                "revenue": 50000000000,
                "operating_income": 3000000000,
                "net_income": 2500000000,
                "debt_ratio": 45.2,
            },
        }

    async def fake_rag(**kwargs):
        return {
            "total_found": 1,
            "chunks": [{"document_name": "테스트사_업무협약서_2025.pdf"}],
        }

    async def fake_dart(**kwargs):
        return {
            "success": True,
            "total_count": 1,
            "items": [{"report_nm": "사업보고서", "rcept_dt": "20260330", "flr_nm": "주식회사 테스트"}],
        }

    monkeypatch.setattr(corporate_intelligence.nts, "check_business_status", fake_nts)
    monkeypatch.setattr(corporate_intelligence.nps, "search_business", fake_nps)
    monkeypatch.setattr(corporate_intelligence.fsc, "get_summary_financial_statement", fake_fsc)
    monkeypatch.setattr(corporate_intelligence.rag, "rag_search_documents", fake_rag)
    monkeypatch.setattr(corporate_intelligence.dart, "search_dart_filings", fake_dart)

    result = run_async(corporate_intelligence.analyze_company_comprehensive(
        business_number="123-45-67890",
        company_name="주식회사 테스트",
        include_internal_knowledge=True,
    ))

    assert result["success"] is True
    assert result["tax_status"]["is_active"] is True
    assert result["pension_employment"]["employee_count"] == 150
    assert result["financial_summary"]["revenue"] == 50000000000
    assert result["internal_rag_history"]["total_matches"] == 1
    assert result["dart_filings"]["total_recent"] == 1
    assert "양호" in result["overall_grade"]
