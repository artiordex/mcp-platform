#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export DATA_GO_SERVERS="${DATA_GO_SERVERS:-nps,fsc,public_data_catalog,food_safety}"

exec "$script_dir/run-data-go-gateway.sh" "$@"
