from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
NODE = os.environ.get("NODE", "node")
PYTHON = sys.executable
PROTOCOL_VERSION = "2025-11-25"


def request(process: subprocess.Popen[str], method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    if process.stdin is None or process.stdout is None:
        raise RuntimeError("MCP process pipes are unavailable")
    request_id = getattr(process, "_mcp_request_id", 0) + 1
    setattr(process, "_mcp_request_id", request_id)
    process.stdin.write(
        json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
            ensure_ascii=False,
        )
        + "\n"
    )
    process.stdin.flush()
    line = process.stdout.readline()
    if not line:
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise AssertionError(f"MCP process closed before replying to {method}: {stderr}")
    message = json.loads(line)
    if "error" in message:
        raise AssertionError(f"MCP request {method} failed: {message['error']}")
    return message["result"]


def connect(command: list[str], env: dict[str, str]) -> subprocess.Popen[str]:
    process = subprocess.Popen(
        command,
        cwd=PROJECT_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    result = request(
        process,
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "platform-integration-test", "version": "1.0.0"},
        },
    )
    if result.get("protocolVersion") != PROTOCOL_VERSION:
        raise AssertionError(f"unexpected negotiated protocol: {result.get('protocolVersion')}")
    if process.stdin is None:
        raise RuntimeError("MCP process stdin is unavailable")
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    process.stdin.flush()
    return process


def close(process: subprocess.Popen[str]) -> str:
    if process.stdin is not None:
        process.stdin.close()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
    stderr = process.stderr.read() if process.stderr is not None else ""
    if process.returncode != 0:
        raise AssertionError(f"MCP process exited with {process.returncode}: {stderr}")
    return stderr


