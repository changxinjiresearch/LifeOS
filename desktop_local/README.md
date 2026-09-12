# NextPlan Local Desktop

This directory is the Stage 6 Tauri desktop shell for NextPlan Local v0.1.

## Development runtime

The desktop process generates a private bootstrap credential and launches:

```text
python -m mcp_server.local_core_v3
```

with `NEXTPLAN_LOCAL_DB`, `NEXTPLAN_LOCAL_PORT` and `NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN` set by the trusted desktop process. Set `NEXTPLAN_LOCAL_REPO_ROOT` when the desktop process is launched outside the LifeOS repository, and `NEXTPLAN_LOCAL_PYTHON` to override the Python executable.

The webview never writes SQLite directly. It calls the authenticated Local Core at `127.0.0.1:47123`.

## Release boundary

Stage 10 will replace the development Python launch assumption with a bundled Local Core sidecar and produce the signed Windows installer. `bundle.active` therefore remains false in Stage 6–8.
