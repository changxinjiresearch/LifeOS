from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI_DIR = ROOT / "desktop_local" / "ui"
WEB_REPO = "changxinjiresearch/LifeOS-App"
WEB_REF = os.environ.get("NEXTPLAN_WEB_UI_REF", "main").strip() or "main"
BASE = f"https://raw.githubusercontent.com/{WEB_REPO}/{WEB_REF}"
ASSETS = ["index.html", "apple-web-v1.css", "icon.svg", "manifest.webmanifest", "sw.js"]


def fetch_bytes(name: str) -> bytes:
    req = urllib.request.Request(
        f"{BASE}/{name}",
        headers={"User-Agent": "NextPlan-Desktop-Web-Parity-Sync/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return response.read()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    UI_DIR.mkdir(parents=True, exist_ok=True)
    fetched = {name: fetch_bytes(name) for name in ASSETS}

    source_index = fetched["index.html"].decode("utf-8")
    # The production Web page keeps its runtime inline. Tauri's bundled desktop
    # page externalizes only that script so the native adapter can run first.
    # This changes no DOM, copy, styling, layout, or user-visible behavior.
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

    (UI_DIR / "index.html").write_text(desktop_index, encoding="utf-8", newline="\n")
    (UI_DIR / "web-runtime.js").write_text(runtime, encoding="utf-8", newline="\n")
    for name in ASSETS[1:]:
        (UI_DIR / name).write_bytes(fetched[name])

    manifest = {
        "source_repository": WEB_REPO,
        "source_ref": WEB_REF,
        "source_index_sha256": sha256(fetched["index.html"]),
        "generated_index_sha256": sha256(desktop_index.encode("utf-8")),
        "web_runtime_sha256": sha256(runtime.encode("utf-8")),
        "asset_sha256": {name: sha256(fetched[name]) for name in ASSETS[1:]},
        "contract": "desktop UI is generated from the canonical Web UI; only an invisible local-data adapter is injected",
    }
    (UI_DIR / "web-ui-source.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    # Hard parity guards. Any mismatch here is a release failure.
    assert (UI_DIR / "apple-web-v1.css").read_bytes() == fetched["apple-web-v1.css"]
    assert (UI_DIR / "icon.svg").read_bytes() == fetched["icon.svg"]
    assert (UI_DIR / "manifest.webmanifest").read_bytes() == fetched["manifest.webmanifest"]
    assert (UI_DIR / "sw.js").read_bytes() == fetched["sw.js"]
    assert desktop_index.count('src="./desktop-adapter.js"') == 1
    assert desktop_index.count('src="./web-runtime.js"') == 1
    print(f"NextPlan desktop UI synced 1:1 from {WEB_REPO}@{WEB_REF}")
    print(f"source index sha256={manifest['source_index_sha256']}")


if __name__ == "__main__":
    main()
