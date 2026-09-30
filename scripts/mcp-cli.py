#!/usr/bin/env python3
# =============================================================================
# 파일명: mcp-cli.py
# 경로: scripts/mcp-cli.py
# 목적: 터미널에서 MCP 서버, 도구 목록 조회, 직접 도구 호출 및 캐시 제어를 수행하는 CLI 도구임
# 작성자: AI전략팀
# 작성일: 2026-09-30
# 수정일: 2026-09-30
# =============================================================================

"""터미널에서 MCP 서버, 도구 목록 조회, 직접 도구 호출 및 캐시 제어를 수행하는 CLI 도구임"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# connectors 패키지 경로를 sys.path에 추가함
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR / "connectors"))

from mcp_platform.cli.commands import (
    call_tool,
    clear_cache,
    get_cache_stats,
    list_servers,
    list_tools,
)


def parse_args():
    """CLI 커맨드라인 인자를 파싱함"""
    parser = argparse.ArgumentParser(
        description="mcp-platform 터미널 관리 및 도구 호출 CLI 유틸리티임",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. servers (list-servers)
    subparsers.add_parser("servers", help="등록된 모든 MCP 서버 목록을 조회함")

    # 2. tools (list-tools)
    tools_parser = subparsers.add_parser("tools", help="등록된 MCP 도구 목록 및 스키마를 조회함")
    tools_parser.add_argument("--server", "-s", type=str, default=None, help="특정 서버 식별자 필터임")
    tools_parser.add_argument("--schema", action="store_true", help="입력 파라미터 스키마를 상세 출력함")

    # 3. call
    call_parser = subparsers.add_parser("call", help="지정된 서버의 특정 MCP 도구를 직접 호출함")
    call_parser.add_argument("server", type=str, help="대상 서버 식별자임 (예: rag, dart, smes, corporate_intelligence)")
    call_parser.add_argument("tool", type=str, help="호출할 도구명임 (예: rag_search_documents, search_dart_filings)")
    call_parser.add_argument("--json", "-j", dest="json_args", type=str, help="JSON 형식의 인자 문자열임")
    call_parser.add_argument(
        "--arg",
        "-a",
        dest="kv_args",
        action="append",
        default=[],
        help="key=value 형식의 인자 매핑임 (복수 지정 가능함)",
    )

    # 4. cache
    cache_parser = subparsers.add_parser("cache", help="L1/L2 영속 캐시 상태를 점검하거나 초기화함")
    cache_sub = cache_parser.add_subparsers(dest="cache_action", required=True)
    cache_sub.add_parser("stats", help="캐시 항목 수 및 스토리지 현황을 조회함")
    cache_sub.add_parser("clear", help="영속 캐시 데이터를 전량 초기화함")

    return parser.parse_args()


async def main_async():
    """비동기 메인 실행 진입점임"""
    args = parse_args()

    if args.command == "servers":
        servers = await list_servers()
        print(json.dumps(servers, ensure_ascii=False, indent=2))

    elif args.command == "tools":
        tools = await list_tools(server_id=args.server)
        if not args.schema:
            simplified = [
                {
                    "server": t["server"],
                    "name": t["name"],
                    "description": t["description"],
                }
                for t in tools
            ]
            print(json.dumps(simplified, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(tools, ensure_ascii=False, indent=2))

    elif args.command == "call":
        # 인자 병합
        call_arguments = {}
        if args.json_args:
            try:
                call_arguments = json.loads(args.json_args)
            except json.JSONDecodeError as exc:
                print(f"[ERROR] 유효하지 않은 JSON 인자 형식임: {exc}", file=sys.stderr)
                sys.exit(1)

        for pair in args.kv_args:
            if "=" in pair:
                k, v = pair.split("=", 1)
                # 숫자 변환 시도
                if v.isdigit():
                    call_arguments[k.strip()] = int(v)
                elif v.lower() == "true":
                    call_arguments[k.strip()] = True
                elif v.lower() == "false":
                    call_arguments[k.strip()] = False
                else:
                    call_arguments[k.strip()] = v.strip()

        try:
            raw_result = await call_tool(args.server, args.tool, call_arguments)
            # FastMCP call_tool은 (content, structured_data) 튜플을 반환할 수 있음
            if isinstance(raw_result, tuple):
                if len(raw_result) == 2 and isinstance(raw_result[1], dict):
                    print(json.dumps(raw_result[1], ensure_ascii=False, indent=2))
                elif len(raw_result) > 0 and hasattr(raw_result[0], "__iter__"):
                    first = raw_result[0]
                    if isinstance(first, list) and len(first) > 0 and hasattr(first[0], "text"):
                        print(first[0].text)
                    else:
                        print(json.dumps(raw_result, ensure_ascii=False, default=str, indent=2))
                else:
                    print(json.dumps(raw_result, ensure_ascii=False, default=str, indent=2))
            elif hasattr(raw_result, "model_dump"):
                print(json.dumps(raw_result.model_dump(), ensure_ascii=False, indent=2))
            elif isinstance(raw_result, (dict, list)):
                print(json.dumps(raw_result, ensure_ascii=False, indent=2))
            else:
                print(str(raw_result))
        except Exception as exc:
            print(f"[ERROR] 도구 호출 실패함: {exc}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "cache":
        if args.cache_action == "stats":
            stats = get_cache_stats()
            print(json.dumps(stats, ensure_ascii=False, indent=2))
        elif args.cache_action == "clear":
            result = clear_cache()
            print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    """동기 진입점임"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n[INFO] 사용자에 의해 중단됨", file=sys.stderr)
        sys.exit(130)


if __name__ == "__main__":
    main()
