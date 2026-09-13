use serde::Serialize;
use std::fs::OpenOptions;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;
use std::time::Duration;
use tauri::{Manager, RunEvent, State};
use uuid::Uuid;

const EXPECTED_EXTENSION_ID: &str = "gbdcbnbdmkgjffjioohjfidjmchiggpc";

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

fn header_value(request: &str, name: &str) -> Option<String> {
    request.lines().skip(1).find_map(|line| {
        let (key, value) = line.split_once(':')?;
        key.trim().eq_ignore_ascii_case(name).then(|| value.trim().to_string())
    })
}

fn expected_extension_origin() -> String {
    format!("chrome-extension://{EXPECTED_EXTENSION_ID}")
}

fn extension_origin(request: &str) -> Option<String> {
    let origin = header_value(request, "Origin")?;
    (origin == expected_extension_origin()).then_some(origin)
}

fn extension_identity(request: &str) -> Option<String> {
    let origin = extension_origin(request)?;
    let extension_id = header_value(request, "X-NextPlan-Extension-Id")?;
    if extension_id == EXPECTED_EXTENSION_ID {
        Some(origin)
    } else {
        None
    }
}

fn write_http_response(stream: &mut TcpStream, status: &str, origin: Option<&str>, body: &str) {
    let mut headers = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json; charset=utf-8\r\nContent-Length: {}\r\nCache-Control: no-store\r\nConnection: close\r\n",
        body.len()
    );
    if let Some(origin) = origin {
        headers.push_str(&format!(
            "Access-Control-Allow-Origin: {origin}\r\nAccess-Control-Allow-Methods: POST, OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type, X-NextPlan-Extension-Id\r\nVary: Origin\r\n"
        ));
    }
    headers.push_str("\r\n");
    let _ = stream.write_all(headers.as_bytes());
    let _ = stream.write_all(body.as_bytes());
    let _ = stream.flush();
}

fn reset_persistent_pairing(core_port: u16, token: &str) -> bool {
    for _ in 0..50 {
        if let Ok(mut stream) = TcpStream::connect(("127.0.0.1", core_port)) {
            let _ = stream.set_read_timeout(Some(Duration::from_millis(500)));
            let request = format!(
                "POST /pairing/reset HTTP/1.1\r\nHost: 127.0.0.1:{core_port}\r\nAuthorization: Bearer {token}\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{{}}"
            );
            if stream.write_all(request.as_bytes()).is_ok() {
                let mut response = [0u8; 512];
                if let Ok(n) = stream.read(&mut response) {
                    let first = String::from_utf8_lossy(&response[..n]);
                    if first.starts_with("HTTP/1.1 200") || first.starts_with("HTTP/1.0 200") {
                        return true;
                    }
                }
            }
        }
        thread::sleep(Duration::from_millis(100));
    }
    false
}

fn handle_bridge_connection(mut stream: TcpStream, core_port: u16, token: &str) {
    let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
    let mut buffer = [0u8; 8192];
    let n = match stream.read(&mut buffer) {
        Ok(n) if n > 0 => n,
        _ => return,
    };
    let request = String::from_utf8_lossy(&buffer[..n]).to_string();
    let first_line = request.lines().next().unwrap_or("");

    if first_line.starts_with("OPTIONS ") {
        if let Some(origin) = extension_origin(&request) {
            write_http_response(&mut stream, "204 No Content", Some(&origin), "");
        } else {
            write_http_response(&mut stream, "403 Forbidden", None, "{\"error\":\"official_extension_required\"}");
        }
        return;
    }

    if !first_line.starts_with("POST /bridge/bootstrap ") {
        write_http_response(&mut stream, "404 Not Found", None, "{\"error\":\"not_found\"}");
        return;
    }

    let Some(origin) = extension_identity(&request) else {
        write_http_response(&mut stream, "403 Forbidden", None, "{\"error\":\"official_extension_required\"}");
        return;
    };

    if !reset_persistent_pairing(core_port, token) {
        write_http_response(
            &mut stream,
            "503 Service Unavailable",
            Some(&origin),
            "{\"error\":\"local_core_not_ready\"}",
        );
        return;
    }

    let body = format!(
        "{{\"status\":\"connected\",\"endpoint\":\"http://127.0.0.1:{core_port}\",\"token\":\"{token}\",\"session\":\"desktop-bootstrap\"}}"
    );
    write_http_response(&mut stream, "200 OK", Some(&origin), &body);
}

fn start_browser_bootstrap_bridge(core_port: u16, bridge_port: u16, token: String) {
    thread::spawn(move || {
        let listener = match TcpListener::bind(("127.0.0.1", bridge_port)) {
            Ok(listener) => listener,
            Err(_) => return,
        };
        for stream in listener.incoming().flatten() {
            handle_bridge_connection(stream, core_port, &token);
        }
    });
}

fn main() {
    let port = 47123u16;
    let bridge_port = 47124u16;
    let bootstrap_token = Uuid::new_v4().simple().to_string();
    let bridge_token = bootstrap_token.clone();
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
                    start_browser_bootstrap_bridge(port, bridge_port, bridge_token.clone());
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
