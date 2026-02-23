# macOS Accessibility API Reference

A comprehensive guide to building accessibility trees on macOS using the HIServices framework.

## Overview

The macOS Accessibility API allows assistive applications to inspect and interact with UI elements across all running applications. The core type is `AXUIElementRef`, which represents any accessible UI element.

**Header Location:**
```
/Applications/Xcode.app/Contents/Developer/Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk/System/Library/Frameworks/ApplicationServices.framework/Versions/A/Frameworks/HIServices.framework/Versions/A/Headers/
```

**Framework:** `ApplicationServices.framework` (specifically `HIServices.framework`)

**Import (Swift/Objective-C):**
```swift
import ApplicationServices
// or specifically:
import HIServices
```

**Rust crate:** [`accessibility`](https://crates.io/crates/accessibility) or use `core-foundation` + raw FFI

---

## Prerequisites: Accessibility Permissions

Before using any accessibility APIs, your app must have accessibility permissions.

### Check Trust Status

```c
// Check if current process is trusted
Boolean AXIsProcessTrusted(void);

// Check with optional prompt to user
Boolean AXIsProcessTrustedWithOptions(CFDictionaryRef options);

// Key to show system prompt if not trusted
extern CFStringRef kAXTrustedCheckOptionPrompt;
```

**Usage:**
```c
// Check and prompt user if needed
NSDictionary *options = @{(__bridge NSString *)kAXTrustedCheckOptionPrompt: @YES};
Boolean trusted = AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
```

---

## Core Functions for Building an Accessibility Tree

### 1. Entry Points - Getting Root Elements

| Function | Purpose |
|----------|---------|
| `AXUIElementCreateSystemWide()` | System-wide element (focused app, element at position) |
| `AXUIElementCreateApplication(pid_t pid)` | Application root element by PID |

```c
// Get system-wide element for cross-app queries
AXUIElementRef systemWide = AXUIElementCreateSystemWide();

// Get app element by PID
AXUIElementRef app = AXUIElementCreateApplication(12345);
```

### 2. Reading Attributes

| Function | Purpose |
|----------|---------|
| `AXUIElementCopyAttributeNames()` | List all attributes on an element |
| `AXUIElementCopyAttributeValue()` | Get a single attribute value |
| `AXUIElementCopyMultipleAttributeValues()` | Batch-fetch multiple attributes (faster) |
| `AXUIElementGetAttributeValueCount()` | Get count of array attribute |
| `AXUIElementCopyAttributeValues()` | Get slice of array attribute (pagination) |

```c
// Get all attribute names
CFArrayRef names;
AXError err = AXUIElementCopyAttributeNames(element, &names);

// Get single attribute
CFTypeRef value;
AXError err = AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &value);

// Batch fetch (more efficient)
CFArrayRef attributes = CFArrayCreate(..., {kAXRoleAttribute, kAXTitleAttribute, ...});
CFArrayRef values;
AXError err = AXUIElementCopyMultipleAttributeValues(element, attributes, 0, &values);
```

### 3. Tree Traversal Attributes

These attributes are essential for walking the accessibility tree:

| Attribute | Type | Description |
|-----------|------|-------------|
| `kAXParentAttribute` | `AXUIElementRef` | Parent element in hierarchy |
| `kAXChildrenAttribute` | `CFArrayRef` of `AXUIElementRef` | All child elements |
| `kAXVisibleChildrenAttribute` | `CFArrayRef` | Children currently visible |
| `kAXSelectedChildrenAttribute` | `CFArrayRef` | Currently selected children |
| `kAXWindowAttribute` | `AXUIElementRef` | Containing window |
| `kAXTopLevelUIElementAttribute` | `AXUIElementRef` | Top-level container (window/sheet/drawer) |

### 4. Hit Testing

```c
// Find element at screen coordinates (top-left origin)
AXUIElementRef element;
AXError err = AXUIElementCopyElementAtPosition(
    systemWideOrApp, // AXUIElementRef
    x,               // float - horizontal position
    y,               // float - vertical position
    &element         // out: element at position
);
```

### 5. Element Identification

```c
// Get process ID from element
pid_t pid;
AXError err = AXUIElementGetPid(element, &pid);

// Get type ID for CFType operations
CFTypeID typeID = AXUIElementGetTypeID();
```

---

## Essential Attributes for Building a Tree

### Identity Attributes

| Attribute | String | Type | Description |
|-----------|--------|------|-------------|
| `kAXRoleAttribute` | `"AXRole"` | `CFStringRef` | Element type (button, window, etc.) |
| `kAXSubroleAttribute` | `"AXSubrole"` | `CFStringRef` | More specific type |
| `kAXRoleDescriptionAttribute` | `"AXRoleDescription"` | `CFStringRef` | Localized role description |
| `kAXIdentifierAttribute` | `"AXIdentifier"` | `CFStringRef` | Developer-assigned identifier |
| `kAXTitleAttribute` | `"AXTitle"` | `CFStringRef` | Display title/label |
| `kAXDescriptionAttribute` | `"AXDescription"` | `CFStringRef` | Accessibility description |
| `kAXHelpAttribute` | `"AXHelp"` | `CFStringRef` | Help text (tooltip) |

### Geometry Attributes

| Attribute | String | Type | Description |
|-----------|--------|------|-------------|
| `kAXPositionAttribute` | `"AXPosition"` | `AXValueRef` (CGPoint) | Top-left screen position |
| `kAXSizeAttribute` | `"AXSize"` | `AXValueRef` (CGSize) | Width and height |

### State Attributes

| Attribute | String | Type | Description |
|-----------|--------|------|-------------|
| `kAXEnabledAttribute` | `"AXEnabled"` | `CFBooleanRef` | Whether element is enabled |
| `kAXFocusedAttribute` | `"AXFocused"` | `CFBooleanRef` | Has keyboard focus |
| `kAXValueAttribute` | `"AXValue"` | Varies | Current value (text, number, etc.) |
| `kAXSelectedAttribute` | `"AXSelected"` | `CFBooleanRef` | Is selected |
| `kAXExpandedAttribute` | `"AXExpanded"` | `CFBooleanRef` | Is expanded (disclosure) |

### Application-Level Attributes

| Attribute | String | Description |
|-----------|--------|-------------|
| `kAXWindowsAttribute` | `"AXWindows"` | Array of all windows |
| `kAXMainWindowAttribute` | `"AXMainWindow"` | The main document window |
| `kAXFocusedWindowAttribute` | `"AXFocusedWindow"` | Currently focused window |
| `kAXFocusedUIElementAttribute` | `"AXFocusedUIElement"` | Currently focused element |
| `kAXMenuBarAttribute` | `"AXMenuBar"` | Application menu bar |
| `kAXFrontmostAttribute` | `"AXFrontmost"` | Is frontmost app |
| `kAXHiddenAttribute` | `"AXHidden"` | Is app hidden |

---

## Working with AXValue (Geometry Types)

CGPoint, CGSize, and CGRect are wrapped in `AXValueRef`:

```c
// Creating AXValue from CGPoint
CGPoint point = {100.0, 200.0};
AXValueRef value = AXValueCreate(kAXValueTypeCGPoint, &point);

// Extracting CGPoint from AXValue
CGPoint extractedPoint;
Boolean success = AXValueGetValue(value, kAXValueTypeCGPoint, &extractedPoint);

// Get type of AXValue
AXValueType type = AXValueGetType(value);
```

| AXValueType | Wrapped Type |
|-------------|--------------|
| `kAXValueTypeCGPoint` | `CGPoint` |
| `kAXValueTypeCGSize` | `CGSize` |
| `kAXValueTypeCGRect` | `CGRect` |
| `kAXValueTypeCFRange` | `CFRange` |
| `kAXValueTypeAXError` | `AXError` |

---

## Standard Roles

### Window & Container Roles

| Role Constant | String Value | Description |
|---------------|--------------|-------------|
| `kAXApplicationRole` | `"AXApplication"` | Application root |
| `kAXSystemWideRole` | `"AXSystemWide"` | System-wide element |
| `kAXWindowRole` | `"AXWindow"` | Standard window |
| `kAXSheetRole` | `"AXSheet"` | Modal sheet |
| `kAXDrawerRole` | `"AXDrawer"` | Drawer panel |
| `kAXGroupRole` | `"AXGroup"` | Generic container |
| `kAXScrollAreaRole` | `"AXScrollArea"` | Scrollable area |
| `kAXPopoverRole` | `"AXPopover"` | Popover |

### Interactive Elements

| Role Constant | String Value | Description |
|---------------|--------------|-------------|
| `kAXButtonRole` | `"AXButton"` | Push button |
| `kAXRadioButtonRole` | `"AXRadioButton"` | Radio button |
| `kAXCheckBoxRole` | `"AXCheckBox"` | Checkbox |
| `kAXPopUpButtonRole` | `"AXPopUpButton"` | Popup/dropdown button |
| `kAXMenuButtonRole` | `"AXMenuButton"` | Menu button |
| `kAXSliderRole` | `"AXSlider"` | Slider |
| `kAXIncrementorRole` | `"AXIncrementor"` | Stepper/incrementor |
| `kAXComboBoxRole` | `"AXComboBox"` | Combo box |
| `kAXDisclosureTriangleRole` | `"AXDisclosureTriangle"` | Disclosure triangle |
| `kAXColorWellRole` | `"AXColorWell"` | Color picker well |

### Text Elements

| Role Constant | String Value | Description |
|---------------|--------------|-------------|
| `kAXTextFieldRole` | `"AXTextField"` | Single-line text field |
| `kAXTextAreaRole` | `"AXTextArea"` | Multi-line text area |
| `kAXStaticTextRole` | `"AXStaticText"` | Non-editable text label |
| `kAXHeadingRole` | `"AXHeading"` | Heading text |

### Table/List Elements

| Role Constant | String Value | Description |
|---------------|--------------|-------------|
| `kAXTableRole` | `"AXTable"` | Table |
| `kAXOutlineRole` | `"AXOutline"` | Outline/tree view |
| `kAXBrowserRole` | `"AXBrowser"` | Column browser |
| `kAXListRole` | `"AXList"` | List |
| `kAXRowRole` | `"AXRow"` | Table/outline row |
| `kAXColumnRole` | `"AXColumn"` | Table column |
| `kAXCellRole` | `"AXCell"` | Table cell |
| `kAXGridRole` | `"AXGrid"` | Grid |

### Menu Elements

| Role Constant | String Value | Description |
|---------------|--------------|-------------|
| `kAXMenuBarRole` | `"AXMenuBar"` | Menu bar |
| `kAXMenuBarItemRole` | `"AXMenuBarItem"` | Menu bar item |
| `kAXMenuRole` | `"AXMenu"` | Menu |
| `kAXMenuItemRole` | `"AXMenuItem"` | Menu item |

### Other Elements

| Role Constant | String Value | Description |
|---------------|--------------|-------------|
| `kAXScrollBarRole` | `"AXScrollBar"` | Scroll bar |
| `kAXToolbarRole` | `"AXToolbar"` | Toolbar |
| `kAXTabGroupRole` | `"AXTabGroup"` | Tab group |
| `kAXSplitGroupRole` | `"AXSplitGroup"` | Split view |
| `kAXSplitterRole` | `"AXSplitter"` | Split view divider |
| `kAXImageRole` | `"AXImage"` | Image |
| `kAXProgressIndicatorRole` | `"AXProgressIndicator"` | Progress bar |
| `kAXBusyIndicatorRole` | `"AXBusyIndicator"` | Busy/loading indicator |
| `kAXValueIndicatorRole` | `"AXValueIndicator"` | Value indicator (thumb) |
| `kAXGrowAreaRole` | `"AXGrowArea"` | Window resize handle |
| `kAXUnknownRole` | `"AXUnknown"` | Unknown/unspecified |

---

## Common Subroles

| Subrole Constant | String Value | Description |
|------------------|--------------|-------------|
| `kAXCloseButtonSubrole` | `"AXCloseButton"` | Window close button |
| `kAXMinimizeButtonSubrole` | `"AXMinimizeButton"` | Window minimize button |
| `kAXZoomButtonSubrole` | `"AXZoomButton"` | Window zoom button |
| `kAXFullScreenButtonSubrole` | `"AXFullScreenButton"` | Full screen button |
| `kAXToolbarButtonSubrole` | `"AXToolbarButton"` | Toolbar toggle button |
| `kAXSecureTextFieldSubrole` | `"AXSecureTextField"` | Password field |
| `kAXSearchFieldSubrole` | `"AXSearchField"` | Search field |
| `kAXStandardWindowSubrole` | `"AXStandardWindow"` | Standard window |
| `kAXDialogSubrole` | `"AXDialog"` | Dialog window |
| `kAXFloatingWindowSubrole` | `"AXFloatingWindow"` | Floating panel |
| `kAXTableRowSubrole` | `"AXTableRow"` | Table row |
| `kAXOutlineRowSubrole` | `"AXOutlineRow"` | Outline row |
| `kAXToggleSubrole` | `"AXToggle"` | Toggle button |
| `kAXSwitchSubrole` | `"AXSwitch"` | Switch control |

---

## Actions

### Querying Actions

```c
// Get available actions
CFArrayRef actions;
AXError err = AXUIElementCopyActionNames(element, &actions);

// Get localized description
CFStringRef description;
AXError err = AXUIElementCopyActionDescription(element, kAXPressAction, &description);
```

### Performing Actions

```c
AXError err = AXUIElementPerformAction(element, kAXPressAction);
```

### Standard Actions

| Action Constant | String Value | Description |
|-----------------|--------------|-------------|
| `kAXPressAction` | `"AXPress"` | Click/activate |
| `kAXIncrementAction` | `"AXIncrement"` | Increment value |
| `kAXDecrementAction` | `"AXDecrement"` | Decrement value |
| `kAXConfirmAction` | `"AXConfirm"` | Confirm (like pressing Return) |
| `kAXCancelAction` | `"AXCancel"` | Cancel |
| `kAXRaiseAction` | `"AXRaise"` | Bring to front |
| `kAXShowMenuAction` | `"AXShowMenu"` | Show context menu |
| `kAXPickAction` | `"AXPick"` | Select (menu items) |
| `kAXShowAlternateUIAction` | `"AXShowAlternateUI"` | Show alternate UI (hover) |
| `kAXShowDefaultUIAction` | `"AXShowDefaultUI"` | Show default UI |

---

## Observing Changes (Notifications)

### Creating an Observer

```c
// Callback signature
void myCallback(
    AXObserverRef observer,
    AXUIElementRef element,
    CFStringRef notification,
    void *refcon
);

// Create observer
AXObserverRef observer;
AXError err = AXObserverCreate(pid, myCallback, &observer);

// Add to run loop
CFRunLoopAddSource(
    CFRunLoopGetCurrent(),
    AXObserverGetRunLoopSource(observer),
    kCFRunLoopDefaultMode
);

// Register for notification
AXError err = AXObserverAddNotification(
    observer,
    element,          // element to observe (use app for all)
    kAXFocusedUIElementChangedNotification,
    myContext         // refcon passed to callback
);

// Unregister
AXObserverRemoveNotification(observer, element, notification);
```

### Key Notifications for Tree Changes

| Notification | Description |
|--------------|-------------|
| `kAXUIElementDestroyedNotification` | Element was destroyed |
| `kAXCreatedNotification` | Element was created |
| `kAXWindowCreatedNotification` | Window was created |
| `kAXFocusedUIElementChangedNotification` | Focus changed |
| `kAXFocusedWindowChangedNotification` | Focused window changed |
| `kAXValueChangedNotification` | Value attribute changed |
| `kAXSelectedChildrenChangedNotification` | Selection changed |
| `kAXLayoutChangedNotification` | Layout changed |
| `kAXTitleChangedNotification` | Title changed |
| `kAXWindowMovedNotification` | Window moved |
| `kAXWindowResizedNotification` | Window resized |
| `kAXApplicationActivatedNotification` | App activated |
| `kAXApplicationDeactivatedNotification` | App deactivated |
| `kAXMenuOpenedNotification` | Menu opened |
| `kAXMenuClosedNotification` | Menu closed |
| `kAXRowExpandedNotification` | Outline row expanded |
| `kAXRowCollapsedNotification` | Outline row collapsed |

---

## Error Handling

```c
typedef enum {
    kAXErrorSuccess                        = 0,
    kAXErrorFailure                        = -25200,  // System failure
    kAXErrorIllegalArgument                = -25201,  // Bad argument
    kAXErrorInvalidUIElement               = -25202,  // Element invalid
    kAXErrorInvalidUIElementObserver       = -25203,  // Observer invalid
    kAXErrorCannotComplete                 = -25204,  // Messaging failed
    kAXErrorAttributeUnsupported           = -25205,  // Attribute not supported
    kAXErrorActionUnsupported              = -25206,  // Action not supported
    kAXErrorNotificationUnsupported        = -25207,  // Notification not supported
    kAXErrorNotImplemented                 = -25208,  // Not implemented
    kAXErrorNotificationAlreadyRegistered  = -25209,  // Already registered
    kAXErrorNotificationNotRegistered      = -25210,  // Not registered
    kAXErrorAPIDisabled                    = -25211,  // Accessibility disabled
    kAXErrorNoValue                        = -25212,  // No value exists
    kAXErrorParameterizedAttributeUnsupported = -25213,
    kAXErrorNotEnoughPrecision             = -25214,
} AXError;
```

---

## Configuration

### Setting Messaging Timeout

```c
// Set timeout for specific element (0 = use global)
AXError err = AXUIElementSetMessagingTimeout(element, 5.0); // 5 seconds

// Set global timeout
AXUIElementRef systemWide = AXUIElementCreateSystemWide();
AXUIElementSetMessagingTimeout(systemWide, 10.0); // 10 seconds
// Reset to default
AXUIElementSetMessagingTimeout(systemWide, 0);
```

---

## Practical Patterns

### Walking the Full Tree (Recursive)

```c
void walkTree(AXUIElementRef element, int depth) {
    // Get role
    CFTypeRef roleValue;
    if (AXUIElementCopyAttributeValue(element, kAXRoleAttribute, &roleValue) == kAXErrorSuccess) {
        // Process element...
        CFRelease(roleValue);
    }

    // Get children
    CFTypeRef childrenValue;
    if (AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, &childrenValue) == kAXErrorSuccess) {
        CFArrayRef children = (CFArrayRef)childrenValue;
        CFIndex count = CFArrayGetCount(children);

        for (CFIndex i = 0; i < count; i++) {
            AXUIElementRef child = (AXUIElementRef)CFArrayGetValueAtIndex(children, i);
            walkTree(child, depth + 1);
        }
        CFRelease(childrenValue);
    }
}
```

### Efficient Attribute Fetching

```c
// Batch fetch common attributes
CFStringRef attrNames[] = {
    kAXRoleAttribute,
    kAXTitleAttribute,
    kAXPositionAttribute,
    kAXSizeAttribute,
    kAXEnabledAttribute
};
CFArrayRef attributes = CFArrayCreate(NULL, (const void **)attrNames, 5, &kCFTypeArrayCallBacks);

CFArrayRef values;
AXError err = AXUIElementCopyMultipleAttributeValues(element, attributes, 0, &values);

// values[i] corresponds to attrNames[i]
// May contain kCFNull or AXValueRef with kAXValueTypeAXError on failure
```

### Finding Element by Identifier

```c
AXUIElementRef findByIdentifier(AXUIElementRef root, CFStringRef targetId) {
    CFTypeRef idValue;
    if (AXUIElementCopyAttributeValue(root, kAXIdentifierAttribute, &idValue) == kAXErrorSuccess) {
        if (CFEqual(idValue, targetId)) {
            CFRelease(idValue);
            CFRetain(root);
            return root;
        }
        CFRelease(idValue);
    }

    CFTypeRef children;
    if (AXUIElementCopyAttributeValue(root, kAXChildrenAttribute, &children) == kAXErrorSuccess) {
        CFIndex count = CFArrayGetCount((CFArrayRef)children);
        for (CFIndex i = 0; i < count; i++) {
            AXUIElementRef child = (AXUIElementRef)CFArrayGetValueAtIndex((CFArrayRef)children, i);
            AXUIElementRef found = findByIdentifier(child, targetId);
            if (found) {
                CFRelease(children);
                return found;
            }
        }
        CFRelease(children);
    }
    return NULL;
}
```

---

## Memory Management

- All `AXUIElementRef`, `AXValueRef`, and returned `CFTypeRef` values are owned by the caller
- Use `CFRetain()` / `CFRelease()` appropriately
- Arrays returned from copy functions must be released
- Elements inside arrays do NOT need individual release (array owns them)

```c
CFArrayRef children;
AXUIElementCopyAttributeValue(element, kAXChildrenAttribute, (CFTypeRef *)&children);
// ... use children ...
CFRelease(children); // releases array AND its contents
```

---

## References

- **Headers:** `/Applications/Xcode.app/.../HIServices.framework/Headers/`
  - `AXUIElement.h` - Core API
  - `AXValue.h` - Geometry wrappers
  - `AXError.h` - Error codes
  - `AXAttributeConstants.h` - Attribute names
  - `AXRoleConstants.h` - Role/subrole names
  - `AXActionConstants.h` - Action names
  - `AXNotificationConstants.h` - Notification names
- **Apple Docs:** [Accessibility Programming Guide](https://developer.apple.com/library/archive/documentation/Accessibility/Conceptual/AccessibilityMacOSX/)
