use accessibility_sys::{
    AXUIElementCopyAttributeNames, AXUIElementCopyAttributeValue, AXUIElementRef, AXValueGetValue,
    AXValueRef, kAXChildrenAttribute, kAXParentAttribute, kAXPositionAttribute, kAXSizeAttribute,
    kAXValueTypeCGPoint, kAXValueTypeCGSize,
};
use core_foundation::{
    array::CFArray,
    base::{CFType, CFTypeRef, TCFType},
    boolean::CFBoolean,
    number::CFNumber,
    string::CFString,
};
use core_foundation_sys::array::CFArrayRef;
use core_foundation_sys::base::{CFRelease, CFRetain};
use crate::accessibility::ax_snapshot::{AxAttributes, AxBoundingBox, AxSnapshot};
use core_graphics::geometry::{CGPoint, CGSize};
use std::mem;
use std::ptr;


/// Owns an Accessibility element pointer and releases it on drop.
pub struct OwnedAXUIElement {
    ptr: AXUIElementRef,
}

impl OwnedAXUIElement {
    const MAX_PARENT_DEPTH: usize = 8;
    const MAX_CHILDREN_SCAN: usize = 64;

    /// Construct from a `Create`/`Copy` API result (already retained, +1).
    pub fn from_create_rule(ptr: AXUIElementRef) -> Option<Self> {
        if ptr.is_null() {
            None
        } else {
            Some(Self { ptr })
        }
    }

    /// Borrow the raw pointer for FFI calls.
    pub fn as_ptr(&self) -> AXUIElementRef {
        self.ptr
    }

    /// Transfer ownership to caller and skip automatic release.
    pub fn into_raw(self) -> AXUIElementRef {
        let ptr = self.ptr;
        mem::forget(self);
        ptr
    }

    fn copy_attr_value(&self, attr_name: &str) -> Result<CFTypeRef, i32> {
        let attr = CFString::new(attr_name);
        let mut value: CFTypeRef = ptr::null_mut();
        
        let err = unsafe { AXUIElementCopyAttributeValue(self.ptr, attr.as_concrete_TypeRef(), &mut value) };
        if err != 0 || value.is_null() {
            Err(err)
        } else {
            Ok(value)
        }
    }
    
    fn copy_attr_as_string(&self, attr_name: &str) -> Result<String, i32> {
        let value = self.copy_attr_value(attr_name)?;
        let cf_value = unsafe { CFType::wrap_under_create_rule(value) };
        if let Some(s) = cf_value.downcast::<CFString>() {
            Ok(s.to_string())
        } else if let Some(n) = cf_value.downcast::<CFNumber>() {
            Ok(n.to_f64().map(|v| v.to_string()).unwrap_or_else(|| "<number>".to_string()))
        } else if let Some(b) = cf_value.downcast::<CFBoolean>() {
            Ok(format!("{}", bool::from(b)))
        } else {
            Ok(format!("{:?}", cf_value))
        }
    }
    
    fn copy_attr<T>(&self, attr_name: &str, ax_value_type: u32, mut out: T) -> Option<T> {
        let value = self.copy_attr_value(attr_name).ok()?;
        let ok = unsafe {
            AXValueGetValue(
                value as AXValueRef,
                ax_value_type,
                (&mut out as *mut T).cast(),
            )
        };
        unsafe { CFRelease(value as *const _) };
        ok.then_some(out)
    }
    
    fn copy_point_attr(&self, attr_name: &str) -> Option<CGPoint> {
        self.copy_attr(attr_name, kAXValueTypeCGPoint, CGPoint::new(0.0, 0.0))
    }
    
    fn copy_size_attr(&self, attr_name: &str) -> Option<CGSize> {
        self.copy_attr(attr_name, kAXValueTypeCGSize, CGSize::new(0.0, 0.0))
    }
    
    fn copy_attribute_names(&self) -> Result<Vec<String>, i32> {
        let mut names = ptr::null();
        let err = unsafe { AXUIElementCopyAttributeNames(self.ptr, &mut names) };
        if err != 0 {
            return Err(err);
        }
        if names.is_null() {
            return Ok(vec![]);
        }
    
        let array: CFArray<CFString> = unsafe { CFArray::wrap_under_create_rule(names) };
        Ok(array.iter().map(|s| s.to_string()).collect())
    }
    
    fn get_parent(&self) -> Result<OwnedAXUIElement, i32> {
        let attr = CFString::new(kAXParentAttribute);
        let mut parent: CFTypeRef = ptr::null_mut();
        let err = unsafe { AXUIElementCopyAttributeValue(self.ptr, attr.as_concrete_TypeRef(), &mut parent) };
        if err != 0 || parent.is_null() {
            Err(err)
        } else {
            OwnedAXUIElement::from_create_rule(parent as AXUIElementRef).ok_or(err)
        }
    }

    /// First `max` children from `AXChildren`. Each child is `CFRetain`d so it outlives the array.
    fn first_children(&self, max: usize) -> Vec<OwnedAXUIElement> {
        let Ok(value) = self.copy_attr_value(kAXChildrenAttribute) else {
            return vec![];
        };
        let array: CFArray =
            unsafe { CFArray::wrap_under_create_rule(value as CFArrayRef) };
        let mut out = Vec::new();
        for ptr in array.get_all_values().into_iter().take(max) {
            if ptr.is_null() {
                continue;
            }
            unsafe {
                let retained = CFRetain(ptr as CFTypeRef) as AXUIElementRef;
                if let Some(child) = OwnedAXUIElement::from_create_rule(retained) {
                    out.push(child);
                }
            }
        }
        out
    }

