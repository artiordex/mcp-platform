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


def test_sqlite_cache_persistence(tmp_path):
    """SQLite 캐시가 파일에 정상 영속화되고 조회되는지 검증함"""
    from mcp_platform.core.cache import SQLiteCache

    db_file = tmp_path / "test_cache.db"
    cache = SQLiteCache(db_path=db_file, default_ttl_seconds=10)
    key = "test_key_1"
    cache.set(key, {"msg": "영속 데이터"})

    # 새 인스턴스로 동일 DB 조회 시 데이터 복원 확인
    cache2 = SQLiteCache(db_path=db_file)
    assert cache2.get(key) == {"msg": "영속 데이터"}
    assert cache2.count() == 1


def test_tiered_cache_promotion(tmp_path):
    """L1에 없으나 L2에 있는 데이터가 L1으로 자동 승격 캐시되는지 검증함"""
    from mcp_platform.core.cache import SQLiteCache, TTLCache, TieredCache

    db_file = tmp_path / "tiered_cache.db"
    l1 = TTLCache(default_ttl_seconds=60)
    l2 = SQLiteCache(db_path=db_file, default_ttl_seconds=60)
    tiered = TieredCache(l1, l2)

    key = "tiered_key"
    tiered.set(key, {"level": 2})

    # L1만 임의 비움
    l1.clear()
    assert l1.get(key) is None

    # TieredCache 조회 시 L2에서 가져오며 L1에 다시 적재됨
    val = tiered.get(key)
    assert val == {"level": 2}
    assert l1.get(key) == {"level": 2}


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


def test_rag_ingest_document_success(monkeypatch):
    """RAG 신규 문서 인제스트 도구의 정상 등록 응답을 검증함"""
    class FakeResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "document_id": "doc-uuid-12345",
                "name": "2026_인프라계획.md",
                "chunks_created": 3,
                "quality_score": 0.96,
                "quality_grade": "A",
            }

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def post(self, url, json, headers):
            return FakeResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(rag.rag_ingest_document(
        name="2026_인프라계획.md",
        text="# 2026년 인프라 계획 본문",
        department="AI전략팀",
    ))
    assert result["success"] is True
    assert result["document_id"] == "doc-uuid-12345"
    assert result["chunks_created"] == 3


def test_rag_get_document_detail_success(monkeypatch):
    """RAG 등록 문서 단건 상세 및 청크 조회를 검증함"""
    class FakeDocResponse:
        status_code = 200
        def raise_for_status(self):
            pass
        def json(self):
            return {
                "id": "doc-uuid-12345",
                "name": "2026_인프라계획.md",
                "quality_score": 0.96,
            }

    class FakeChunkResponse:
        status_code = 200
        def json(self):
            return [
                {"chunk_index": 0, "text": "청크 1", "token_count": 50},
                {"chunk_index": 1, "text": "청크 2", "token_count": 60},
            ]

    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass
        async def get(self, url, headers):
            if "chunks" in url:
                return FakeChunkResponse()
            return FakeDocResponse()

    monkeypatch.setattr(rag.httpx, "AsyncClient", lambda **kwargs: FakeClient())

    result = run_async(rag.rag_get_document_detail("doc-uuid-12345"))
    assert result["success"] is True
    assert result["document"]["name"] == "2026_인프라계획.md"
    assert result["total_chunks"] == 2

