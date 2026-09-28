#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"
python_root="$mcp_root/python/mcp-runtime"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [[ ! -f "$python_root/pyproject.toml" ]]; then
  echo "Python MCP runtime was not found: $python_root" >&2
  exit 1
fi

echo "Installing dependencies for the local MCP runtime..." >&2
UV_PROJECT_ENVIRONMENT="$python_root/.venv" \
  uv sync --project "$python_root" --dev
echo "Python MCP runtime setup complete." >&2
