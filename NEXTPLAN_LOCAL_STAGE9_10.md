# NextPlan Local v0.1 — Stage 9–10 Release Contract

## Stage 9 — Security / Recovery / Release Hardening

Release requirements:

- Local Core binds only to `127.0.0.1`.
- Browser API calls require a pairing-derived bearer credential.
- After pairing, the credential is bound to the paired Chrome extension origin.
- No arbitrary shell capability is exposed.
- SQLite uses transactions, WAL and `synchronous=FULL`.
- Database health is visible through `PRAGMA quick_check`.
- Canonical writes produce rotating verified recovery checkpoints.
- A corrupt live database is quarantined and recovered from the newest valid checkpoint when possible.
- User backups are ZIP archives containing only `nextplan.db` + `manifest.json`.
- Backup database hashes are verified before restore.
- Browser pairing credentials are removed from exported backups and cleared after restore.
- Restore checkpoints the pre-restore database and requires browser re-pairing.

## Stage 10 — Packaging + Clean Machine Acceptance

Windows v0.1 packaging requirements:

- Build `nextplan-core.exe` with PyInstaller.
- Bundle the Core executable inside the Tauri desktop installer.
- End users do not need Python, Node, Rust, Git, Docker, GitHub or Railway.
- Build a current-user NSIS installer.
- Build a Chrome Manifest V3 release ZIP for the local bridge.
- A fresh Windows CI runner must install the NSIS bundle and reach Local Core v4 while `NEXTPLAN_LOCAL_PYTHON` points to a nonexistent executable.
- The packaged standalone Core must support pairing, canonical project creation, restart persistence, integrity checks and backup creation.
- Release artifacts must be uploaded with SHA-256 hashes.

## Release distinction

Passing Stage 10 produces an installable Windows Beta and a Chrome Web Store-ready extension ZIP. Publishing that ZIP to the Chrome Web Store is a distribution-account action, not part of the canonical runtime or installer build. Until Web Store publication is performed, the extension bundle is suitable for developer/beta installation rather than public one-click Chrome installation.
