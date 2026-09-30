# =============================================================================
# 파일명: rag.py
# 경로: connectors/mcp_platform/servers/rag.py
# 목적: 사내 RAG-vLLM 엔진과 연동하여 문서 검색·AI 질의·행정 기안 도구를 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""사내 RAG-vLLM 엔진과 연동하여 문서 검색·AI 질의·행정 기안 도구를 제공함"""

from __future__ import annotations

import os
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

from ..core.cache import api_cache
from ..core.common import error_result

mcp = FastMCP("Internal RAG-vLLM Knowledge Hub")

RAG_BASE_URL = os.getenv("RAG_VLLM_URL", "http://127.0.0.1:11020").rstrip("/")
RAG_API_KEY = os.getenv("RAG_API_KEY", "")


def _get_headers() -> dict[str, str]:
    """RAG-vLLM API 요청 헤더를 구성함"""
    headers = {"Content-Type": "application/json"}
    if RAG_API_KEY:
        headers["X-API-Key"] = RAG_API_KEY
    return headers


# -----------------------------------------------------------------------------
# 1. MCP Tools (도구)
# -----------------------------------------------------------------------------


@mcp.tool()
async def rag_search_documents(
    query: str,
    top_k: int = 5,
    department: str | None = None,
    min_quality_score: float = 0.0,
) -> dict[str, Any]:
    """사내 규정, 기안문, 매뉴얼 등 등록된 문서를 하이브리드(밀집+희소) 벡터 검색함

    Args:
        query: 검색할 질문이나 키워드임
        top_k: 반환할 관련 청크 수임 (기본 5개)
        department: 대상 부서 필터임 (예: 기획재정팀, 인사총무팀)
        min_quality_score: 최소 데이터 품질 점수 필터임 (0.0 ~ 1.0)

    Returns:
        검색된 문서 청크 목록 및 유사도 점수 매핑 객체임
    """
    cache_key = api_cache.make_key(
        "rag_search",
        query=query,
        top_k=top_k,
        dept=department,
        quality=min_quality_score,
    )
    cached = api_cache.get(cache_key)
    if cached is not None:
        return cached

    payload = {
        "question": query,
        "top_k": min(max(top_k, 1), 20),
        "use_llm": False,
        "department": department,
        "min_quality_score": min_quality_score,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RAG_BASE_URL}/query",
                json=payload,
                headers=_get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            sources = data.get("sources", [])
            result = {
                "total_found": len(sources),
                "chunks": [
                    {
                        "document_name": s.get("document_name"),
                        "text": s.get("text"),
                        "similarity": round(s.get("similarity", 0.0), 4),
                        "chunk_index": s.get("chunk_index"),
                        "department": s.get("metadata", {}).get("department"),
                    }
                    for s in sources
                ],
                "message": f"검색 결과 {len(sources)}건을 조회함",
            }
            api_cache.set(cache_key, result, ttl_seconds=180)
            return result
    except Exception as exc:
        return error_result(exc, total_found=0, chunks=[], query=query)


@mcp.tool()
async def rag_ask_ai(
    question: str,
    top_k: int = 5,
    department: str | None = None,
) -> dict[str, Any]:
    """사내 문서를 근거로 vLLM 고속 로컬 모델이 검증된 답변을 생성함

    Args:
        question: 사내 업무나 규정에 관한 구체적 질문임
        top_k: 답변 생성 시 참조할 청크 수임
        department: 특정 부서 문서 우선 참조 필터임

    Returns:
        인공지능 모델 답변 본문, 출처 인용 목록, 신뢰도 점수임
    """
    payload = {
        "question": question,
        "top_k": min(max(top_k, 1), 10),
        "use_llm": True,
        "department": department,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{RAG_BASE_URL}/query",
                json=payload,
                headers=_get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "answer": data.get("answer", "답변을 생성하지 못함"),
                "confidence_score": round(data.get("confidence_score", 0.0), 3),
                "sources_count": len(data.get("sources", [])),
                "sources": [
                    {
                        "document_name": s.get("document_name"),
                        "similarity": round(s.get("similarity", 0.0), 3),
                    }
                    for s in data.get("sources", [])
                ],
            }
    except Exception as exc:
        return error_result(exc, answer="RAG 엔진 통신 오류가 발생함", confidence_score=0.0)


@mcp.tool()
async def rag_list_documents(
    search: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """사내 RAG 시스템에 색인 완료된 문서 목록을 페이징 조회함

    Args:
        search: 파일명 검색어 필터임
        limit: 조회할 최대 건수임 (기본 20건)

    Returns:
        등록된 문서 목록 및 총 건수임
    """
    params: dict[str, Any] = {"limit": min(max(limit, 1), 100), "offset": 0}
    if search:
        params["search"] = search

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{RAG_BASE_URL}/documents",
                params=params,
                headers=_get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "total_count": data.get("total_count", 0),
                "documents": [
                    {
                        "id": doc.get("id"),
                        "name": doc.get("name"),
                        "chunk_count": doc.get("chunk_count"),
                        "quality_grade": doc.get("quality_grade"),
                        "created_at": doc.get("created_at"),
                    }
                    for doc in data.get("items", [])
                ],
            }
    except Exception as exc:
        return error_result(exc, total_count=0, documents=[])


