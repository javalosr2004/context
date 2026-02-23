use accessibility::AXUIElementRef;
use accessibility::{
    AXUIElementCopyAttributeNames, AXUIElementCopyAttributeValue, AXValueGetValue, AXValueRef,
    kAXParentAttribute, kAXPositionAttribute, kAXSizeAttribute, kAXValueTypeCGPoint,
    kAXValueTypeCGSize,
};
use core_foundation::{
    array::CFArray,
    base::{CFType, CFTypeRef, TCFType},
    boolean::CFBoolean,
    number::CFNumber,
    string::CFString,
};
use core_foundation_sys::base::CFRelease;
use core_graphics::geometry::{CGPoint, CGSize};
use std::collections::BTreeMap;
use std::mem;
use std::ptr;


/// Owns an Accessibility element pointer and releases it on drop.
pub struct OwnedAXUIElement {
    ptr: AXUIElementRef,
}

impl OwnedAXUIElement {
    const MAX_PARENT_DEPTH: usize = 8;

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

    fn write_snapshot_with_prefix(
        elem: &OwnedAXUIElement,
        prefix: &str,
        attrs: &mut BTreeMap<String, String>,
    ) -> Result<(), i32> {
        for attr_name in elem.copy_attribute_names()? {
            if let Ok(value) = elem.copy_attr_as_string(&attr_name) {
                attrs.insert(format!("{prefix}{attr_name}"), value);
            }
        }

        if let (Some(p), Some(s)) = (
            elem.copy_point_attr(kAXPositionAttribute),
            elem.copy_size_attr(kAXSizeAttribute),
        ) {
            attrs.insert(format!("{prefix}bbox_x"), format!("{:.0}", p.x));
            attrs.insert(format!("{prefix}bbox_y"), format!("{:.0}", p.y));
            attrs.insert(format!("{prefix}bbox_width"), format!("{:.0}", s.width));
            attrs.insert(format!("{prefix}bbox_height"), format!("{:.0}", s.height));
        }

        Ok(())
    }

    fn write_intent_snapshot_with_prefix(
        elem: &OwnedAXUIElement,
        prefix: &str,
        attrs: &mut BTreeMap<String, String>,
    ) {
        if let Ok(role) = elem.copy_attr_as_string("AXRole") {
            attrs.insert(format!("{prefix}AXRole"), role);
        }

        if let Ok(identifier) = elem.copy_attr_as_string("AXIdentifier") {
            attrs.insert(format!("{prefix}AXIdentifier"), identifier);
        }

        if let Ok(class_list) = elem.copy_attr_as_string("AXDOMClassList") {
            attrs.insert(format!("{prefix}AXDOMClassList"), class_list);
        }

        let title_or_value = elem
            .copy_attr_as_string("AXTitle")
            .ok()
            .or_else(|| elem.copy_attr_as_string("AXValue").ok());
        if let Some(text) = title_or_value {
            attrs.insert(format!("{prefix}AXTitleOrValue"), text);
        }

        if let (Some(p), Some(s)) = (
            elem.copy_point_attr(kAXPositionAttribute),
            elem.copy_size_attr(kAXSizeAttribute),
        ) {
            attrs.insert(format!("{prefix}bbox_x"), format!("{:.0}", p.x));
            attrs.insert(format!("{prefix}bbox_y"), format!("{:.0}", p.y));
            attrs.insert(format!("{prefix}bbox_width"), format!("{:.0}", s.width));
            attrs.insert(format!("{prefix}bbox_height"), format!("{:.0}", s.height));
        }
    }

    pub fn attribute_snapshot(&self) -> Result<BTreeMap<String, String>, i32> {
        let mut attrs = BTreeMap::new();
        Self::write_snapshot_with_prefix(self, "", &mut attrs)?;

        let mut depth = 1usize;
        let mut current_parent = self.get_parent().ok();
        while let Some(parent) = current_parent {
            if depth > Self::MAX_PARENT_DEPTH {
                break;
            }

            let prefix = format!("parent_{depth}_");
            let _ = Self::write_snapshot_with_prefix(&parent, &prefix, &mut attrs);
            current_parent = parent.get_parent().ok();
            depth += 1;
        }

        Ok(attrs)
    }

    pub fn intent_attribute_snapshot(&self) -> BTreeMap<String, String> {
        let mut attrs = BTreeMap::new();
        Self::write_intent_snapshot_with_prefix(self, "", &mut attrs);

        let mut depth = 1usize;
        let mut current_parent = self.get_parent().ok();
        while let Some(parent) = current_parent {
            if depth > Self::MAX_PARENT_DEPTH {
                break;
            }

            let prefix = format!("parent_{depth}_");
            Self::write_intent_snapshot_with_prefix(&parent, &prefix, &mut attrs);
            current_parent = parent.get_parent().ok();
            depth += 1;
        }

        attrs
    }
    
    pub fn print_parent_hierarchy(&self) {
        let mut depth = 0usize;
        let mut current_owner: Option<OwnedAXUIElement> = self.get_parent().ok();
    
        loop {
            let Some(parent) = current_owner else {
                break;
            };
    
            depth += 1;
            parent.print_element_attributes(&format!("Parent[{depth}]"));
    
            current_owner = parent.get_parent().ok();
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