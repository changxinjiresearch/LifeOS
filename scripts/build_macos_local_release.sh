#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "ERROR: This script must run on macOS." >&2
  exit 1
fi

for cmd in git python3 node npm cargo rustc file shasum ditto xcode-select; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: Missing required command: $cmd" >&2
    exit 1
  fi
done

if ! xcode-select -p >/dev/null 2>&1; then
  echo "ERROR: Xcode Command Line Tools are not installed. Run: xcode-select --install" >&2
  exit 1
fi

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) ARTIFACT_ARCH="apple-silicon" ;;
  x86_64) ARTIFACT_ARCH="intel" ;;
  *)
    echo "ERROR: Unsupported Mac architecture: $ARCH" >&2
    exit 1
    ;;
esac

HEAD_SHA="$(git rev-parse HEAD)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "Building NextPlan Local from branch=$BRANCH commit=$HEAD_SHA arch=$ARCH"

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Working tree is not clean. Commit/stash local changes before building." >&2
  git status --short
  exit 1
fi

VENV="$ROOT_DIR/.venv-macos-release"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
python -m pip install --upgrade pip
pip install -r mcp_server/requirements.txt pytest pytest-asyncio pyinstaller

echo "== Sync canonical LifeOS-App Web UI =="
python scripts/sync_web_ui_to_desktop.py
test -f desktop_local/ui/web-runtime.js
test -f desktop_local/ui/apple-web-v1.css
test -f desktop_local/ui/web-ui-source.json
test ! -e desktop_local/ui/app.js
test ! -e desktop_local/ui/styles.css

echo "== Run shared UI / local runtime tests =="
python -m py_compile \
  mcp_server/storage_v3.py \
  mcp_server/local_core_v4.py \
  mcp_server/local_execution_v1.py \
  scripts/local_core_entry.py \
  scripts/sync_web_ui_to_desktop.py
python -m pytest -q \
  tests/test_shared_ui_adapter_contract.py \
  tests/test_local_stage9_10.py \
  tests/test_local_stage6_8.py \
  tests/test_local_stage4_5.py \
  tests/test_local_stage1_3.py \
  tests/test_conversation_capture.py
node --check desktop_local/ui/desktop-adapter.js
node --check desktop_local/ui/web-runtime.js
node --check chrome_extension_local/background.js
node --check chrome_extension_local/content.js
node --check chrome_extension_local/popup.js
node --check chrome_extension_local/options.js

python - <<'PY'
from pathlib import Path
import hashlib
import json
import subprocess

execution = Path('mcp_server/local_execution_v1.py').read_text()
core = Path('mcp_server/local_core_v4.py').read_text()
rust = Path('desktop_local/src-tauri/src/main.rs').read_text()
conf = json.loads(Path('desktop_local/src-tauri/tauri.conf.json').read_text())
index = Path('desktop_local/ui/index.html').read_text(encoding='utf-8')
runtime = Path('desktop_local/ui/web-runtime.js').read_text(encoding='utf-8')
adapter = Path('desktop_local/ui/desktop-adapter.js').read_text(encoding='utf-8')
source = json.loads(Path('desktop_local/ui/web-ui-source.json').read_text(encoding='utf-8'))
tracked_ui = set(subprocess.run(
    ['git', 'ls-files', 'desktop_local/ui'],
    check=True,
    capture_output=True,
    text=True,
).stdout.splitlines())

