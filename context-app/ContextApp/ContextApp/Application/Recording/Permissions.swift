import AppKit
import ApplicationServices
import CoreGraphics

/// Aggregate permission state required to begin a recording.
///
/// - `screen`: screen capture (`SCStream` via `CGPreflightScreenCaptureAccess`).
/// - `accessibility`: required for `CGEvent.tapCreate`. We do NOT use the AX
///   tree itself; only the tap permission piggybacks on this flag.
struct RecordingPermissions: Equatable {
    let screen: Bool
    let accessibility: Bool

    var allGranted: Bool { screen && accessibility }
    var needsScreen: Bool { !screen }
    var needsAccessibility: Bool { !accessibility }
    var needsBoth: Bool { needsScreen && needsAccessibility }
}

enum RecordingPermissionsProbe {
    /// Read-only check. Safe to call from any thread.
    static func current() -> RecordingPermissions {
        RecordingPermissions(
            screen: CGPreflightScreenCaptureAccess(),
            accessibility: AXIsProcessTrusted()
        )
    }

    /// Triggers the system prompts for any missing permissions.
    /// Returns the post-prompt state, but note that grants typically require
    /// the user to enable the toggle in System Settings and relaunch.
    @discardableResult
    static func request() -> RecordingPermissions {
        if !CGPreflightScreenCaptureAccess() {
            _ = CGRequestScreenCaptureAccess()
        }
        if !AXIsProcessTrusted() {
            let key = "AXTrustedCheckOptionPrompt" as CFString
            let opts = [key: kCFBooleanTrue!] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(opts)
        }
        return current()
    }
}
