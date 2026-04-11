//! Watches for new macOS app launches via NSWorkspaceDidLaunchApplicationNotification
//! and sends the PID of each newly launched app through an `mpsc` channel so the
//! caller can activate AXEnhancedUserInterface on them.

#![allow(unexpected_cfgs)]

use core_foundation::runloop::CFRunLoop;
use objc::declare::ClassDecl;
use objc::runtime::{Class, Object, Sel};
use objc::{class, msg_send, sel, sel_impl};
use std::ffi::CString;
use std::os::raw::c_void;
use std::sync::mpsc::Sender;
use std::sync::Once;
use std::thread::{self, JoinHandle};

#[link(name = "AppKit", kind = "framework")]
extern "C" {}

static REGISTER_CLASS: Once = Once::new();

fn observer_class() -> &'static Class {
    REGISTER_CLASS.call_once(|| {
        let superclass = class!(NSObject);
        let mut decl = ClassDecl::new("RustWorkspaceObserver", superclass).unwrap();
        decl.add_ivar::<*mut c_void>("tx_ptr");
        unsafe {
            decl.add_method(
                sel!(appDidLaunch:),
                app_did_launch as extern "C" fn(&Object, Sel, *mut Object),
            );
        }
        decl.register();
    });
    Class::get("RustWorkspaceObserver").unwrap()
}

unsafe fn ns_string(s: &str) -> *mut Object {
    let c = CString::new(s).unwrap();
    msg_send![class!(NSString), stringWithUTF8String: c.as_ptr()]
}

extern "C" fn app_did_launch(this: &Object, _sel: Sel, notification: *mut Object) {
    unsafe {
        let user_info: *mut Object = msg_send![notification, userInfo];
        if user_info.is_null() {
            return;
        }

        let key = ns_string("NSWorkspaceApplicationKey");
        let running_app: *mut Object = msg_send![user_info, objectForKey: key];
        if running_app.is_null() {
            return;
        }

        let pid: i32 = msg_send![running_app, processIdentifier];
        if pid <= 0 {
            return;
        }

        let bundle_id: *mut Object = msg_send![running_app, bundleIdentifier];
        if !bundle_id.is_null() {
            let utf8: *const i8 = msg_send![bundle_id, UTF8String];
            if !utf8.is_null() {
                let name = std::ffi::CStr::from_ptr(utf8).to_string_lossy();
                eprintln!("workspace: app launched — {name} (pid {pid})");
            }
        }

        let tx_ptr: *mut c_void = *this.get_ivar("tx_ptr");
        if !tx_ptr.is_null() {
            let tx = &*(tx_ptr as *const Sender<i32>);
            let _ = tx.send(pid);
        }
    }
}

/// Observes macOS app launches and forwards their PIDs through a channel.
pub struct WorkspaceObserver {
    _thread: JoinHandle<()>,
}

impl WorkspaceObserver {
    pub fn start(tx: Sender<i32>) -> Self {
        let handle = thread::spawn(move || {
            unsafe {
                let pool: *mut Object = msg_send![class!(NSAutoreleasePool), new];

                // AppKit must be initialised for NSWorkspace in non-app processes.
                let _: *mut Object = msg_send![class!(NSApplication), sharedApplication];

                let cls = observer_class();
                let observer: *mut Object = msg_send![cls, alloc];
                let observer: *mut Object = msg_send![observer, init];

                let tx_box = Box::new(tx);
                let tx_ptr = Box::into_raw(tx_box) as *mut c_void;
                (*observer).set_ivar("tx_ptr", tx_ptr);

                let workspace: *mut Object = msg_send![class!(NSWorkspace), sharedWorkspace];
                let center: *mut Object = msg_send![workspace, notificationCenter];
                let name = ns_string("NSWorkspaceDidLaunchApplicationNotification");
                let nil: *mut Object = std::ptr::null_mut();

                let _: () = msg_send![
                    center,
                    addObserver: observer
                    selector: sel!(appDidLaunch:)
                    name: name
                    object: nil
                ];

                eprintln!("workspace: observing app launches");

                let _: () = msg_send![pool, drain];

                // Block forever — notifications are delivered on this run loop.
                CFRunLoop::run_current();
            }
        });

        Self { _thread: handle }
    }
}
