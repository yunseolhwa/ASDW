#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${ASDW_PORT:-7868}"

cd "${PROJECT_DIR}"
source .venv-wsl/bin/activate
export HSA_ENABLE_SDMA="${HSA_ENABLE_SDMA:-0}"
export HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-10.3.0}"
export ASDW_SENSORS="${ASDW_SENSORS:-template,clip}"
export ASDW_PORT="${PORT}"

python -m asdw_fusion.server >/tmp/asdw-server.log 2>&1 &
SERVER_PID=$!

cleanup() {
  kill "${SERVER_PID}" 2>/dev/null || true
  wait "${SERVER_PID}" 2>/dev/null || true
}
trap cleanup EXIT

for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORT}/health"; then
    echo
    exit 0
  fi
  sleep 0.5
done

echo "Server did not answer /health. Last log lines:" >&2
tail -n 50 /tmp/asdw-server.log >&2
exit 1
