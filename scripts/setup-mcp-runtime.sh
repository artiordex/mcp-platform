#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"
connector_root="$mcp_root/connectors"
python_environment="$mcp_root/.venv"

uv_executable="uv"
if ! command -v "$uv_executable" >/dev/null 2>&1; then
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    uv_executable="$HOME/.local/bin/uv"
  else
    echo "uv is required. Install it from https://docs.astral.sh/uv/" >&2
    exit 1
  fi
fi

if [[ ! -f "$connector_root/pyproject.toml" ]]; then
  echo "MCP connector project was not found: $connector_root" >&2
  exit 1
fi

echo "Installing dependencies for the MCP connectors..." >&2
UV_PROJECT_ENVIRONMENT="$python_environment" \
  "$uv_executable" sync --project "$connector_root" --dev
echo "MCP connector setup complete." >&2
