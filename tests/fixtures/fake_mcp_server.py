from __future__ import annotations

import json
import os
import sys
from typing import Any


def respond(request_id: int | str, result: dict[str, Any]) -> None:
    message = {"jsonrpc": "2.0", "id": request_id, "result": result}
    sys.stdout.write(json.dumps(message, ensure_ascii=False) + "\n")
    sys.stdout.flush()


for raw_line in sys.stdin:
    try:
        request = json.loads(raw_line)
    except json.JSONDecodeError:
        continue

    method = request.get("method")
    request_id = request.get("id")
    if request_id is None:
        continue

    if method == "initialize":
        respond(
            request_id,
            {
                "protocolVersion": request.get("params", {}).get("protocolVersion", "2025-11-25"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "fake-mcp-server", "version": "1.0.0"},
            },
        )
    elif method == "tools/list":
        respond(
            request_id,
            {
                "tools": [
                    {
                        "name": "inspect_env",
                        "description": "Return selected child environment variables.",
                        "inputSchema": {"type": "object", "properties": {}},
                    }
                ]
            },
        )
    elif method == "tools/call":
        respond(
            request_id,
            {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "allowed": os.getenv("MCP_PLATFORM_TEST_ALLOWED"),
                                "private": os.getenv("MCP_PLATFORM_TEST_PRIVATE"),
                            }
                        ),
                    }
                ]
            },
        )
    else:
        respond(
            request_id,
            {"error": {"code": -32601, "message": f"unsupported method: {method}"}},
        )
