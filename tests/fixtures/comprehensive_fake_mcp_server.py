from __future__ import annotations

import json
import sys
from typing import Any

PROTOCOL_VERSION = "2024-11-05"


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
                "protocolVersion": request.get("params", {}).get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {
                    "tools": {},
                    "resources": {},
                    "prompts": {},
                },
                "serverInfo": {"name": "comprehensive-fake-mcp", "version": "1.0.0"},
            },
        )
    elif method == "tools/list":
        respond(
            request_id,
            {
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo input text.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"msg": {"type": "string"}},
                            "required": ["msg"],
                        },
                    },
                    {
                        "name": "create_item",
                        "description": "Create a new item (write tool).",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}},
                        },
                        "annotations": {"readOnlyHint": False},
                    },
                ]
            },
        )
    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name")
        args = params.get("arguments", {})
        if tool_name == "echo":
            respond(
                request_id,
                {"content": [{"type": "text", "text": f"Echo: {args.get('msg', '')}"}]},
            )
        elif tool_name == "create_item":
            respond(
                request_id,
                {"content": [{"type": "text", "text": f"Created: {args.get('name', '')}"}]},
            )
        else:
            respond(request_id, {"error": {"code": -32601, "message": f"unknown tool: {tool_name}"}})
    elif method == "resources/list":
        respond(
            request_id,
            {
                "resources": [
                    {
                        "uri": "fake://catalog/sample",
                        "name": "Sample Catalog",
                        "description": "A sample catalog resource.",
                        "mimeType": "application/json",
                    }
                ]
            },
        )
    elif method == "resources/read":
        params = request.get("params", {})
        uri = params.get("uri")
        respond(
            request_id,
            {
                "contents": [
                    {
                        "uri": uri,
                        "mimeType": "application/json",
                        "text": json.dumps({"status": "active", "items": ["alpha", "beta"]}),
                    }
                ]
            },
        )
    elif method == "prompts/list":
        respond(
            request_id,
            {
                "prompts": [
                    {
                        "name": "generate_report",
                        "description": "Generate analysis report.",
                        "arguments": [
                            {"name": "topic", "description": "Report topic", "required": True}
                        ],
                    }
                ]
            },
        )
    elif method == "prompts/get":
        params = request.get("params", {})
        args = params.get("arguments", {})
        topic = args.get("topic", "default")
        respond(
            request_id,
            {
                "description": "Generated report prompt",
                "messages": [
                    {
                        "role": "user",
                        "content": {"type": "text", "text": f"Please generate a report about {topic}."},
                    }
                ],
            },
        )
    else:
        respond(
            request_id,
            {"error": {"code": -32601, "message": f"unsupported method: {method}"}},
        )
