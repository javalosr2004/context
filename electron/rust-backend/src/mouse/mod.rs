use rdev::{listen, Event, EventType};
use serde::{Deserialize, Serialize};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::Arc;
use std::thread::{self, JoinHandle};
use std::time::{SystemTime, UNIX_EPOCH};
use ts_rs::TS;

#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export, export_to = "rust_types.ts")]
pub struct MouseEvent {
    pub x: f32,
    pub y: f32,
    pub event_type: String,
    #[ts(type = "number")]
    pub time_utc_ms: u64,
}

impl MouseEvent {
    pub fn new(x: f32, y: f32, event_type: &str) -> Self {
        let time_utc_ms = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis() as u64;

        MouseEvent {
            x,
            y,
            event_type: event_type.to_string(),
            time_utc_ms,
        }
    }
}

pub struct MouseListener {
    receiver: Receiver<MouseEvent>,
    running: Arc<AtomicBool>,
    _thread: JoinHandle<()>,
}

impl MouseListener {
    pub fn new() -> Self {
        let (tx, rx): (Sender<MouseEvent>, Receiver<MouseEvent>) = channel();
        let running = Arc::new(AtomicBool::new(true));

        let handle = Self::spawn_listener(tx, running.clone());

        MouseListener {
            receiver: rx,
            running,
            _thread: handle,
        }
    }

    fn spawn_listener(tx: Sender<MouseEvent>, running: Arc<AtomicBool>) -> JoinHandle<()> {
        thread::spawn(move || {
            let mut current_x: f32 = 0.0;
            let mut current_y: f32 = 0.0;

            listen(move |event: Event| {
                if let EventType::MouseMove { x, y } = event.event_type {
                    current_x = x as f32;
                    current_y = y as f32;
                    return;
                }

                if !running.load(Ordering::Relaxed) {
                    return;
                }

                match event.event_type {
                    EventType::ButtonPress(button) => {
                        let event_type = format!("mousedown_{:?}", button).to_lowercase();
                        let _ = tx.send(MouseEvent::new(current_x, current_y, &event_type));
                    }
                    EventType::Wheel { .. } => {
                        let _ = tx.send(MouseEvent::new(current_x, current_y, "scroll"));
                    }
                    _ => {}
                }
            })
            .expect("Could not listen to mouse events");
        })
    }

    pub fn start(&self) {
        self.running.store(true, Ordering::Relaxed);
    }

    pub fn stop(&self) {
        self.running.store(false, Ordering::Relaxed);
    }

    pub fn try_recv(&self) -> Option<MouseEvent> {
        self.receiver.try_recv().ok()
    }

    pub fn recv(&self) -> Option<MouseEvent> {
        self.receiver.recv().ok()
    }
}
