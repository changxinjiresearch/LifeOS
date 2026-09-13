from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import urllib.request
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "desktop_local" / "ui"
WEB_REPO = "changxinjiresearch/LifeOS-App"
WEB_REF = os.environ.get("NEXTPLAN_WEB_UI_REF", "main").strip() or "main"
BASE = f"https://raw.githubusercontent.com/{WEB_REPO}/{WEB_REF}"
PRESERVE_LOCAL = {"desktop-adapter.js", ".gitignore"}
TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".webmanifest", ".svg", ".txt"}


def fetch_bytes(name: str) -> bytes:
    req = urllib.request.Request(
        f"{BASE}/{name}",
        headers={"User-Agent": "NextPlan-Desktop-Web-Parity-Sync/3.2"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise_local_ref(raw: str) -> str | None:
    value = raw.strip().split("#", 1)[0].split("?", 1)[0]
    if (
        not value
        or "${" in value
        or "{{" in value
        or value.startswith(("http://", "https://", "data:", "blob:", "mailto:", "javascript:", "#", "/"))
    ):
        return None
    while value.startswith("./"):
        value = value[2:]
    path = PurePosixPath(value)
    if not value or value.endswith("/") or ".." in path.parts:
        return None
    return path.as_posix()


def _collect(pattern: str, text: str) -> set[str]:
    refs: set[str] = set()
    for raw in re.findall(pattern, text, flags=re.I | re.S):
        ref = normalise_local_ref(raw)
        if ref:
            refs.add(ref)
    return refs


def discover_css_refs(text: str) -> set[str]:
    return _collect(r'''url\(\s*["']?([^"')]+)["']?\s*\)''', text)


def discover_html_refs(text: str) -> set[str]:
    refs = _collect(r'''(?:src|href)=["']([^"']+)["']''', text)
    for style in re.findall(r'''<style\b[^>]*>(.*?)</style>''', text, flags=re.I | re.S):
        refs |= discover_css_refs(style)
    return refs


def discover_local_refs(text: str) -> set[str]:
    """Compatibility helper: discover static references in an HTML document."""
    return discover_html_refs(text)


def decode_text(name: str, data: bytes) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix not in TEXT_SUFFIXES and Path(name).name != "manifest.webmanifest":
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def child_refs(name: str, text: str) -> set[str]:
    suffix = Path(name).suffix.lower()
    if suffix == ".css":
        return discover_css_refs(text)
    if suffix == ".html":
        return discover_html_refs(text)
    return set()


def fetch_asset_graph(source_index: str) -> dict[str, bytes]:
    pending = discover_html_refs(source_index) | {"sw.js"}
    fetched: dict[str, bytes] = {}
    while pending:
        name = pending.pop()
        if name in fetched or name == "index.html":
            continue
        data = fetch_bytes(name)
        fetched[name] = data
        text = decode_text(name, data)
        if text is not None:
            pending |= child_refs(name, text) - fetched.keys()
    return fetched


def clear_generated_ui() -> None:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    for path in UI_DIR.iterdir():
        if path.name in PRESERVE_LOCAL:
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()


def adapt_runtime_for_desktop(canonical_runtime: str) -> str:
    """Replace only the cloud state-read boundary; never alter rendered UI logic."""
    start = canonical_runtime.find("async function sync(){")
    end = canonical_runtime.find("\nfunction openSearch()", start)
    if start < 0 or end < 0:
        raise SystemExit("Could not locate canonical Web sync function")
    desktop_sync = (
        "async function sync(){if(busy)return;const c=getCfg(),adapter=window.__NEXTPLAN_STATE_ADAPTER__;"
        "if(!c.token){$('syncPill').className='sync-pill';$('syncText').textContent='Local';return}"
        "if(!adapter||typeof adapter.readState!=='function'){console.warn('NextPlan state adapter unavailable');"
        "$('syncPill').className='sync-pill error';$('syncText').textContent='Offline';return}"
        "busy=true;$('syncPill').className='sync-pill syncing';$('syncText').textContent='Syncing';"
        "try{const x=await adapter.readState(c);if(!Array.isArray(x.projects))throw new Error('Invalid state file');"
        "state=x;saveCache();renderAll();$('syncPill').className='sync-pill synced';$('syncText').textContent='Synced'}"
        "catch(e){console.warn('NextPlan sync failed:',e);$('syncPill').className='sync-pill error';"
        "$('syncText').textContent='Offline'}finally{busy=false}}"
    )
    runtime = canonical_runtime[:start] + desktop_sync + canonical_runtime[end:]
    if "await adapter.readState(c)" not in runtime:
        raise SystemExit("Desktop state adapter seam was not installed")
    return runtime


def main() -> None:
    source_index_bytes = fetch_bytes("index.html")
    source_index = source_index_bytes.decode("utf-8")
    assets = fetch_asset_graph(source_index)
    pattern = re.compile(r"<script>\s*(\(\(\)=>\{.*\}\)\(\);)\s*</script>(\s*</body>)", re.S)
    match = pattern.search(source_index)
    if not match:
        raise SystemExit("Could not locate the canonical Web runtime script")
    canonical_runtime = match.group(1).strip() + "\n"
    runtime = adapt_runtime_for_desktop(canonical_runtime)
    desktop_scripts = '<script src="./desktop-adapter.js"></script>\n<script src="./web-runtime.js"></script>'
    desktop_index = source_index[: match.start()] + desktop_scripts + match.group(2) + source_index[match.end() :]
    clear_generated_ui()
    (UI_DIR / "index.html").write_text(desktop_index, encoding="utf-8", newline="\n")
    (UI_DIR / "web-runtime.js").write_text(runtime, encoding="utf-8", newline="\n")
    for name, data in assets.items():
        target = UI_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        "source_repository": WEB_REPO,
        "source_ref": WEB_REF,
        "source_index_sha256": sha256(source_index_bytes),
        "generated_index_sha256": sha256(desktop_index.encode("utf-8")),
        "canonical_web_runtime_sha256": sha256(canonical_runtime.encode("utf-8")),
        "web_runtime_sha256": sha256(runtime.encode("utf-8")),
        "asset_sha256": {name: sha256(data) for name, data in sorted(assets.items())},
        "ui_contract": "LifeOS-App is the only UI authority",
        "data_contract": "Web uses cloud state access; Desktop replaces only the state-read boundary with Local Core -> SQLite",
        "contract": "LifeOS-App is the only UI authority; desktop injects only the local data adapter",
    }
    (UI_DIR / "web-ui-source.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    for name, data in assets.items():
        assert (UI_DIR / name).read_bytes() == data
    adapter_text = (UI_DIR / "desktop-adapter.js").read_text(encoding="utf-8")
    assert desktop_index.count('src="./desktop-adapter.js"') == 1
    assert desktop_index.count('src="./web-runtime.js"') == 1
    assert "window.__NEXTPLAN_STATE_ADAPTER__" in adapter_text
    assert "window.fetch =" not in adapter_text
    assert "await adapter.readState(c)" in runtime
    assert "fetch(apiPath(c)" not in runtime
    assert not (UI_DIR / "app.js").exists()
    assert not (UI_DIR / "styles.css").exists()
    print(f"NextPlan desktop UI synced 1:1 from {WEB_REPO}@{WEB_REF}")
    print(f"source index sha256={manifest['source_index_sha256']}")
    print(f"canonical asset count={len(assets)}")
    print("state adapter boundary=Local Core -> SQLite")


if __name__ == "__main__":
    main()