@mcp.tool()
async def rag_ingest_document(
    name: str,
    text: str,
    department: str = "AI전략팀",
    source_type: str = "agent_report",
) -> dict[str, Any]:
    """분석 보고서, 회의록, 기안문 등 신규 텍스트 문서를 사내 RAG 지식베이스에 실시간 색인 등록함

    Args:
        name: 문서 제목 또는 식별 파일명임
        text: 색인할 문서 전문 본문임
        department: 담당 부서명임 (기본: AI전략팀)
        source_type: 문서 유형 식별자임 (기본: agent_report)

    Returns:
        등록된 문서 ID, 생성된 청크 수, 품질 점수 및 상태 객체임
    """
    payload = {
        "name": name,
        "text": text,
        "source_type": source_type,
        "mime_type": "text/markdown",
        "metadata": {"department": department, "ingested_by": "mcp-platform"},
        "replace_existing_source": True,
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{RAG_BASE_URL}/documents/text",
                json=payload,
                headers=_get_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            return {
                "success": True,
                "document_id": data.get("document_id"),
                "name": data.get("name"),
                "chunks_created": data.get("chunks_created", 0),
                "quality_score": data.get("quality_score"),
                "quality_grade": data.get("quality_grade"),
                "message": f"문서 '{name}' 색인 등록을 완료함 (청크 {data.get('chunks_created', 0)}개 생성됨)",
            }
    except Exception as exc:
        return error_result(exc, success=False, document_id=None, chunks_created=0)


@mcp.tool()
async def rag_get_document_detail(
    document_id: str,
    include_chunks: bool = True,
) -> dict[str, Any]:
    """등록된 문서의 메타데이터, 품질 점수 및 청크 목록 상세를 단건 조회함

    Args:
        document_id: 문서 고유 UUID 식별자임
        include_chunks: 원문 청크 텍스트 목록 포함 여부임 (기본: True)

    Returns:
        문서 상세 정보 및 청크 목록 객체임
    """
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{RAG_BASE_URL}/documents/{document_id}",
                headers=_get_headers(),
            )
            resp.raise_for_status()
            doc = resp.json()

            chunks = []
            if include_chunks:
                chunk_resp = await client.get(
                    f"{RAG_BASE_URL}/documents/{document_id}/chunks",
                    headers=_get_headers(),
                )
                if chunk_resp.status_code == 200:
                    chunks = [
                        {
                            "chunk_index": c.get("chunk_index"),
                            "text": c.get("text"),
                            "token_count": c.get("token_count"),
                        }
                        for c in chunk_resp.json()
                    ]

            return {
                "success": True,
                "document": doc,
                "chunks": chunks,
                "total_chunks": len(chunks),
            }
    except Exception as exc:
        return error_result(exc, success=False, document=None, chunks=[])



# -----------------------------------------------------------------------------
# 2. MCP Resources (리소스 - URI 기반 읽기)
# -----------------------------------------------------------------------------


@mcp.resource("internal://rag/stats")
async def get_rag_stats() -> str:
    """RAG-vLLM 시스템 상태 및 색인 현황 리소스를 반환함"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{RAG_BASE_URL}/stats", headers=_get_headers())
            if resp.status_code == 200:
                return resp.text
            return '{"status": "error", "message": "통계 조회 실패함"}'
    except Exception as exc:
        return f'{{"status": "offline", "error": "{str(exc)}"}}\'\'\''


# -----------------------------------------------------------------------------
# 3. MCP Prompts (프롬프트 템플릿 - 워크플로우 지원)
# -----------------------------------------------------------------------------


@mcp.prompt()
def draft_internal_memo(topic: str, department: str = "기획재정팀") -> str:
    """사내 규정 및 양식에 맞춘 공문서·기안서 초안 작성을 위한 지침 프롬프트임"""
    return (
        f"당신은 사내 최고 행정 전문가입니다. 아래 주제에 대해 공식 기안문을 작성하십시오.\n\n"
        f"- 주제: {topic}\n"
        f"- 주관부서: {department}\n\n"
        f"작성 규칙:\n"
        f"1. 먼저 `rag_search_documents` 도구를 사용해 관련 사내 규정 및 최근 공문을 검색하십시오.\n"
        f"2. 문서 번호, 시행 일자, 수신처, 발신처, 추진 배경, 주요 내용, 소요 예산, 향후 일정을 표준 기안 양식으로 작성하십시오.\n"
        f"3. 근거가 되는 사내 문서명을 본문 말미에 인용하십시오."
    )


def main() -> None:
    """FastMCP 표준 stdio 러너를 실행함"""
    mcp.run()


if __name__ == "__main__":
    main()
