use crate::accessibility::element::OwnedAXUIElement;
use accessibility::{
    AXIsProcessTrustedWithOptions, AXUIElementCopyElementAtPosition, AXUIElementCreateSystemWide,
    AXUIElementRef, kAXTrustedCheckOptionPrompt,
};
use core_foundation::{
    base::TCFType,
    boolean::CFBoolean,
    dictionary::CFDictionary,
    string::CFString,
};
use std::collections::BTreeMap;
use std::ptr;

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
}

impl AccessibilityTree {
    pub fn new() -> Result<Self, AXError> {
        let key = unsafe { CFString::wrap_under_get_rule(kAXTrustedCheckOptionPrompt) };
        let value = CFBoolean::true_value();

        let options = CFDictionary::from_CFType_pairs(&[(key, value)]);

        let trusted = unsafe { AXIsProcessTrustedWithOptions(options.as_concrete_TypeRef()) };

        if !trusted {
            return Err(AXError::PermissionDenied);
        }

        let root = unsafe { AXUIElementCreateSystemWide() };
        let root = OwnedAXUIElement::from_create_rule(root).ok_or(AXError::NullSystemWideElement)?;

        Ok(Self { root })
    }

    pub fn get_ax_element_at_position(&self, x: f32, y: f32) -> Result<OwnedAXUIElement, AXError> {
        unsafe {
            let mut elem: AXUIElementRef = ptr::null_mut();
            let err = AXUIElementCopyElementAtPosition(self.root.as_ptr(), x, y, &mut elem);
            if err != 0 || elem.is_null() {
                return Err(AXError::CopyElementAtPositionErr(err));
            }

            let Some(elem) = OwnedAXUIElement::from_create_rule(elem) else {
                return Err(AXError::NullElement);
            };
            Ok(elem)
        }
    }

    pub fn get_ax_attributes_at_position(
        &self,
        x: f32,
        y: f32,
    ) -> Result<BTreeMap<String, String>, AXError> {
        let elem = self.get_ax_element_at_position(x, y)?;
        Ok(elem.intent_attribute_snapshot())
    }
}
