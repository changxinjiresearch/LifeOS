use serde::Serialize;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent, State};
use uuid::Uuid;

struct CoreRuntime {
    endpoint: String,
    token: String,
    child: Mutex<Option<Child>>,
    start_error: Mutex<Option<String>>,
}

#[derive(Serialize)]
struct CoreConfig {
    endpoint: String,
    token: String,
    start_error: Option<String>,
}

#[tauri::command]
fn core_config(state: State<'_, CoreRuntime>) -> CoreConfig {
    CoreConfig {
        endpoint: state.endpoint.clone(),
        token: state.token.clone(),
        start_error: state.start_error.lock().ok().and_then(|v| v.clone()),
    }
}

fn main() {
    let port = 47123u16;
    let bootstrap_token = Uuid::new_v4().simple().to_string();
    let runtime = CoreRuntime {
        endpoint: format!("http://127.0.0.1:{port}"),
        token: bootstrap_token,
        child: Mutex::new(None),
        start_error: Mutex::new(None),
    };

    let app = tauri::Builder::default()
        .manage(runtime)
        .invoke_handler(tauri::generate_handler![core_config])
        .setup(move |app| {
            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let db_path = data_dir.join("nextplan.db");
            let state = app.state::<CoreRuntime>();
            let python = std::env::var("NEXTPLAN_LOCAL_PYTHON").unwrap_or_else(|_| {
                if cfg!(target_os = "windows") { "python".into() } else { "python3".into() }
            });
            let repo_root = std::env::var("NEXTPLAN_LOCAL_REPO_ROOT")
                .map(PathBuf::from)
                .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));
            let mut command = Command::new(python);
            command
                .args(["-m", "mcp_server.local_core_v3"])
                .env("NEXTPLAN_LOCAL_DB", &db_path)
                .env("NEXTPLAN_LOCAL_PORT", port.to_string())
                .env("NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN", &state.token)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::null());
            if repo_root.exists() {
                command.current_dir(repo_root);
            }
            match command.spawn() {
                Ok(child) => {
                    if let Ok(mut slot) = state.child.lock() {
                        *slot = Some(child);
                    }
                }
                Err(err) => {
                    if let Ok(mut slot) = state.start_error.lock() {
                        *slot = Some(err.to_string());
                    }
                }
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("failed to build NextPlan desktop app");

    app.run(|handle, event| {
        if matches!(event, RunEvent::Exit) {
            let state = handle.state::<CoreRuntime>();
            if let Ok(mut slot) = state.child.lock() {
                if let Some(child) = slot.as_mut() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                *slot = None;
            }
        }
    });
}
