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
import tempfile
from pathlib import Path


MANAGED_SERVERS = {"mcp-platform", "workspace-tools", "data-go-portal"}


def resolve_target_path(target_path: Path) -> Path:
    """심볼릭 링크 대상 파일을 갱신하고 링크 경로 자체는 유지함"""
    if target_path.is_symlink() and not target_path.exists():
        raise ValueError(f"기존 설정 경로가 끊어진 심볼릭 링크임: {target_path}")
    return target_path.resolve(strict=False)


def merge_json(target_path: Path, template_path: Path) -> None:
    """기존 JSON 파일에서 템플릿이 사용하는 MCP 서버 맵만 갱신함"""
    target_path = resolve_target_path(target_path)
    with open(template_path, "r", encoding="utf-8") as f:
        template_data = json.load(f)

    if not isinstance(template_data, dict):
        raise ValueError(f"템플릿 최상위 값은 JSON 객체여야 함: {template_path}")
    server_key = next(
        (key for key in ("mcpServers", "servers") if isinstance(template_data.get(key), dict)),
        None,
    )
    if server_key is None:
        raise ValueError(f"템플릿에 mcpServers 또는 servers 객체가 없음: {template_path}")

    target_data = {}
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                target_data = json.load(f)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(
                f"기존 설정을 읽거나 파싱할 수 없어 병합을 중단함: {target_path}: {exc}"
            ) from exc

    if not isinstance(target_data, dict):
        raise ValueError(f"기존 설정의 최상위 값은 JSON 객체여야 함: {target_path}")

    # VS Code용 .vscode/mcp.json 템플릿으로 병합할 때 기존 portable 형식의
    # mcpServers 항목을 서버 목록으로 옮겨 기존 사용자 설정을 보존함.
    if server_key == "servers":
        portable_servers = target_data.pop("mcpServers", None)
        if portable_servers is not None:
            if not isinstance(portable_servers, dict):
                raise ValueError(f"기존 mcpServers 값은 JSON 객체여야 함: {target_path}")
            existing_servers = target_data.get("servers", {})
            if not isinstance(existing_servers, dict):
                raise ValueError(f"기존 servers 값은 JSON 객체여야 함: {target_path}")
            for server_name, server_config in portable_servers.items():
                existing_servers.setdefault(server_name, server_config)
            target_data["servers"] = existing_servers

    target_servers = target_data.get(server_key, {})
    if not isinstance(target_servers, dict):
        raise ValueError(f"기존 {server_key} 값은 JSON 객체여야 함: {target_path}")

    template_servers = template_data[server_key]
    for server_name in MANAGED_SERVERS - template_servers.keys():
        target_servers.pop(server_name, None)
    for server_name, server_config in template_servers.items():
        target_servers[server_name] = server_config
    target_data[server_key] = target_servers

    target_path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = target_path.stat().st_mode & 0o777 if target_path.exists() else None
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target_path.parent, delete=False
        ) as f:
            temp_name = f.name
            json.dump(target_data, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        if original_mode is not None:
            os.chmod(temp_name, original_mode)
        os.replace(temp_name, target_path)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)


def merge_toml(target_path: Path, template_path: Path) -> None:
    """기존 TOML 파일에서 managed 서버 섹션만 치환하여 보존 갱신함"""
    target_path = resolve_target_path(target_path)
    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read().strip()

    existing_content = ""
    if target_path.exists():
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                existing_content = f.read()
        except (OSError, UnicodeError) as exc:
            raise ValueError(
                f"기존 TOML 설정을 읽을 수 없어 병합을 중단함: {target_path}: {exc}"
            ) from exc

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
    original_mode = target_path.stat().st_mode & 0o777 if target_path.exists() else None
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target_path.parent, delete=False
        ) as f:
            temp_name = f.name
            f.write(final_content)
            f.flush()
            os.fsync(f.fileno())
        if original_mode is not None:
            os.chmod(temp_name, original_mode)
        os.replace(temp_name, target_path)
    finally:
        if temp_name is not None and os.path.exists(temp_name):
            os.unlink(temp_name)


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
