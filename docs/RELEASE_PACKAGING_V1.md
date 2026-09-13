# NextPlan Release Packaging v1

## End-user contract

NextPlan Desktop is distributed as a prebuilt, self-contained installer. End users must not need Python, Node.js, npm, Rust, Cargo, Git, Xcode, Visual Studio Build Tools, or any other developer toolchain to install or run NextPlan.

Supported distributables:

- Windows: `NextPlan-Setup-v0.1.1.exe`
- macOS Apple Silicon: `NextPlan-v0.1.1-macOS-apple-silicon.dmg`
- macOS Intel: `NextPlan-v0.1.1-macOS-intel.dmg`
- Chrome/Chromium bridge beta bundle: `NextPlan-Local-Bridge-v0.1.1.zip`

The Tauri application launches the PyInstaller-built `nextplan-core` executable from inside the installed application bundle. User data is stored in the platform application-data directory, outside the installation bundle, so replacing or upgrading the app does not replace the SQLite database.

## Build-time vs runtime dependencies

Python, Node/npm, Rust/Cargo, PyInstaller, and the platform build toolchain are build-machine dependencies only. They are allowed in GitHub Actions or on a developer release machine, but never form part of the end-user runtime contract.

Clean-machine acceptance must launch the installed application with development-tool paths unavailable. A release is not distributable unless the installed application starts its bundled Local Core and `/healthz` reports `nextplan-local-core-v4` with database integrity OK.

## Browser bootstrap contract

NextPlan Desktop owns a loopback-only bootstrap service on `127.0.0.1:47124`. The Chrome/Chromium bridge uses it to obtain the current Desktop session credential automatically. End users must not copy tokens or enter a pairing code.

The v0.1.1 beta Bridge has a stable public extension key whose Chrome extension ID is `gbdcbnbdmkgjffjioohjfidjmchiggpc`. The Desktop bootstrap service accepts only the exact origin `chrome-extension://gbdcbnbdmkgjffjioohjfidjmchiggpc`. CORS preflight validates that exact origin, and the actual bootstrap POST additionally requires `X-NextPlan-Extension-Id: gbdcbnbdmkgjffjioohjfidjmchiggpc`. Ordinary web pages and other Chrome extensions are rejected.

The returned credential is the current random Desktop bootstrap token and changes on every Desktop launch. The Bridge reuses a valid session credential and automatically re-bootstraps only when the Desktop session changes or the credential is no longer valid.

Before handing the session credential to the official browser bridge, the Desktop shell clears any legacy persisted extension-pairing metadata through the authenticated Local Core `/pairing/reset` path. This prevents an old extension ID from blocking a clean v0.1.1 connection.

Release acceptance must prove all of the following on Windows, macOS Apple Silicon, and macOS Intel:

- the installed app starts without Python/Node/Rust/Git/Xcode on PATH;
- Local Core is healthy on `127.0.0.1:47123`;
- the official NextPlan Bridge origin passes CORS preflight on `127.0.0.1:47124`;
- the official Bridge can bootstrap a session credential and use it to read local state;
- a normal web origin such as `https://example.com` is rejected by the bootstrap service;
- a different Chrome extension ID is rejected by the bootstrap service.

## Beta security confirmation

Unsigned/unnotarized beta builds may require a first-launch security confirmation on macOS. Unsigned Windows installers may trigger Microsoft Defender SmartScreen. These are accepted beta limitations and are separate from runtime dependency requirements.

## Chrome Bridge distribution boundary

The desktop installer is self-contained and the browser connection is automatic once the Bridge is installed. Consumer Chrome does not permit an ordinary third-party desktop installer to silently sideload an arbitrary browser extension. Until the Bridge is distributed through an approved browser installation channel such as the Chrome Web Store, beta users may still need to install the provided Bridge bundle manually with Chrome Developer Mode / Load unpacked. This packaging limitation must not be confused with application runtime dependencies.
