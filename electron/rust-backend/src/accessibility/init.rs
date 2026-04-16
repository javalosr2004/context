use crate::accessibility::ax_snapshot::AxSnapshot;
use crate::accessibility::element::OwnedAXUIElement;
use accessibility_sys::{
    AXIsProcessTrustedWithOptions, AXUIElementCopyElementAtPosition,
    AXUIElementCreateApplication, AXUIElementCreateSystemWide, AXUIElementGetPid,
    AXUIElementRef, AXUIElementSetAttributeValue, kAXTrustedCheckOptionPrompt,
};
use core_foundation::{
    base::TCFType,
    boolean::CFBoolean,
    dictionary::CFDictionary,
    number::CFNumber,
    string::CFString,
};
use core_foundation_sys::dictionary::CFDictionaryGetValue;
use core_graphics::window::{
    copy_window_info, kCGNullWindowID, kCGWindowListExcludeDesktopElements, kCGWindowOwnerPID,
};
use std::cell::RefCell;
use std::collections::HashSet;
use std::ptr;
use std::thread;
use std::time::Duration;

#[derive(Debug)]
pub enum AXError {
    PermissionDenied,
    NullSystemWideElement,
    NullElement,
    CopyElementAtPositionErr(i32),
    CopyElementAttributesErr(i32),
}

pub struct AccessibilityTree {
    root: OwnedAXUIElement,
    /// PIDs for which we've already set AXEnhancedUserInterface.
    enhanced_pids: RefCell<HashSet<i32>>,
}

impl AccessibilityTree {
    pub fn new() -> Result<Self, AXError> {
        let key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
        let value = CFBoolean::false_value();

        let options = CFDictionary::from_CFType_pairs(&[(key, value)]);

        let trusted = unsafe { AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef()) };

        if !trusted {
            return Err(AXError::PermissionDenied);
        }

        let root = unsafe { AXUIElementCreateSystemWide() };
        let root = OwnedAXUIElement::from_create_rule(root).ok_or(AXError::NullSystemWideElement)?;

        Ok(Self {
            root,
            enhanced_pids: RefCell::new(HashSet::new()),
        })
    }

    /// Set `AXEnhancedUserInterface` on every app that currently owns a window.
    /// This causes Chromium-based apps (and others) to eagerly populate their
    /// accessibility trees before the first hit-test.
    /// Returns the number of newly activated apps.
    pub fn activate_all_apps(&self) -> usize {
        let pid_key = unsafe { CFString::wrap_under_get_rule(kCGWindowOwnerPID) };
        let Some(info) = copy_window_info(kCGWindowListExcludeDesktopElements, kCGNullWindowID)
        else {
            return 0;
        };

        let mut count = 0usize;
        let mut pids = self.enhanced_pids.borrow_mut();
        for dict_ptr in info.get_all_values() {
            let pid_ptr = unsafe {
                CFDictionaryGetValue(dict_ptr as _, pid_key.as_concrete_TypeRef() as _)
            };
            if pid_ptr.is_null() {
                continue;
            }
            let cf_num: CFNumber = unsafe { CFNumber::wrap_under_get_rule(pid_ptr as _) };
            let Some(pid) = cf_num.to_i32() else {
                continue;
            };
            if !pids.insert(pid) {
                continue;
            }
            eprintln!("AXEnhancedUserInterface → pid {pid}");
            Self::set_enhanced_ui_for_pid(pid);
            count += 1;
        }
        count
    }

    fn set_enhanced_ui_for_pid(pid: i32) {
        let app_ptr = unsafe { AXUIElementCreateApplication(pid) };
        let Some(app) = OwnedAXUIElement::from_create_rule(app_ptr) else {
            return;
        };
        let attr = CFString::new("AXEnhancedUserInterface");
        let val = CFBoolean::true_value();
        unsafe {
            AXUIElementSetAttributeValue(
                app.as_ptr(),
                attr.as_concrete_TypeRef(),
                val.as_CFTypeRef(),
            );
        }
    }

    /// Tell the app owning `elem` to expose its full accessibility tree.
    /// Returns `true` when a previously-unseen app was activated (caller may re-hit-test).
    fn ensure_enhanced_ui(&self, elem: &OwnedAXUIElement) -> bool {
        let mut pid: i32 = 0;
        if unsafe { AXUIElementGetPid(elem.as_ptr(), &mut pid) } != 0 || pid == 0 {
            return false;
        }

        if !self.enhanced_pids.borrow_mut().insert(pid) {
            return false;
        }

        Self::set_enhanced_ui_for_pid(pid);
        true
    }

    fn hit_test(&self, x: f32, y: f32) -> Result<OwnedAXUIElement, AXError> {
        unsafe {
            let mut elem: AXUIElementRef = ptr::null_mut();
            let err = AXUIElementCopyElementAtPosition(self.root.as_ptr(), x, y, &mut elem);
            if err != 0 || elem.is_null() {
                return Err(AXError::CopyElementAtPositionErr(err));
            }
            OwnedAXUIElement::from_create_rule(elem).ok_or(AXError::NullElement)
        }
    }

    pub fn get_ax_element_at_position(&self, x: f32, y: f32) -> Result<OwnedAXUIElement, AXError> {
        let elem = self.hit_test(x, y)?;

        if self.ensure_enhanced_ui(&elem) {
            // Chromium-based apps build their tree asynchronously after activation.
            thread::sleep(Duration::from_millis(150));
            if let Ok(deeper) = self.hit_test(x, y) {
                return Ok(deeper);
            }
        }

        Ok(elem)
    }

    pub fn get_ax_snapshot_at_position(&self, x: f32, y: f32) -> Result<AxSnapshot, AXError> {
        let elem = self.get_ax_element_at_position(x, y)?;
        Ok(elem.intent_ax_snapshot(f64::from(x), f64::from(y)))
    }
}
