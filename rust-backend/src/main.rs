mod capture;

use capture::screen::take_screenshot;
use serde::{Deserialize, Serialize};
use std::io::{self, BufRead, Write};

#[derive(Deserialize)]
struct Request {
    id: u64,
    method: String,
    #[serde(default)]
    params: serde_json::Value,
}

#[derive(Serialize)]
struct Response {
    id: u64,
    result: serde_json::Value,
}

fn handle_request(req: Request) -> Response {
    let result = match req.method.as_str() {
        "ping" => serde_json::json!({ "message": "pong" }),
        "echo" => req.params,
        "screenshot" => {
            let result = take_screenshot();
            serde_json::json!({"data": result})
        }
        _ => serde_json::json!({ "error": "unknown method" }),
    };

    Response { id: req.id, result }
}

fn main() {
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        let line = match line {
            Ok(l) => l,
            Err(_) => break,
        };

        if line.is_empty() {
            continue;
        }

        let req: Request = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(e) => {
                eprintln!("Parse error: {}", e);
                continue;
            }
        };

        let res = handle_request(req);
        let output = serde_json::to_string(&res).unwrap();
        writeln!(stdout, "{}", output).unwrap();
        stdout.flush().unwrap();
    }
}
