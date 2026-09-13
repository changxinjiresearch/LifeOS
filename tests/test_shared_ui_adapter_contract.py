from pathlib import Path

from scripts.sync_web_ui_to_desktop import adapt_runtime_for_desktop, discover_local_refs


ROOT = Path(__file__).resolve().parents[1]


def test_desktop_runtime_replaces_only_sync_state_boundary():
    canonical = """(()=>{\nconst before='keep-before';\nasync function sync(){const canonicalCloudCall=fetch(apiPath(c));return canonicalCloudCall}\nfunction openSearch(){return 'keep-after'}\n})();\n"""
    adapted = adapt_runtime_for_desktop(canonical)

    assert "const before='keep-before'" in adapted
    assert "function openSearch(){return 'keep-after'}" in adapted
    assert "await adapter.readState(c)" in adapted
    assert "fetch(apiPath(c)" not in adapted
    assert adapted.startswith("(()=>{\nconst before='keep-before';\n")
    assert adapted.endswith("\nfunction openSearch(){return 'keep-after'}\n})();\n")


def test_static_asset_discovery_ignores_runtime_generated_urls_and_routes():
    source = """
    <link rel="stylesheet" href="./apple-web-v1.css?v=1">
    <script src="./current-action.js"></script>
    <style>.logo{background-image:url('./icon.svg')}</style>
    <script>
      const apiRoute='./api/state';
      const internalView='./projects/today';
      const parsed=new URL(request.url);
      const markup=`<a href="${esc(loc)}">Open</a>`;
    </script>
    """
    refs = discover_local_refs(source)

    assert "apple-web-v1.css" in refs
    assert "current-action.js" in refs
    assert "icon.svg" in refs
    assert "api/state" not in refs
    assert "projects/today" not in refs
    assert "request.url" not in refs
    assert "${esc(loc)}" not in refs


def test_desktop_adapter_is_explicit_and_does_not_monkeypatch_fetch():
    adapter = (ROOT / "desktop_local" / "ui" / "desktop-adapter.js").read_text(encoding="utf-8")

    assert "window.__NEXTPLAN_STATE_ADAPTER__" in adapter
    assert "kind: 'local'" in adapter
    assert "async function readState()" in adapter
    assert "`${cfg.endpoint}/state`" in adapter
    assert "window.fetch =" not in adapter


def test_no_legacy_hand_maintained_desktop_ui_files():
    ui = ROOT / "desktop_local" / "ui"
    assert not (ui / "app.js").exists()
    assert not (ui / "styles.css").exists()
    ignore = (ui / ".gitignore").read_text(encoding="utf-8")
    assert "*" in ignore
    assert "!desktop-adapter.js" in ignore
