# =============================================================================
# 파일명: commands.py
# 경로: connectors/mcp_platform/cli/commands.py
# 목적: MCP 플랫폼 CLI 핵심 제어 로직(서버 목록, 도구 목록/호출, 캐시 관리)을 제공함
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""MCP 플랫폼 CLI 핵심 제어 로직을 제공함"""

from __future__ import annotations

import importlib
from typing import Any

from ..core.cache import api_cache

# 지원 서버 식별자 및 모듈 매핑 레지스트리
SERVER_REGISTRY: dict[str, tuple[str, str]] = {
    "corporate_intelligence": ("mcp_platform.servers.corporate_intelligence", "기업 종합 분석 융합 허브"),
    "rag": ("mcp_platform.servers.rag", "사내 RAG-vLLM 지식 허브"),
    "pps": ("mcp_platform.servers.pps", "조달청 나라장터 입찰 및 계약 정보"),
    "nps": ("mcp_platform.servers.nps", "국민연금 사업장 가입내역"),
    "nts": ("mcp_platform.servers.nts", "국세청 사업자등록 상태 및 진위확인"),
    "fsc": ("mcp_platform.servers.fsc", "금융위원회 기업 재무제표 정보"),
    "dart": ("mcp_platform.servers.dart", "금융감독원 OpenDART 전자공시"),
    "address": ("mcp_platform.servers.address", "행정안전부 도로명주소 및 행정구역"),
    "smes": ("mcp_platform.servers.smes", "중소벤처기업부 기업마당 지원사업"),
    "portal_catalog": ("mcp_platform.servers.portal_catalog", "공공데이터포털 데이터셋 카탈로그"),
    "food_safety": ("mcp_platform.servers.food_safety", "식품안전나라 위해식품 및 인허가 정보"),
}


def load_server_mcp(server_id: str) -> Any:
    """서버 식별자에 대응하는 FastMCP 인스턴스를 동적으로 로드함

    Args:
        server_id: 서버 고유 식별자임

    Returns:
        로드된 FastMCP 인스턴스임

    Raises:
        ValueError: 등록되지 않은 서버 식별자일 때 발생함
    """
    if server_id not in SERVER_REGISTRY:
        valid_servers = ", ".join(sorted(SERVER_REGISTRY.keys()))
        raise ValueError(f"지원하지 않는 서버 식별자임: '{server_id}'. 지원 목록: [{valid_servers}]")

    module_name, _ = SERVER_REGISTRY[server_id]
    mod = importlib.import_module(module_name)
    mcp_instance = getattr(mod, "mcp", None)
    if mcp_instance is None:
        raise ValueError(f"모듈 {module_name}에 'mcp' 인스턴스가 정의되어 있지 않음")
    return mcp_instance


async def list_servers() -> list[dict[str, Any]]:
    """등록된 모든 MCP 서버의 식별자, 설명, 상태 목록을 반환함

    Returns:
        서버 메타데이터 딕셔너리 목록임
    """
    results: list[dict[str, Any]] = []
    for sid, (_, desc) in SERVER_REGISTRY.items():
        results.append(
            {
                "id": sid,
                "description": desc,
                "status": "ready",
            }
        )
    return results


async def list_tools(server_id: str | None = None) -> list[dict[str, Any]]:
    """지정된 서버 또는 전체 서버의 도구 목록 및 스키마를 반환함

    Args:
        server_id: 특정 서버 식별자 필터임 (생략 시 전체 서버 조회함)

    Returns:
        도구명, 소속 서버, 설명, 파라미터 스키마를 담은 목록임
    """
    target_servers = [server_id] if server_id else list(SERVER_REGISTRY.keys())
    tools_list: list[dict[str, Any]] = []

    for sid in target_servers:
        try:
            mcp_instance = load_server_mcp(sid)
            server_tools = await mcp_instance.list_tools()
            for tool in server_tools:
                tools_list.append(
                    {
                        "server": sid,
                        "name": tool.name,
                        "description": (tool.description or "").strip().split("\n")[0],
                        "full_description": tool.description or "",
                        "parameters": getattr(tool, "inputSchema", {}),
                    }
                )
        except Exception as exc:
            tools_list.append(
                {
                    "server": sid,
                    "name": "ERROR",
                    "description": f"도구 목록 로드 실패함: {exc}",
                    "parameters": {},
                }
            )

    return tools_list


async def call_tool(server_id: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """특정 MCP 서버의 도구를 직접 호출하고 결과를 반환함

    Args:
        server_id: 대상 서버 식별자임
        tool_name: 호출할 도구명임
        arguments: 전달할 파라미터 매핑 객체임

    Returns:
        도구 실행 결과 객체임
    """
    mcp_instance = load_server_mcp(server_id)
    return await mcp_instance.call_tool(tool_name, arguments)


def get_cache_stats() -> dict[str, Any]:
    """2계층(L1 메모리 + L2 SQLite) 캐시의 현황 통계를 반환함

    Returns:
        캐시 항목 수 및 스토리지 정보 딕셔너리임
    """
    stats = api_cache.stats()
    return {
        "status": "active",
        "l1_memory_entries": stats.get("l1_memory_entries", 0),
        "l2_disk_entries": stats.get("l2_disk_entries", 0),
        "cache_type": "TieredCache (L1 Memory LRU + L2 SQLite WAL)",
    }


def clear_cache() -> dict[str, Any]:
    """2계층 캐시 데이터를 전량 초기화함

    Returns:
        초기화 결과 메시지 객체임
    """
    api_cache.clear()
    return {
        "success": True,
        "message": "L1 메모리 및 L2 SQLite 영속 캐시가 모두 초기화되었음",
    }
