from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]


def test_desktop_release_uses_bundled_core_and_external_app_data():
    rust = (ROOT / 'desktop_local/src-tauri/src/main.rs').read_text(encoding='utf-8')
    assert 'app.path().app_data_dir()?' in rust
    assert 'data_dir.join("nextplan.db")' in rust
    assert 'app.path().resource_dir()?' in rust
    assert 'resources' in rust
    assert 'nextplan-core.exe' in rust
    assert 'nextplan-core' in rust
    assert 'bundled-sidecar' in rust
    assert 'python-development-fallback' in rust


def test_windows_installer_is_current_user_and_bundled():
    conf = json.loads((ROOT / 'desktop_local/src-tauri/tauri.conf.json').read_text(encoding='utf-8'))
    assert conf['bundle']['active'] is True
    assert conf['bundle']['windows']['nsis']['installMode'] == 'currentUser'
    assert 'resources/**/*' in conf['bundle']['resources']


def test_clean_machine_gates_hide_developer_toolchains():
    win = (ROOT / 'scripts/clean_machine_acceptance.ps1').read_text(encoding='utf-8')
    mac = (ROOT / 'scripts/clean_macos_acceptance.sh').read_text(encoding='utf-8')

    assert 'definitely-not-python' in win
    assert '$env:NODE_PATH' in win
    assert '$env:PATH = "$env:SystemRoot\\System32;$env:SystemRoot"' in win
    assert 'ZERO_DEPENDENCY_WINDOWS_ACCEPTANCE_PASS' in win

    assert '/usr/bin/env -i' in mac
    assert 'PATH="$SYSTEM_PATH"' in mac
    assert 'definitely/missing/python3' in mac
    assert 'definitely/missing/node' in mac
    assert 'ZERO_DEPENDENCY_MACOS_ACCEPTANCE_PASS' in mac


def test_release_contract_declares_no_end_user_dev_dependencies():
    contract = (ROOT / 'docs/RELEASE_PACKAGING_V1.md').read_text(encoding='utf-8')
    for tool in ('Python', 'Node.js', 'npm', 'Rust', 'Cargo', 'Git', 'Xcode'):
        assert tool in contract
    assert 'must not need' in contract
    assert 'NextPlan-Setup-v0.1.0.exe' in contract
    assert 'NextPlan-v0.1.0-macOS-apple-silicon.dmg' in contract
    assert 'NextPlan-v0.1.0-macOS-intel.dmg' in contract
