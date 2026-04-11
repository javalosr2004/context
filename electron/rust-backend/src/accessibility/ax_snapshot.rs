//! First-class accessibility snapshots for the hit target, ancestor chain, and direct children.
//! Serialized as JSON `axAttributes: { current, parents, children }`.

use serde::{Deserialize, Serialize};
use ts_rs::TS;

/// Bounding box for an accessibility element (screen coordinates).
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export, export_to = "rust_types.ts")]
pub struct AxBoundingBox {
    pub x: f64,
    pub y: f64,
    pub width: f64,
    pub height: f64,
}

/// Intent subset: role, sub-role, descriptions, title, value, DOM metadata, and geometry.
#[derive(Debug, Clone, Default, Serialize, Deserialize, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export, export_to = "rust_types.ts")]
pub struct AxAttributes {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_role: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_subrole: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_role_description: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_title: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_value: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_description: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_label: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_help: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_placeholder_value: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_identifier: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_dom_identifier: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ax_dom_class_list: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub bounding_box: Option<AxBoundingBox>,
    /// Whether this node is the user-confirmed target for the event.
    /// Defaults to `true` for the hit target (`current`) at capture time.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub selected: Option<bool>,
}

/// Snapshot at the hit-tested element: `current`, ancestors (immediate parent first, then up),
/// and up to two **child** snapshots.
///
/// `children` are normally the hit element’s `AXChildren`. If the hit target is a leaf with no
/// children (typical for `AXStaticText`, buttons, etc.), we use the first two children of the
/// **immediate parent** instead so the array is often useful for context.
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export, export_to = "rust_types.ts")]
pub struct AxSnapshot {
    pub current: AxAttributes,
    pub parents: Vec<AxAttributes>,
    pub children: Vec<AxAttributes>,
}
