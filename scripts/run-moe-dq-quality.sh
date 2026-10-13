#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"
connector_root="$mcp_root/connectors"
python_executable="$mcp_root/.venv/bin/python"

if [[ ! -x "$python_executable" ]]; then
  echo "The local Python environment is missing. Run $mcp_root/scripts/setup-mcp-runtime.sh first." >&2
  exit 1
fi

export PYTHONPATH="$connector_root${PYTHONPATH:+:$PYTHONPATH}"
exec "$python_executable" "$mcp_root/scripts/run-data-go-python.py" mcp_platform.servers.moe_quality
