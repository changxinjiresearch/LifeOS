# NextPlan Local Desktop

`desktop_local/` is the shared Tauri shell used by both Windows and macOS.

## UI authority

The desktop app does **not** maintain its own UI.

`changxinjiresearch/LifeOS-App` is the single UI authority for Web, Windows, and macOS. Before local development or a desktop build, `scripts/sync_web_ui_to_desktop.py` fetches the canonical Web UI, copies its assets into the generated `desktop_local/ui/` bundle, externalizes the canonical Web runtime, and injects only `desktop-adapter.js` ahead of it.

The only hand-maintained files allowed inside `desktop_local/ui/` are:

- `.gitignore`
- `desktop-adapter.js`

HTML, CSS, icons, fonts/references, navigation, layout, system copy, cards, search UI, and all other presentation code come from `LifeOS-App`. Legacy desktop `index.html`, `app.js`, and `styles.css` are intentionally not retained.

## Data boundary

The presentation layer is shared; the data adapter differs by runtime:

```text
Web      -> cloud/state adapter
Desktop  -> desktop-adapter.js -> Local Core -> SQLite
```

The desktop adapter never writes SQLite directly. It talks only to the authenticated Local Core at `http://127.0.0.1:47123`.

## Tauri shell contract

The shared Windows/macOS window defaults are:

- 1180 × 780
- minimum 900 × 620

The shell is resizable. Desktop adaptation must not change the approved Web UI.

## Development

From `desktop_local/`:

```text
npm install
npm run dev
```

`npm run dev`, `npm run build`, and `npm run check:ui` all synchronize the canonical Web UI first, so a local Tauri build cannot intentionally rely on a stale manually maintained Desktop UI.

## Release

Windows release acceptance is defined in `.github/workflows/stage5-local-stage9-10.yml`.

macOS dual-architecture release acceptance is defined in `.github/workflows/nextplan-local-macos-release.yml`.

Both workflows synchronize the canonical Web UI before build and fail if a legacy second Desktop UI is tracked or generated.
