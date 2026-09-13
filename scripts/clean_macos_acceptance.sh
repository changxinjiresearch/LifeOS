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
SYSTEM_PATH="/usr/bin:/bin:/usr/sbin:/sbin"

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
    if /usr/bin/curl -fsS "http://127.0.0.1:${port}/healthz" > "$TMP_ROOT/health.json" 2>/dev/null; then
      return 0
    fi
    /bin/sleep 1
  done
  return 1
}

assert_health_json() {
  local file="$1"
  local status runtime canonical schema integrity
  status="$(/usr/bin/plutil -extract status raw -o - "$file")"
  runtime="$(/usr/bin/plutil -extract runtime raw -o - "$file")"
  canonical="$(/usr/bin/plutil -extract canonical_store raw -o - "$file")"
  schema="$(/usr/bin/plutil -extract schema_version raw -o - "$file")"
  integrity="$(/usr/bin/plutil -extract integrity.ok raw -o - "$file")"
  [[ "$status" == "ok" ]] || { echo "unexpected status: $status" >&2; exit 7; }
  [[ "$runtime" == "nextplan-local-core-v4" ]] || { echo "unexpected runtime: $runtime" >&2; exit 8; }
  [[ "$canonical" == "sqlite-local" ]] || { echo "unexpected canonical store: $canonical" >&2; exit 9; }
  [[ "$schema" == "3" ]] || { echo "unexpected schema: $schema" >&2; exit 10; }
  [[ "$integrity" == "true" || "$integrity" == "1" ]] || { echo "database integrity failed: $integrity" >&2; exit 11; }
}

# Gate A: the PyInstaller Local Core must run as a self-contained executable
# with only normal macOS system paths available. No Python/Node/Rust/Git/Xcode
# path is inherited from the build machine.
DIRECT_PORT=47124
/usr/bin/env -i \
  HOME="$TMP_ROOT" \
  TMPDIR="$TMP_ROOT" \
  PATH="$SYSTEM_PATH" \
  NEXTPLAN_LOCAL_DB="$TMP_ROOT/direct.db" \
  NEXTPLAN_LOCAL_PORT="$DIRECT_PORT" \
  NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN="macos-direct-test" \
  NEXTPLAN_LOCAL_PYTHON="/definitely/missing/python3" \
  PYTHONHOME="/definitely/missing/python" \
  PYTHONPATH="/definitely/missing/python" \
  NODE_PATH="/definitely/missing/node" \
  "$CORE" >"$TMP_ROOT/core-direct.log" 2>&1 &
CORE_PID=$!

if ! wait_for_health "$DIRECT_PORT" 45; then
  echo "standalone bundled core did not become healthy" >&2
  cat "$TMP_ROOT/core-direct.log" >&2 || true
  exit 5
fi

assert_health_json "$TMP_ROOT/health.json"
echo "BUNDLED_CORE_ZERO_DEPENDENCY_PASS"

kill "$CORE_PID" 2>/dev/null || true
wait "$CORE_PID" 2>/dev/null || true
CORE_PID=""

# Gate B: launch the packaged desktop itself in a clean runtime environment.
# If the bundled sidecar is missing, the development fallback cannot succeed.
mkdir -p "$TMP_ROOT/home"
/usr/bin/env -i \
  HOME="$TMP_ROOT/home" \
  TMPDIR="$TMP_ROOT" \
  PATH="$SYSTEM_PATH" \
  NEXTPLAN_LOCAL_PYTHON="/definitely/missing/python3" \
  PYTHONHOME="/definitely/missing/python" \
  PYTHONPATH="/definitely/missing/python" \
  NODE_PATH="/definitely/missing/node" \
  "$DESKTOP" >"$TMP_ROOT/desktop.log" 2>&1 &
DESKTOP_PID=$!

if ! wait_for_health 47123 60; then
  echo "packaged desktop did not launch bundled Local Core" >&2
  cat "$TMP_ROOT/desktop.log" >&2 || true
  find "$TMP_ROOT/home" -type f -name 'local-core.log' -print -exec cat {} \; 2>/dev/null || true
  exit 6
fi

assert_health_json "$TMP_ROOT/health.json"
echo "ZERO_DEPENDENCY_MACOS_ACCEPTANCE_PASS"
