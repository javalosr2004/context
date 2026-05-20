import AppKit
import Foundation

enum GoalEntryError: LocalizedError {
    case cancelled
    case tooShort
    case tooLong

    var errorDescription: String? {
        switch self {
        case .cancelled: return "Goal entry was cancelled."
        case .tooShort: return "Goal must be at least 8 characters."
        case .tooLong: return "Goal must be at most 280 characters."
        }
    }
}

enum GoalValidator {
    static let minLength = 8
    static let maxLength = 280

    static func validate(_ raw: String) -> Result<String, GoalEntryError> {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.count < minLength { return .failure(.tooShort) }
        if trimmed.count > maxLength { return .failure(.tooLong) }
        return .success(trimmed)
    }
}

/// Presents an `NSAlert`-based goal entry. We use `NSAlert` instead of a real
/// sheet because the app is menu-bar-only and may not have a key window when
/// the user invokes "Record...".
@MainActor
final class GoalSheetController {
    func prompt() async throws -> Goal {
        let textField = NSTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 60))
        textField.placeholderString = "Reply to Sarah about the Q3 hiring numbers"
        textField.cell?.usesSingleLineMode = false
        textField.cell?.wraps = true

        let alert = NSAlert()
        alert.messageText = "What workflow are you about to demonstrate?"
        alert.informativeText = "State the goal in one sentence. This is shown to the describer so each click can be disambiguated."
        alert.accessoryView = textField
        alert.addButton(withTitle: "Start Recording")
        alert.addButton(withTitle: "Cancel")
        alert.window.initialFirstResponder = textField

        NSApp.activate(ignoringOtherApps: true)

        while true {
            let response = alert.runModal()
            guard response == .alertFirstButtonReturn else { throw GoalEntryError.cancelled }
            switch GoalValidator.validate(textField.stringValue) {
            case .success(let text):
                return Goal(text: text, enteredAtMs: MonotonicClock.wallClockMs())
            case .failure(let err):
                alert.informativeText = err.errorDescription ?? "Invalid goal."
            }
        }
    }
}
