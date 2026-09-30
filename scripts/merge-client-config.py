#!/usr/bin/env python3
"""
파일명: merge-client-config.py
경로: scripts/merge-client-config.py
목적: 기존 클라이언트 설정 파일(JSON/TOML)의 다른 항목을 보존하면서 mcp-platform 항목만 안전하게 병합함
작성자: AI전략팀
작성일: 2026-09-30
수정일: 2026-09-30
"""

import json
import os
import sys
from pathlib import Path


MANAGED_SERVERS = {"mcp-platform", "workspace-tools", "data-go-portal"}


def merge_json(target_path: Path, template_path: Path) -> None:
    """기존 JSON 파일의 mcpServers 내 managed 항목만 안전하게 갱신함"""
    with open(template_path, "r", encoding="utf-8") as f:
        template_data = json.load(f)

    target_data = {}
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                target_data = json.load(f)
        except Exception:
            target_data = {}

    if not isinstance(target_data, dict):
        target_data = {}

    if "mcpServers" not in target_data or not isinstance(target_data["mcpServers"], dict):
        target_data["mcpServers"] = {}

    template_servers = template_data.get("mcpServers", {})
    for server_name, server_config in template_servers.items():
        target_data["mcpServers"][server_name] = server_config

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(target_data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def merge_toml(target_path: Path, template_path: Path) -> None:
    """기존 TOML 파일에서 managed 서버 섹션만 치환하여 보존 갱신함"""
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read().strip()

    existing_content = ""
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except Exception:
            existing_content = ""

    lines = existing_content.splitlines()
    filtered_lines = []
    skipping = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            is_managed = False
            for k in MANAGED_SERVERS:
                if stripped.startswith(f"[mcp_servers.{k}]") or stripped.startswith(f"[mcp_servers.{k}."):
                    is_managed = True
                    break
            if is_managed:
                skipping = True
                continue
            else:
                skipping = False
        if not skipping:
            filtered_lines.append(line)

    clean_existing = "\n".join(filtered_lines).rstrip()
    if clean_existing:
        final_content = clean_existing + "\n\n" + template_content + "\n"
    else:
        final_content = template_content + "\n"

    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(final_content)


def main() -> None:
    if len(sys.argv) != 4:
        print("사용법: merge-client-config.py <json|toml> <대상파일> <템플릿파일>", file=sys.stderr)
        sys.exit(1)

    fmt = sys.argv[1].lower()
    target_path = Path(sys.argv[2])
    template_path = Path(sys.argv[3])

    if fmt == "json":
        merge_json(target_path, template_path)
    elif fmt == "toml":
        merge_toml(target_path, template_path)
    else:
        print(f"지원하지 않는 포맷임: {fmt}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
