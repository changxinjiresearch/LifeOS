from __future__ import annotations

import hashlib
import json
import os
import re
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
        headers={"User-Agent": "NextPlan-Desktop-Web-Parity-Sync/2.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalise_local_ref(raw: str) -> str | None:
    value = raw.strip().split("#", 1)[0].split("?", 1)[0]
    if not value or value.startswith(("http://", "https://", "data:", "blob:", "mailto:", "#", "/")):
        return None
    while value.startswith("./"):
        value = value[2:]
    path = PurePosixPath(value)
    if not value or value.endswith("/") or ".." in path.parts:
        return None
    return path.as_posix()


def discover_local_refs(text: str) -> set[str]:
    refs: set[str] = set()
    patterns = (
        r'''(?:src|href)=["']([^"']+)["']''',
        r'''url\(\s*["']?([^"')]+)["']?\s*\)''',
        r'''["'](\.?\.?/[^"']+)["']''',
    )
    for pattern in patterns:
        for raw in re.findall(pattern, text, flags=re.I):
            ref = normalise_local_ref(raw)
            if ref:
                refs.add(ref)
    return refs


def decode_text(name: str, data: bytes) -> str | None:
    suffix = Path(name).suffix.lower()
    if suffix not in TEXT_SUFFIXES and Path(name).name != "manifest.webmanifest":
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


def fetch_asset_graph(source_index: str) -> dict[str, bytes]:
    # sw.js is part of the Web runtime even when registration is expressed from
    # inline JavaScript rather than an HTML src/href attribute.
    pending = discover_local_refs(source_index) | {"sw.js"}
    fetched: dict[str, bytes] = {}
    while pending:
        name = pending.pop()
        if name in fetched or name == "index.html":
            continue
        data = fetch_bytes(name)
        fetched[name] = data
        text = decode_text(name, data)
        if text is not None:
            pending |= discover_local_refs(text) - fetched.keys()
    return fetched


def clear_generated_ui() -> None:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    for path in UI_DIR.iterdir():
        if path.is_file() and path.name not in PRESERVE_LOCAL:
            path.unlink()


def main() -> None:
    source_index_bytes = fetch_bytes("index.html")
    source_index = source_index_bytes.decode("utf-8")
    assets = fetch_asset_graph(source_index)

    # The production Web page keeps its runtime inline. Tauri's bundled desktop
    # page externalizes only that script so the native adapter can run first.
    # This changes no DOM, copy, styling, layout, icons, fonts, or user-visible text.
    pattern = re.compile(r"<script>\s*(\(\(\)=>\{.*\}\)\(\);)\s*</script>(\s*</body>)", re.S)
    match = pattern.search(source_index)
    if not match:
        raise SystemExit("Could not locate the canonical Web runtime script")

    runtime = match.group(1).strip() + "\n"
    desktop_scripts = (
        '<script src="./desktop-adapter.js"></script>\n'
        '<script src="./web-runtime.js"></script>'
    )
    desktop_index = source_index[: match.start()] + desktop_scripts + match.group(2) + source_index[match.end() :]

    # desktop_local/ui is a generated bundle directory, not a second UI source.
    # Only the local data adapter and the ignore rule are hand-maintained here.
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
        "web_runtime_sha256": sha256(runtime.encode("utf-8")),
        "asset_sha256": {name: sha256(data) for name, data in sorted(assets.items())},
        "contract": "LifeOS-App is the only UI authority; desktop injects only the local data adapter",
    }
    (UI_DIR / "web-ui-source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Hard parity guards. Any mismatch here is a release failure.
    for name, data in assets.items():
        assert (UI_DIR / name).read_bytes() == data
    assert desktop_index.count('src="./desktop-adapter.js"') == 1
    assert desktop_index.count('src="./web-runtime.js"') == 1
    assert not (UI_DIR / "app.js").exists()
    assert not (UI_DIR / "styles.css").exists()
    print(f"NextPlan desktop UI synced 1:1 from {WEB_REPO}@{WEB_REF}")
    print(f"source index sha256={manifest['source_index_sha256']}")
    print(f"canonical asset count={len(assets)}")


if __name__ == "__main__":
    main()
