#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
mcp_root="$(cd -- "$script_dir/.." && pwd)"
python_root="$mcp_root/python/mcp-runtime"
server_name="${1:-}"

case "$server_name" in
  nps-business-enrollment)
    python_module="mcp_platform.servers.nps"
    ;;
  nts-business-verification)
    python_module="mcp_platform.servers.nts"
    ;;
  pps-narajangteo)
    python_module="mcp_platform.servers.pps"
    ;;
  fsc-financial-info)
    python_module="mcp_platform.servers.fsc"
    ;;
  public-data-catalog)
    python_module="mcp_platform.servers.portal_catalog"
    ;;
  food-safety-korea)
    python_module="mcp_platform.servers.food_safety"
    ;;
  *)
    cat >&2 <<'USAGE'
Usage: run-data-go-server.sh <server>

Servers:
  nps-business-enrollment
  nts-business-verification
  pps-narajangteo
  fsc-financial-info
  public-data-catalog
  food-safety-korea
USAGE
    exit 2
    ;;
esac

project_dir="$python_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required. Install it from https://docs.astral.sh/uv/" >&2
  exit 1
fi

if [[ ! -f "$project_dir/pyproject.toml" ]]; then
  echo "Unknown or missing Python MCP runtime: $project_dir" >&2
  exit 1
fi

# Keep local source imports working even when an editable environment contains
# an old absolute project path after a repository rename.
export PYTHONPATH="$project_dir${PYTHONPATH:+:$PYTHONPATH}"

# Load the repository-level .env while preserving explicit parent values.
data_go_api_key_override="${DATA_GO_API_KEY:-}"
api_key_override="${API_KEY:-}"
food_safety_api_key_override="${FOOD_SAFETY_API_KEY:-}"
food_api_key_override="${FOOD_API_KEY:-}"
if [[ -f "$mcp_root/.env" ]]; then
  # shellcheck disable=SC1091
  source "$mcp_root/.env"
fi
if [[ -n "$data_go_api_key_override" ]]; then
  export DATA_GO_API_KEY="$data_go_api_key_override"
fi
if [[ -n "$api_key_override" ]]; then
  export API_KEY="$api_key_override"
elif [[ -n "${DATA_GO_API_KEY:-}" ]]; then
  export API_KEY="$DATA_GO_API_KEY"
fi
if [[ -n "$food_safety_api_key_override" ]]; then
  export FOOD_SAFETY_API_KEY="$food_safety_api_key_override"
fi
if [[ -n "$food_api_key_override" ]]; then
  export FOOD_API_KEY="$food_api_key_override"
fi


# Each selected server remains a separate process, while all local modules
# share one maintained runtime project and virtual environment.
export UV_PROJECT_ENVIRONMENT="$project_dir/.venv"

exec uv run --project "$project_dir" --no-sync python "$mcp_root/scripts/run-data-go-python.py" "$python_module"
