use serde::Serialize;
use std::fs::OpenOptions;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use tauri::{Manager, RunEvent, State};
use uuid::Uuid;

struct CoreRuntime {
    endpoint: String,
    token: String,
    mode: Mutex<String>,
    child: Mutex<Option<Child>>,
    start_error: Mutex<Option<String>>,
}

#[derive(Serialize)]
struct CoreConfig {
    endpoint: String,
    token: String,
    mode: String,
    start_error: Option<String>,
}

#[tauri::command]
fn core_config(state: State<'_, CoreRuntime>) -> CoreConfig {
    CoreConfig {
        endpoint: state.endpoint.clone(),
        token: state.token.clone(),
        mode: state.mode.lock().map(|v| v.clone()).unwrap_or_else(|_| "unknown".into()),
        start_error: state.start_error.lock().ok().and_then(|v| v.clone()),
    }
}

fn main() {
    let port = 47123u16;
    let bootstrap_token = Uuid::new_v4().simple().to_string();
    let runtime = CoreRuntime {
        endpoint: format!("http://127.0.0.1:{port}"),
        token: bootstrap_token,
        mode: Mutex::new("not-started".into()),
        child: Mutex::new(None),
        start_error: Mutex::new(None),
    };

    let app = tauri::Builder::default()
        .manage(runtime)
        .invoke_handler(tauri::generate_handler![core_config])
        .setup(move |app| {
            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;
            let log_dir = data_dir.join("logs");
            std::fs::create_dir_all(&log_dir)?;
            let db_path = data_dir.join("nextplan.db");
            let state = app.state::<CoreRuntime>();

            let resource_dir = app.path().resource_dir()?;
            let bundled_core = resource_dir
                .join("resources")
                .join(if cfg!(target_os = "windows") { "nextplan-core.exe" } else { "nextplan-core" });

            let mut command;
            if bundled_core.is_file() {
                command = Command::new(&bundled_core);
                if let Ok(mut mode) = state.mode.lock() {
                    *mode = "bundled-sidecar".into();
                }
            } else {
                // Development-only fallback. Release acceptance requires the
                // bundled sidecar path, so end users never need Python.
                let python = std::env::var("NEXTPLAN_LOCAL_PYTHON").unwrap_or_else(|_| {
                    if cfg!(target_os = "windows") { "python".into() } else { "python3".into() }
                });
                command = Command::new(python);
                command.args(["-m", "mcp_server.local_core_v4"]);
                let repo_root = std::env::var("NEXTPLAN_LOCAL_REPO_ROOT")
                    .map(PathBuf::from)
                    .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.."));
                if repo_root.exists() {
                    command.current_dir(repo_root);
                }
                if let Ok(mut mode) = state.mode.lock() {
                    *mode = "python-development-fallback".into();
                }
            }

            let log_path = log_dir.join("local-core.log");
            let stdout = OpenOptions::new().create(true).append(true).open(&log_path)?;
            let stderr = stdout.try_clone()?;
            command
                .env("NEXTPLAN_LOCAL_DB", &db_path)
                .env("NEXTPLAN_LOCAL_PORT", port.to_string())
                .env("NEXTPLAN_LOCAL_BOOTSTRAP_TOKEN", &state.token)
                .stdin(Stdio::null())
                .stdout(Stdio::from(stdout))
                .stderr(Stdio::from(stderr));

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
            let lock_result = state.child.lock();
            if let Ok(mut slot) = lock_result {
                if let Some(child) = slot.as_mut() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
                *slot = None;
            }
        }
    });
}
