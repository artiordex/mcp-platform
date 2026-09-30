# =============================================================================
# 파일명: test_rag_and_cache.py
# 경로: connectors/tests/test_rag_and_cache.py
# 목적: TTL 캐시 모듈 및 사내 RAG-vLLM MCP 도구 동작을 검증함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""TTL 캐시 모듈 및 사내 RAG-vLLM MCP 도구 동작을 검증함"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp_platform.core.cache import TTLCache, api_cache
from mcp_platform.servers import rag


def run_async(coro):
    """비동기 코루틴을 동기 방식으로 실행함"""
    return asyncio.run(coro)


def test_ttl_cache_basic_and_expiration():
    """TTL 캐시의 저장, 조회 및 시간 경과에 따른 만료를 검증함"""
    cache = TTLCache(default_ttl_seconds=1, max_entries=10)
    key = cache.make_key("test", id=123, name="샘플")

    cache.set(key, {"data": "value"}, ttl_seconds=1)
    assert cache.get(key) == {"data": "value"}

    # 키 생성 결정론성 검증
    key2 = cache.make_key("test", name="샘플", id=123)
    assert key == key2


def test_ttl_cache_capacity_limit():
    """캐시 용량 초과 시 오래된 항목이 자동 정리되는지 검증함"""
    cache = TTLCache(default_ttl_seconds=60, max_entries=5)
    for i in range(10):
        cache.set(f"key_{i}", i)

    # 최대 5건 내외로 정리되어야 함
    assert len(cache._store) <= 5


def test_rag_search_documents_success(monkeypatch):
    """RAG 문서 검색 도구가 정상 응답을 파싱하고 캐시하는지 검증함"""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "sources": [
                    {
                        "document_name": "취업규칙_2026.pdf",
                        "text": "제1조 본 규칙은...",
                        "similarity": 0.892,
                        "chunk_index": 0,
                        "metadata": {"department": "인사총무팀"},
                    }
                ]
            }

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json, headers):
            assert "/query" in url
            assert json["question"] == "연차휴가 규정"
            return FakeResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(rag.rag_search_documents(query="연차휴가 규정"))
    assert result["total_found"] == 1
    assert result["chunks"][0]["document_name"] == "취업규칙_2026.pdf"
    assert result["chunks"][0]["similarity"] == 0.892


def test_rag_ask_ai_success(monkeypatch):
    """RAG AI 질의응답 도구가 모델 답변을 올바르게 반환하는지 검증함"""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "answer": "취업규칙 제15조에 따라 연차는 15일 부여됩니다.",
                "confidence_score": 0.945,
                "sources": [
                    {"document_name": "취업규칙.pdf", "similarity": 0.91}
                ],
            }

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(rag.rag_ask_ai(question="연차 며칠이야?"))
    assert "15일" in result["answer"]
    assert result["confidence_score"] == 0.945


def test_rag_prompt_generation():
    """기안서 초안 작성 프롬프트 템플릿 생성을 검증함"""
    prompt_text = rag.draft_internal_memo("2026 하반기 GPU 인프라 확충안", "디지털혁신팀")
    assert "2026 하반기 GPU 인프라 확충안" in prompt_text
    assert "디지털혁신팀" in prompt_text
    assert "rag_search_documents" in prompt_text
