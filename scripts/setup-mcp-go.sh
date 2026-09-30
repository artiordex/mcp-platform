#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"

if ! command -v go >/dev/null 2>&1; then
  echo "Go is required. Install Go or enable automatic toolchain downloads." >&2
  exit 1
fi

cd "$mcp_root"
go mod download
echo "Go MCP dependencies are ready." >&2
