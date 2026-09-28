#!/usr/bin/env python3
"""Run a local Data.go.kr MCP module with a reliable stdio loop.

The local servers use the MCP Python SDK's stdio transport. Keeping a small
periodic checkpoint task here makes that transport responsive in environments
where a background file read does not wake the event loop on its own.
"""

from __future__ import annotations

import importlib
import inspect
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import anyio


async def _heartbeat() -> None:
    while True:
        await anyio.sleep(0.1)


async def _with_heartbeat(
    runner: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any
) -> Any:
    async with anyio.create_task_group() as task_group:
        task_group.start_soon(_heartbeat)
        try:
            return await runner(*args, **kwargs)
        finally:
            task_group.cancel_scope.cancel()


def _patch_fastmcp(module: Any) -> bool:
    server = getattr(module, "mcp", None)
    runner = getattr(server, "run_stdio_async", None)
    if runner is None or not inspect.iscoroutinefunction(runner):
        return False

    async def run_stdio_with_heartbeat(*args: Any, **kwargs: Any) -> Any:
        return await _with_heartbeat(runner, *args, **kwargs)

    server.run_stdio_async = run_stdio_with_heartbeat
    return True


def _patch_low_level_server(module: Any) -> bool:
    runner = getattr(module, "run_server", None)
    if runner is None or not inspect.iscoroutinefunction(runner):
        return False

    async def run_server_with_heartbeat(*args: Any, **kwargs: Any) -> Any:
        return await _with_heartbeat(runner, *args, **kwargs)

    module.run_server = run_server_with_heartbeat
    return True


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: run-data-go-python.py <module>")

    module = importlib.import_module(sys.argv[1])
    if not (_patch_fastmcp(module) or _patch_low_level_server(module)):
        raise SystemExit(f"unsupported Data.go.kr MCP module: {sys.argv[1]}")

    entrypoint = getattr(module, "main", None)
    if not callable(entrypoint):
        raise SystemExit(f"module has no main() entrypoint: {sys.argv[1]}")

    entrypoint()


if __name__ == "__main__":
    main()
