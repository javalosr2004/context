use rust_backend::accessibility::init::{AXError, AccessibilityTree};
use rust_backend::mouse::MouseListener;

fn main() {
    let listener = MouseListener::new();
    let tree = match AccessibilityTree::new() {
        Ok(tree) => tree,
        Err(AXError::PermissionDenied) => {
            eprintln!("Accessibility permission not granted.");
            eprintln!("Grant access in: System Settings > Privacy & Security > Accessibility");
            std::process::exit(1);
        }
        Err(err) => {
            eprintln!("Failed to initialize accessibility tree: {err:?}");
            std::process::exit(1);
        }
    };

    tree.activate_all_apps();

    loop {
        let Some(event) = listener.recv() else {
            break;
        };
        let event_type = event.event_type.as_str();
        if !event_type.starts_with("mousedown") {
            continue;
        }
        println!("Mouse down: {} @ ({:.0}, {:.0})", event_type, event.x, event.y);

        match tree.get_ax_element_at_position(event.x, event.y) {
            Ok(elem) => {
                elem.print_element_attributes("Element");
            }
            Err(err) => {
                eprintln!("Failed to get element at mouse position: {err:?}");
            }
        }
    }
}
