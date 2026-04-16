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
}

/// User-authored bounding box. Created by the annotator UI when no AX node cleanly describes
/// the target region (canvas, broken ARIA, etc.). Selection is tracked on `AxSnapshot::selected`,
/// not here — this struct only carries the geometry.
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export, export_to = "rust_types.ts")]
pub struct UserOverride {
    pub bounding_box: AxBoundingBox,
}

fn default_selected() -> String {
    "current".to_string()
}

/// Snapshot at the hit-tested element: `current`, ancestors (immediate parent first, then up),
/// and up to two **child** snapshots.
///
/// `children` are normally the hit element’s `AXChildren`. If the hit target is a leaf with no
/// children (typical for `AXStaticText`, buttons, etc.), we use the first two children of the
/// **immediate parent** instead so the array is often useful for context.
///
/// User-authored fields (`user_override`, `title`, `description`, non-default `selected`) are
/// populated later by the annotator UI. They are distinct from AX data: the capture pipeline
/// writes them with defaults, and loaders must tolerate older `.ctx` files that omit them.
#[derive(Debug, Clone, Serialize, Deserialize, TS)]
#[serde(rename_all = "camelCase")]
#[ts(export, export_to = "rust_types.ts")]
pub struct AxSnapshot {
    pub current: AxAttributes,
    pub parents: Vec<AxAttributes>,
    pub children: Vec<AxAttributes>,
    /// Optional user-drawn rectangle. Remains in the snapshot as a selectable option even
    /// after the user picks a different node.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub user_override: Option<UserOverride>,
    /// Single source of truth for which node is the annotation target. Valid values:
    /// `"current"`, `"user_override"`, `"parents:<index>"`, `"children:<index>"`.
    /// Defaults to `"current"` at capture time and for legacy `.ctx` files lacking the field.
    #[serde(default = "default_selected")]
    pub selected: String,
    /// Event-level title authored by the user (e.g. "Click the Save button").
    /// Not tied to any single AX node — describes the event as a whole.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    /// Event-level description shown in the tutorial overlay beneath the title.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}
