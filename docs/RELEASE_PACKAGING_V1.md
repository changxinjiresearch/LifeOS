# NextPlan Release Packaging v1

## End-user contract

NextPlan Desktop is distributed as a prebuilt, self-contained installer. End users must not need Python, Node.js, npm, Rust, Cargo, Git, Xcode, Visual Studio Build Tools, or any other developer toolchain to install or run NextPlan.

Supported distributables:

- Windows: `NextPlan-Setup-v0.1.0.exe`
- macOS Apple Silicon: `NextPlan-v0.1.0-macOS-apple-silicon.dmg`
- macOS Intel: `NextPlan-v0.1.0-macOS-intel.dmg`

The Tauri application launches the PyInstaller-built `nextplan-core` executable from inside the installed application bundle. User data is stored in the platform application-data directory, outside the installation bundle, so replacing or upgrading the app does not replace the SQLite database.

## Build-time vs runtime dependencies

Python, Node/npm, Rust/Cargo, PyInstaller, and the platform build toolchain are build-machine dependencies only. They are allowed in GitHub Actions or on a developer release machine, but never form part of the end-user runtime contract.

Clean-machine acceptance must launch the installed application with development-tool paths unavailable. A release is not distributable unless the installed application starts its bundled Local Core and `/healthz` reports `nextplan-local-core-v4` with database integrity OK.

## Beta security confirmation

Unsigned/unnotarized beta builds may require a first-launch security confirmation on macOS. Unsigned Windows installers may trigger Microsoft Defender SmartScreen. These are accepted beta limitations and are separate from runtime dependency requirements.

## Chrome Bridge boundary

The desktop installer is self-contained. Consumer Chrome does not permit an ordinary third-party desktop installer to silently sideload an arbitrary browser extension. Until the Bridge is distributed through an approved browser installation channel, it remains a separate installation boundary and the product must not be described as full-product one-click onboarding.
