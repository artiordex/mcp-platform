#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"

cd "$mcp_root"
exec go run ./cmd/mcp-go-server "$@"