    /// Children of this element whose bounding box contains `(x, y)`.
    /// If this element is a leaf (no `AXChildren`), falls back to the
    /// immediate parent's children that contain the point.
    fn children_at_point(&self, x: f64, y: f64) -> Vec<OwnedAXUIElement> {
        let mut ch = self.first_children(Self::MAX_CHILDREN_SCAN);
        if ch.is_empty() {
            if let Ok(parent) = self.get_parent() {
                ch = parent.first_children(Self::MAX_CHILDREN_SCAN);
            }
        }
        ch.into_iter()
            .filter(|child| {
                let Some(p) = child.copy_point_attr(kAXPositionAttribute) else { return false };
                let Some(s) = child.copy_size_attr(kAXSizeAttribute) else { return false };
                x >= p.x && x <= p.x + s.width && y >= p.y && y <= p.y + s.height
            })
            .collect()
    }
    
    pub fn print_element_attributes(&self, label: &str) {
        println!("{label}:");
        match self.copy_attribute_names() {
            Ok(attr_names) => {
                println!("  attribute_count: {}", attr_names.len());
                for attr_name in attr_names {
                    match self.copy_attr_as_string(&attr_name) {
                        Ok(value) => println!("  {attr_name}: {value}"),
                        Err(err) => println!("  {attr_name}: <error {err}>"),
                    }
                }
            }
            Err(err) => println!("  failed to enumerate attributes (err={err})"),
        }
    
        let position = self.copy_point_attr(kAXPositionAttribute);
        let size = self.copy_size_attr(kAXSizeAttribute);
        if let (Some(p), Some(s)) = (position, size) {
            println!(
                "  bbox: x={:.0}, y={:.0}, width={:.0}, height={:.0}",
                p.x, p.y, s.width, s.height
            );
        } else {
            println!("  bbox: <unavailable>");
        }
    
        println!();
    }

    /// Read a string attribute, treating empty strings as absent.
    fn copy_nonempty_attr(elem: &OwnedAXUIElement, attr: &str) -> Option<String> {
        elem.copy_attr_as_string(attr)
            .ok()
            .filter(|s| !s.is_empty())
    }

    fn fill_intent_attributes(elem: &OwnedAXUIElement) -> AxAttributes {
        let mut a = AxAttributes::default();

        a.ax_role = Self::copy_nonempty_attr(elem, "AXRole");
        a.ax_subrole = Self::copy_nonempty_attr(elem, "AXSubrole");
        a.ax_role_description = Self::copy_nonempty_attr(elem, "AXRoleDescription");
        a.ax_title = Self::copy_nonempty_attr(elem, "AXTitle");
        a.ax_value = Self::copy_nonempty_attr(elem, "AXValue");
        a.ax_description = Self::copy_nonempty_attr(elem, "AXDescription");
        a.ax_label = Self::copy_nonempty_attr(elem, "AXLabel");
        a.ax_help = Self::copy_nonempty_attr(elem, "AXHelp");
        a.ax_placeholder_value = Self::copy_nonempty_attr(elem, "AXPlaceholderValue");
        a.ax_identifier = Self::copy_nonempty_attr(elem, "AXIdentifier");
        a.ax_dom_identifier = Self::copy_nonempty_attr(elem, "AXDOMIdentifier");
        a.ax_dom_class_list = Self::copy_nonempty_attr(elem, "AXDOMClassList");

        if let (Some(p), Some(s)) = (
            elem.copy_point_attr(kAXPositionAttribute),
            elem.copy_size_attr(kAXSizeAttribute),
        ) {
            a.bounding_box = Some(AxBoundingBox {
                x: f64::from(p.x),
                y: f64::from(p.y),
                width: f64::from(s.width),
                height: f64::from(s.height),
            });
        }

        a
    }

    /// Intent subset (role, identifier, title/value, bbox) for hit target, ancestors, and
    /// children whose bounding box contains `(mouse_x, mouse_y)`.
    pub fn intent_ax_snapshot(&self, mouse_x: f64, mouse_y: f64) -> AxSnapshot {
        let mut current = Self::fill_intent_attributes(self);
        current.selected = Some(true);

        let mut parents = Vec::new();
        let mut depth = 1usize;
        let mut current_parent = self.get_parent().ok();
        while let Some(parent) = current_parent {
            if depth > Self::MAX_PARENT_DEPTH {
                break;
            }
            parents.push(Self::fill_intent_attributes(&parent));
            current_parent = parent.get_parent().ok();
            depth += 1;
        }

        let children = self
            .children_at_point(mouse_x, mouse_y)
            .into_iter()
            .map(|c| Self::fill_intent_attributes(&c))
            .collect();

        AxSnapshot {
            current,
            parents,
            children,
        }
    }
}

impl Drop for OwnedAXUIElement {
    fn drop(&mut self) {
        if !self.ptr.is_null() {
            unsafe { CFRelease(self.ptr as *const _) };
        }
    }
}