def check_generic_gateway() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mcp-platform-gateway-") as temp_dir:
        config_path = Path(temp_dir) / "mcp-servers.json"
        config_path.write_text(
            json.dumps(
                {
                    "name": "integration-gateway",
                    "servers": [
                        {
                            "id": "fake",
                            "label": "Fake MCP server",
                            "transport": "stdio",
                            "command": PYTHON,
                            "args": [str(Path(__file__).with_name("fake_mcp_server.py"))],
                            "cwd": ".",
                            "envPassthrough": ["MCP_PLATFORM_TEST_ALLOWED"],
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        env = {
            **os.environ,
            "MCP_SERVERS_CONFIG": str(config_path),
            "MCP_PLATFORM_TEST_ALLOWED": "present",
            "MCP_PLATFORM_TEST_PRIVATE": "must-not-reach-child",
        }
        process = connect([NODE, "dist/servers/mcp-gateway.js"], env)
        try:
            tools = request(process, "tools/list").get("tools", [])
            names = [tool["name"] for tool in tools]
            if names != ["mcp_fake_inspect_env"]:
                raise AssertionError(f"unexpected gateway tools: {names}")
            result = request(
                process,
                "tools/call",
                {"name": "mcp_fake_inspect_env", "arguments": {}},
            )
            text = next(item["text"] for item in result["content"] if item["type"] == "text")
            payload = json.loads(text)
            if payload != {"allowed": "present", "private": None}:
                raise AssertionError(f"child environment was not filtered: {payload}")
            if result.get("isError"):
                raise AssertionError(f"gateway tool returned an error: {result}")
        finally:
            stderr = close(process)
        return {"tools": names, "child_environment": payload, "stderr": stderr}


def check_data_go_gateway() -> dict[str, Any]:
    env = {
        **os.environ,
        "DATA_GO_SERVERS": "nps,nts,pps,fsc,public_data_catalog,food_safety",
    }
    process = connect([NODE, "dist/servers/data-go-gateway.js"], env)
    expected_counts = {
        "nps": 3,
        "nts": 3,
        "pps": 4,
        "fsc": 4,
        "public_data_catalog": 1,
        "food_safety": 3,
    }
    try:
        tools = request(process, "tools/list").get("tools", [])
        names = [tool["name"] for tool in tools]
        by_server = {
            server_id: sum(name.startswith(f"data_go_{server_id}_") for name in names)
            for server_id in expected_counts
        }
        if by_server != expected_counts:
            raise AssertionError(f"unexpected public-data tools: {by_server}")
    finally:
        stderr = close(process)
    return {"total_tools": len(names), "by_server": by_server, "stderr": stderr}


def check_workspace_server() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mcp-platform-workspace-") as temp_dir:
        base = Path(temp_dir)
        workspace = base / "workspace"
        workspace.mkdir()
        (workspace / "visible.txt").write_text("visible content", encoding="utf-8")
        (workspace / ".env").write_text("private content", encoding="utf-8")
        outside = base / "outside.txt"
        outside.write_text("outside content", encoding="utf-8")
        (workspace / "outside-link.txt").symlink_to(outside)

        env = {**os.environ, "MCP_WORKSPACE_ROOT": str(workspace)}
        process = connect([NODE, "dist/servers/workspace-tools.js"], env)
        try:
            visible = request(
                process,
                "tools/call",
                {"name": "read_project_file", "arguments": {"path": "visible.txt"}},
            )
            visible_text = "\n".join(item.get("text", "") for item in visible.get("content", []))
            if "visible content" not in visible_text:
                raise AssertionError(f"visible file was not returned: {visible}")

            hidden = request(
                process,
                "tools/call",
                {"name": "read_project_file", "arguments": {"path": ".env"}},
            )
            hidden_text = json.dumps(hidden)
            if not hidden.get("isError") or "private content" in hidden_text:
                raise AssertionError(f"hidden file was not blocked: {hidden}")

            outside_result = request(
                process,
                "tools/call",
                {
                    "name": "read_project_file",
                    "arguments": {"path": "outside-link.txt"},
                },
            )
            if not outside_result.get("isError") or "outside content" in json.dumps(outside_result):
                raise AssertionError(f"outside symlink was not blocked: {outside_result}")

            listing = request(
                process,
                "tools/call",
                {"name": "list_project_files", "arguments": {"path": ".", "maxDepth": 1}},
            )
            listing_text = json.dumps(listing)
            if "visible.txt" not in listing_text or ".env" in listing_text or "outside-link" in listing_text:
                raise AssertionError(f"workspace listing included hidden entries: {listing}")
        finally:
            stderr = close(process)
        return {"visible_file": visible_text, "hidden_blocked": True, "outside_symlink_blocked": True, "stderr": stderr}


def check_remote_gateway() -> dict[str, Any]:
    token = "Bearer integration-token"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            self.send_response(405)
            self.send_header("Allow", "POST")
            self.end_headers()

        def do_POST(self) -> None:
            if self.headers.get("Authorization") != token:
                self.send_response(401)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", "0"))
            request_message = json.loads(self.rfile.read(length))
            request_id = request_message.get("id")
            if request_id is None:
                self.send_response(202)
                self.end_headers()
                return

            method = request_message.get("method")
            if method == "initialize":
                result = {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "remote-fake-mcp", "version": "1.0.0"},
                }
            elif method == "tools/list":
                result = {
                    "tools": [
                        {
                            "name": "inspect_auth",
                            "description": "Return the authorization header received by the server.",
                            "inputSchema": {"type": "object", "properties": {}},
                        }
                    ]
                }
            elif method == "tools/call":
                result = {
                    "content": [{"type": "text", "text": self.headers["Authorization"]}]
                }
            else:
                result = None

            response = json.dumps(
                {"jsonrpc": "2.0", "id": request_id, "result": result}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    http_server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    http_thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    http_thread.start()

    try:
        with tempfile.TemporaryDirectory(prefix="mcp-platform-remote-") as temp_dir:
            config_path = Path(temp_dir) / "mcp-servers.json"
            config_path.write_text(
                json.dumps(
                    {
                        "name": "remote-integration-gateway",
                        "servers": [
                            {
                                "id": "remote",
                                "label": "Remote fake MCP server",
                                "transport": "streamable-http",
                                "url": f"http://127.0.0.1:{http_server.server_port}/mcp",
                                "headersFromEnv": {
                                    "Authorization": "MCP_REMOTE_TEST_AUTH"
                                },
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            env = {
                **os.environ,
                "MCP_SERVERS_CONFIG": str(config_path),
                "MCP_REMOTE_TEST_AUTH": token,
            }
            process = connect([NODE, "dist/servers/mcp-gateway.js"], env)
            try:
                tools = request(process, "tools/list").get("tools", [])
                names = [tool["name"] for tool in tools]
                if names != ["mcp_remote_inspect_auth"]:
                    raise AssertionError(f"unexpected remote gateway tools: {names}")
                result = request(
                    process,
                    "tools/call",
                    {"name": "mcp_remote_inspect_auth", "arguments": {}},
                )
                text = next(
                    item["text"] for item in result["content"] if item["type"] == "text"
                )
                if text != token:
                    raise AssertionError(f"remote authorization header was not forwarded: {text}")
            finally:
                stderr = close(process)
            return {"tools": names, "authorization_forwarded": True, "stderr": stderr}
    finally:
        http_server.shutdown()
        http_server.server_close()
        http_thread.join(timeout=2)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: run_stdio_checks.py <generic|data-go|remote|workspace>")
    checks = {
        "generic": check_generic_gateway,
        "data-go": check_data_go_gateway,
        "remote": check_remote_gateway,
        "workspace": check_workspace_server,
    }
    try:
        result = checks[sys.argv[1]]()
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise
    print(json.dumps(result, ensure_ascii=False))
