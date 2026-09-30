# =============================================================================
# 파일명: test_address.py
# 경로: connectors/tests/test_address.py
# 목적: 도로명주소 및 행정구역 FastMCP 도구 동작을 검증함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""도로명주소 및 행정구역 FastMCP 도구 동작을 검증함"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp_platform.servers import address


def run_async(coro):
    """비동기 코루틴을 동기 방식으로 실행함"""
    return asyncio.run(coro)


def test_search_address_validation():
    """빈 검색어 전달 시 유효성 오류를 반환하는지 검증함"""
    result = run_async(address.search_address(keyword="   "))
    assert result["success"] is False
    assert "keyword" in result["error"]


def test_search_address_success(monkeypatch):
    """주소 검색 API 응답이 올바르게 구조화되는지 검증함"""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "results": {
                    "common": {
                        "errorCode": "0",
                        "currentPage": "1",
                        "totalCount": "1",
                    },
                    "juso": [
                        {
                            "roadAddr": "서울특별시 강남구 테헤란로 152",
                            "jibunAddr": "서울특별시 강남구 역삼동 737",
                            "zipNo": "06236",
                            "bdNm": "강남파이낸스센터",
                            "siNm": "서울특별시",
                            "sggNm": "강남구",
                            "emdNm": "역삼동",
                            "admCd": "1168010100",
                        }
                    ],
                }
            }

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def get(self, url, params):
            return FakeResponse()

    monkeypatch.setattr(address.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(address.search_address(keyword="테헤란로 152"))
    assert result["success"] is True
    assert result["total_count"] == 1
    assert result["items"][0]["zip_code"] == "06236"
    assert result["items"][0]["building_name"] == "강남파이낸스센터"


def test_get_administrative_district_heuristic():
    """API 실패 시 주소 문자열을 바탕으로 휴리스틱 분리하는지 검증함"""
    result = run_async(address.get_administrative_district("경기도 성남시 분당구 판교역로 166"))
    assert result["success"] is True
    assert result["sido"] == "경기도"
    assert result["sigungu"] == "성남시"
    assert result["emd_name"] == "분당구"
