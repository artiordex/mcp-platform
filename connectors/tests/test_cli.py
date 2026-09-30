# =============================================================================
# 파일명: test_cli.py
# 경로: connectors/tests/test_cli.py
# 목적: MCP 플랫폼 CLI 핵심 제어 로직 단위 테스트임
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""MCP 플랫폼 CLI 모듈의 서버 목록, 도구 조회, 캐시 제어 동작을 검증함"""

import asyncio

import pytest
from mcp_platform.cli.commands import (
    SERVER_REGISTRY,
    clear_cache,
    get_cache_stats,
    list_servers,
    list_tools,
    load_server_mcp,
)


def run_async(coro):
    """비동기 코루틴을 동기 방식으로 실행함"""
    return asyncio.run(coro)


def test_list_servers():
    """모든 등록된 MCP 서버 메타데이터가 정상 반환되는지 검증함"""
    servers = run_async(list_servers())
    assert len(servers) == len(SERVER_REGISTRY)
    ids = [s["id"] for s in servers]
    assert "corporate_intelligence" in ids
    assert "rag" in ids
    assert "pps" in ids
    assert "dart" in ids
    assert "address" in ids
    assert "smes" in ids


def test_list_tools_single_server():
    """특정 서버(smes)의 도구 목록이 정상 반환되는지 검증함"""
    tools = run_async(list_tools(server_id="smes"))
    assert len(tools) >= 2
    tool_names = [t["name"] for t in tools]
    assert "search_support_programs" in tool_names
    assert "get_support_program_detail" in tool_names
    assert tools[0]["server"] == "smes"


def test_list_tools_all_servers():
    """전체 서버 대상 도구 조회가 오류 없이 모든 도구를 수집하는지 검증함"""
    tools = run_async(list_tools(server_id=None))
    assert len(tools) > 10
    tool_names = [t["name"] for t in tools]
    assert "rag_search_documents" in tool_names
    assert "search_address" in tool_names
    assert "search_dart_filings" in tool_names


def test_load_server_invalid():
    """미등록 서버 식별자 입력 시 ValueError를 발생시키는지 검증함"""
    with pytest.raises(ValueError) as excinfo:
        load_server_mcp("unknown_server_id")
    assert "지원하지 않는 서버 식별자임" in str(excinfo.value)


def test_cache_stats_and_clear():
    """CLI 캐시 통계 및 초기화 기능이 올바르게 동작하는지 검증함"""
    stats = get_cache_stats()
    assert "status" in stats
    assert stats["status"] == "active"
    assert "l1_memory_entries" in stats
    assert "l2_disk_entries" in stats

    clear_result = clear_cache()
    assert clear_result["success"] is True
    assert "초기화되었음" in clear_result["message"]
