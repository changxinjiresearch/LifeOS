#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-}"
if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  echo "usage: $0 /path/to/NextPlan.app" >&2
  exit 2
fi

APP_PATH="$(cd "$(dirname "$APP_PATH")" && pwd)/$(basename "$APP_PATH")"
CORE="$APP_PATH/Contents/Resources/resources/nextplan-core"
DESKTOP="$APP_PATH/Contents/MacOS/nextplan-local-desktop"

[[ -f "$CORE" ]] || { echo "bundled Local Core missing: $CORE" >&2; exit 3; }
[[ -f "$DESKTOP" ]] || { echo "desktop executable missing: $DESKTOP" >&2; exit 4; }
chmod +x "$CORE" "$DESKTOP"

TMP_ROOT="$(mktemp -d)"
CORE_PID=""
DESKTOP_PID=""
cleanup() {
  if [[ -n "$CORE_PID" ]]; then kill "$CORE_PID" 2>/dev/null || true; wait "$CORE_PID" 2>/dev/null || true; fi
  if [[ -n "$DESKTOP_PID" ]]; then kill "$DESKTOP_PID" 2>/dev/null || true; wait "$DESKTOP_PID" 2>/dev/null || true; fi
  pkill -f "$APP_PATH/Contents/Resources/resources/nextplan-core" 2>/dev/null || true
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

wait_for_health() {
  local port="$1"
  local attempts="${2:-60}"
  for ((i=1; i<=attempts; i++)); do
    if curl -fsS "http://127.0.0.1:${port}/healthz" > "$TMP_ROOT/health.json" 2>/dev/null; then
      return 0
    fi
    sleep 1
  done
  return 1
}

# Gate A: the PyInstaller Local Core must be a self-contained native executable.
DIRECT_PORT=47124
NEXTPLAN_LOCAL_DB="$TMP_ROOT/direct.db" \
NEXTPLAN_LOCAL_PORT="$DIRECT_PORT" \
NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN="macos-direct-test" \
NEXTPLAN_LOCAL_PYTHON="/definitely/missing/python3" \
"$CORE" >"$TMP_ROOT/core-direct.log" 2>&1 &
CORE_PID=$!

if ! wait_for_health "$DIRECT_PORT" 45; then
  echo "standalone bundled core did not become healthy" >&2
  cat "$TMP_ROOT/core-direct.log" >&2 || true
  exit 5
fi

python3 - "$TMP_ROOT/health.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1], encoding='utf-8'))
assert body.get('status') == 'ok', body
assert body.get('runtime') == 'nextplan-local-core-v4', body
assert body.get('canonical_store') == 'sqlite-local', body
assert body.get('schema_version') == 3, body
assert (body.get('integrity') or {}).get('ok') is True, body
print('BUNDLED_CORE_ACCEPTANCE_PASS')
PY

kill "$CORE_PID" 2>/dev/null || true
wait "$CORE_PID" 2>/dev/null || true
CORE_PID=""

# Gate B: launch the packaged desktop itself with Python deliberately unavailable.
# If the resource sidecar is missing, the development fallback will fail and /healthz never appears.
mkdir -p "$TMP_ROOT/home"
HOME="$TMP_ROOT/home" \
NEXTPLAN_LOCAL_PYTHON="/definitely/missing/python3" \
"$DESKTOP" >"$TMP_ROOT/desktop.log" 2>&1 &
DESKTOP_PID=$!

if ! wait_for_health 47123 60; then
  echo "packaged desktop did not launch bundled Local Core" >&2
  cat "$TMP_ROOT/desktop.log" >&2 || true
  find "$TMP_ROOT/home" -type f -name 'local-core.log' -print -exec cat {} \; 2>/dev/null || true
  exit 6
fi

python3 - "$TMP_ROOT/health.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1], encoding='utf-8'))
assert body.get('status') == 'ok', body
assert body.get('runtime') == 'nextplan-local-core-v4', body
assert body.get('schema_version') == 3, body
assert (body.get('integrity') or {}).get('ok') is True, body
print('MACOS_CLEAN_MACHINE_ACCEPTANCE_PASS')
PY
