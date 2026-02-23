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
    /// Flag to pause/resume sending events (true = running)
    running: Arc<AtomicBool>,
    /// Handle to the listener thread (kept for potential future use)
    _thread: JoinHandle<()>,
}

impl MouseListener {
    /// Create a new mouse listener and start listening immediately.
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

    /// Spawn the listener thread.
    fn spawn_listener(tx: Sender<MouseEvent>, running: Arc<AtomicBool>) -> JoinHandle<()> {
        thread::spawn(move || {
            let mut current_x: f32 = 0.0;
            let mut current_y: f32 = 0.0;

            listen(move |event: Event| {
                // Always track mouse position (even when paused)
                if let EventType::MouseMove { x, y } = event.event_type {
                    current_x = x as f32;
                    current_y = y as f32;
                    return;
                }

                // Skip sending events if paused
                if !running.load(Ordering::Relaxed) {
                    return;
                }

                match event.event_type {
                    EventType::ButtonPress(button) => {
                        let event_type = format!("mousedown_{:?}", button).to_lowercase();
                        let _ = tx.send(MouseEvent::new(current_x, current_y, &event_type));
                    }
                    EventType::Wheel { delta_x: _delta_x, delta_y: _delta_y } => {
                        let event_type = format!("scroll");
                        let _ = tx.send(MouseEvent::new(current_x, current_y, &event_type));
                    }
                    _ => {}
                }
            })
            .expect("Could not listen to mouse events");
        })
    }

    /// Start (resume) listening for mouse events.
    pub fn start(&self) {
        self.running.store(true, Ordering::Relaxed);
    }

    /// Stop (pause) listening for mouse events.
    /// Position tracking continues, but events won't be sent to the channel.
    pub fn stop(&self) {
        self.running.store(false, Ordering::Relaxed);
    }

    /// Returns true if the listener is currently sending events.
    pub fn is_running(&self) -> bool {
        self.running.load(Ordering::Relaxed)
    }

    /// Try to receive a mouse event without blocking.
    /// Returns None if there is no event available.
    pub fn try_recv(&self) -> Option<MouseEvent> {
        self.receiver.try_recv().ok()
    }

    /// Receive a mouse event, blocking until one is available.
    pub fn recv(&self) -> Option<MouseEvent> {
        self.receiver.recv().ok()
    }

    /// Drain all pending mouse events.
    /// Returns a vector of all events.
    pub fn drain(&self) -> Vec<MouseEvent> {
        let mut events = Vec::new();
        while let Ok(event) = self.receiver.try_recv() {
            events.push(event);
        }
        events
    }
}
