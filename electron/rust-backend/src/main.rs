use clap::{Parser, Subcommand};
use rust_backend::mouse::{MouseEvent, MouseListener};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::io::{self, BufRead, Write};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread::{self, JoinHandle};
use std::time::Duration;
use ts_rs::TS;
use rust_backend::accessibility_sys::init::AccessibilityTree;

// ─── RPC Result Types ───────────────────────────────────────────────────────

#[derive(Serialize, TS)]
#[ts(export, export_to = "rust_types.ts")]
pub struct StatusResult {
    pub status: String,
}

#[derive(Serialize, TS)]
#[ts(export, export_to = "rust_types.ts")]
pub struct GetMouseEventsResult {
    pub events: Vec<CapturedMouseEvent>,
}

#[derive(Serialize, TS)]
#[ts(export, export_to = "rust_types.ts")]
pub struct RpcErrorResult {
    pub error: String,
}

#[derive(Debug, Clone, Serialize, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export, export_to = "rust_types.ts")]
pub struct CapturedMouseEvent {
    pub mouse: MouseEvent,
    #[ts(type = "Record<string, string> | null")]
    pub ax_attributes: Option<BTreeMap<String, String>>,
}

#[derive(Parser)]
#[command(name = "rust-backend")]
#[command(about = "Mouse event listener and JSON-RPC server")]
struct Cli {
    #[command(subcommand)]
    command: Option<Commands>,
}


#[derive(Subcommand)]
enum Commands {
    /// Run in debug mode, printing events to console
    Debug {
        /// Watch click events
        #[arg(short, long)]
        click: bool,

        /// Watch scroll events
        #[arg(short, long)]
        scroll: bool,

        /// Watch all events
        #[arg(short, long)]
        all: bool,
    },
}

static EVENT_COLLECTOR: OnceLock<Arc<Mutex<EventCollector>>> = OnceLock::new();

fn get_event_collector() -> &'static Arc<Mutex<EventCollector>> {
    EVENT_COLLECTOR.get_or_init(|| Arc::new(Mutex::new(EventCollector::new())))
}

enum CollectorCommand {
    Start,
    Stop,
}

struct EventCollector {
    cmd_tx: Sender<CollectorCommand>,
    event_rx: Receiver<CapturedMouseEvent>,
    _thread: JoinHandle<()>,
}

impl EventCollector {
    fn new() -> Self {
        let (cmd_tx, cmd_rx) = channel::<CollectorCommand>();
        let (event_tx, event_rx) = channel::<CapturedMouseEvent>();

        let worker = thread::spawn(move || {
            let listener = MouseListener::new();
            let mut running = true;
            let tree = AccessibilityTree::new().ok();

            loop {
                while let Ok(cmd) = cmd_rx.try_recv() {
                    match cmd {
                        CollectorCommand::Start => {
                            running = true;
                            listener.start();
                        }
                        CollectorCommand::Stop => {
                            running = false;
                            listener.stop();
                        }
                    }
                }

                if !running {
                    thread::sleep(Duration::from_millis(20));
                    continue;
                }

                if let Some(mouse) = listener.try_recv() {
                    let ax_attributes = tree.as_ref().and_then(|t| {
                        t.get_ax_attributes_at_position(mouse.x, mouse.y).ok()
                    });

                    let _ = event_tx.send(CapturedMouseEvent {
                        mouse,
                        ax_attributes,
                    });
                } else {
                    thread::sleep(Duration::from_millis(5));
                }
            }
        });

        Self {
            cmd_tx,
            event_rx,
            _thread: worker,
        }
    }

    fn start(&self) {
        let _ = self.cmd_tx.send(CollectorCommand::Start);
    }

    fn stop(&self) {
        let _ = self.cmd_tx.send(CollectorCommand::Stop);
    }

    fn drain(&self) -> Vec<CapturedMouseEvent> {
        let mut out = Vec::new();
        while let Ok(event) = self.event_rx.try_recv() {
            out.push(event);
        }
        out
    }
}

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
        "start_mouse_listener" => {
            let collector = get_event_collector();
            collector.lock().unwrap().start();
            serde_json::to_value(StatusResult {
                status: "started".to_string(),
            })
            .unwrap()
        }
        "get_mouse_events" => {
            let collector = get_event_collector();
            let events = collector.lock().unwrap().drain();
            serde_json::to_value(GetMouseEventsResult { events }).unwrap()
        }
        "stop_mouse_listener" => {
            let collector = get_event_collector();
            collector.lock().unwrap().stop();
            serde_json::to_value(StatusResult {
                status: "stopped".to_string(),
            })
            .unwrap()
        }
        _ => serde_json::to_value(RpcErrorResult {
            error: "unknown method".to_string(),
        })
        .unwrap(),
    };

    Response { id: req.id, result }
}

fn run_debug_mode(watch_click: bool, watch_scroll: bool) {
    println!("Debug mode: click={}, scroll={}", watch_click, watch_scroll);
    println!("Listening for mouse events... (Ctrl+C to stop)\n");

    // Debug mode is single-consumer, so use a dedicated listener and block on recv().
    let listener = MouseListener::new();

    loop {
        let Some(event) = listener.recv() else {
            break;
        };

        let is_click = event.event_type.starts_with("mousedown");
        let is_scroll = event.event_type.starts_with("scroll");

        if (is_click && watch_click) || (is_scroll && watch_scroll) {
            println!(
                "[{}] {} @ ({:.0}, {:.0})",
                event.time_utc_ms, event.event_type, event.x, event.y
            );
        }
    }
}

fn run_json_rpc() {
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

fn main() {
    let cli = Cli::parse();

    match cli.command {
        Some(Commands::Debug { click, scroll, all }) => {
            run_debug_mode(click || all, scroll || all);
        }
        None => run_json_rpc(),
    }
}