assert 'platform.system().lower()' in execution
assert 'system == "darwin"' in execution
assert 'subprocess.Popen(["open", str(path)]' in execution
assert 'subprocess.Popen(["open", "-a", str(path)]' in execution
assert '127.0.0.1' in core
assert 'shell.execute' not in core
assert 'bundled-sidecar' in rust
assert 'nextplan-core.exe' in rust and 'nextplan-core' in rust
assert conf['bundle']['active'] is True
window = conf['app']['windows'][0]
assert (window['width'], window['height']) == (1180, 780)
assert (window['minWidth'], window['minHeight']) == (900, 620)
assert source['source_repository'] == 'changxinjiresearch/LifeOS-App'
assert source['ui_contract'] == 'LifeOS-App is the only UI authority'
assert source['data_contract'] == 'Web uses cloud state access; Desktop replaces only the state-read boundary with Local Core -> SQLite'
assert source['contract'] == 'LifeOS-App is the only UI authority; desktop injects only the local data adapter'
assert 'desktop-adapter.js' in index and 'web-runtime.js' in index
assert 'Good morning' in runtime
assert 'window.__NEXTPLAN_STATE_ADAPTER__' in adapter
assert "kind: 'local'" in adapter
assert 'window.fetch =' not in adapter
assert 'await adapter.readState(c)' in runtime
assert 'fetch(apiPath(c)' not in runtime
assert tracked_ui == {
    'desktop_local/ui/.gitignore',
    'desktop_local/ui/desktop-adapter.js',
}
assert not Path('desktop_local/ui/app.js').exists()
assert not Path('desktop_local/ui/styles.css').exists()
for name, expected in source['asset_sha256'].items():
    actual = hashlib.sha256((Path('desktop_local/ui') / name).read_bytes()).hexdigest()
    assert actual == expected, name
print('Shared UI authority + macOS state adapter contract PASS')
PY

echo "== Build standalone Local Core =="
rm -rf build/nextplan-core dist/nextplan-core nextplan-core.spec
pyinstaller --noconfirm --clean --onefile --name nextplan-core --paths . \
  --hidden-import uvicorn.logging \
  --hidden-import uvicorn.loops.auto \
  --hidden-import uvicorn.protocols.http.auto \
  --hidden-import uvicorn.protocols.websockets.auto \
  --hidden-import uvicorn.lifespan.on \
  scripts/local_core_entry.py
test -x dist/nextplan-core
mkdir -p desktop_local/src-tauri/resources
cp dist/nextplan-core desktop_local/src-tauri/resources/nextplan-core
chmod +x desktop_local/src-tauri/resources/nextplan-core

echo "== Build Tauri app + DMG =="
npx --yes @tauri-apps/cli@2 icon desktop_local/src-tauri/icons/icon.png --output desktop_local/src-tauri/icons
test -f desktop_local/src-tauri/icons/icon.icns
cargo check --manifest-path desktop_local/src-tauri/Cargo.toml
npx --yes @tauri-apps/cli@2 build --bundles app,dmg --config desktop_local/src-tauri/tauri.conf.json

APP="$(find desktop_local/src-tauri/target/release/bundle/macos -maxdepth 1 -name '*.app' -print -quit)"
DMG="$(find desktop_local/src-tauri/target/release/bundle/dmg -maxdepth 1 -name '*.dmg' -print -quit)"
test -n "$APP" && test -d "$APP"
test -n "$DMG" && test -f "$DMG"
test -x "$APP/Contents/Resources/resources/nextplan-core"

echo "== Clean-machine acceptance =="
chmod +x scripts/clean_macos_acceptance.sh
scripts/clean_macos_acceptance.sh "$APP"

echo "== Package local release artifacts =="
RELEASE_DIR="$ROOT_DIR/release-artifacts-local"
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"
cp "$DMG" "$RELEASE_DIR/NextPlan-Local-v0.1.0-macOS-${ARTIFACT_ARCH}.dmg"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$RELEASE_DIR/NextPlan-Local-v0.1.0-macOS-${ARTIFACT_ARCH}.app.zip"
(
  cd chrome_extension_local
  zip -qr "$RELEASE_DIR/NextPlan-Local-Bridge-v0.1.0.zip" .
)
cat > "$RELEASE_DIR/BUILD-INFO.txt" <<EOF
branch=$BRANCH
commit=$HEAD_SHA
architecture=$ARCH
artifact_arch=$ARTIFACT_ARCH
built_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ui_authority=changxinjiresearch/LifeOS-App
EOF
(
  cd "$RELEASE_DIR"
  shasum -a 256 * | tee SHA256SUMS.txt
)

echo
echo "SUCCESS"
echo "Latest unified-UI macOS build created from commit: $HEAD_SHA"
echo "DMG: $RELEASE_DIR/NextPlan-Local-v0.1.0-macOS-${ARTIFACT_ARCH}.dmg"
echo "APP ZIP: $RELEASE_DIR/NextPlan-Local-v0.1.0-macOS-${ARTIFACT_ARCH}.app.zip"
echo "Bridge ZIP: $RELEASE_DIR/NextPlan-Local-Bridge-v0.1.0.zip"
