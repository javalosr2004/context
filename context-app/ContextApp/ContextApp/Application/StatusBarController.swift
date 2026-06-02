import AppKit
import Combine

@MainActor
final class StatusBarController {
    private static let evalModeDefaultsKey = "eval_mode_enabled"
    static let groundingAutoFireDefaultsKey = "gui_fire_auto"

    /// Whether the grounding agent should fire automatically when the
    /// backend signals a new step. When off, grounding only runs after the
    /// user explicitly presses a step in the overlay.
    ///
    /// Defaults to **on**: this is a primarily LLM-driven plan→action loop, so
    /// the overlay should advance itself unless the user has explicitly turned
    /// auto-fire off. A missing key means "never toggled" → on.
    nonisolated static func isGroundingAutoFireEnabled(defaults: UserDefaults = .standard) -> Bool {
        guard defaults.object(forKey: groundingAutoFireDefaultsKey) != nil else { return true }
        return defaults.bool(forKey: groundingAutoFireDefaultsKey)
    }

    private let endpointStore: GroundingEndpointStore
    private let onShowOverlay: () -> Void
    private let onTestBbox: () -> Void
    private let statusItem: NSStatusItem
    private let tutorialEndpointStore: TutorialAPIEndpointStore
    private let recordingController: RecordingController
    private lazy var recordingsWindow = RecordingsWindowController(controller: recordingController)
    private var recordingCancellable: AnyCancellable?

    init(
        endpointStore: GroundingEndpointStore,
        tutorialEndpointStore: TutorialAPIEndpointStore,
        recordingController: RecordingController,
        onShowOverlay: @escaping () -> Void,
        onTestBbox: @escaping () -> Void
    ) {
        self.endpointStore = endpointStore
        self.onShowOverlay = onShowOverlay
        self.onTestBbox = onTestBbox
        self.tutorialEndpointStore = tutorialEndpointStore
        self.recordingController = recordingController
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        configureStatusItem()
        recordingCancellable = recordingController.$isRecording
            .receive(on: DispatchQueue.main)
            .sink { [weak self] _ in self?.rebuildMenu() }
    }

    func stop() {
        NSStatusBar.system.removeStatusItem(statusItem)
    }

    private func configureStatusItem() {
        if let button = statusItem.button {
            button.image = NSImage(systemSymbolName: "scope", accessibilityDescription: "Context debug")
            button.imagePosition = .imageOnly
        }

        rebuildMenu()
    }

    private func rebuildMenu() {
        let menu = NSMenu()
        menu.addItem(CallbackMenuItem(title: "Show Overlay", actionHandler: { [weak self] in
            self?.showOverlay()
        }))
        menu.addItem(NSMenuItem.separator())
        let recordTitle = recordingController.isRecording ? "Stop Recording" : "Record..."
        menu.addItem(CallbackMenuItem(title: recordTitle, actionHandler: { [weak self] in
            self?.recordingController.toggleRecording()
        }))
        menu.addItem(CallbackMenuItem(title: "Show Recordings...", actionHandler: { [weak self] in
            self?.recordingsWindow.show()
        }))
        menu.addItem(NSMenuItem.separator())
        let endpointItem = NSMenuItem(title: endpointTitle(), action: nil, keyEquivalent: "")
        endpointItem.isEnabled = false
        menu.addItem(endpointItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(CallbackMenuItem(title: "Set grounding endpoint...", actionHandler: { [weak self] in
            self?.showEndpointPrompt()
        }))
        menu.addItem(CallbackMenuItem(title: "Clear saved endpoint", actionHandler: { [weak self] in
            self?.clearSavedEndpoint()
        }))
        menu.addItem(NSMenuItem.separator())
        let tutorialEndpointItem = NSMenuItem(title: tutorialEndpointTitle(), action: nil, keyEquivalent: "")
        tutorialEndpointItem.isEnabled = false
        menu.addItem(tutorialEndpointItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(CallbackMenuItem(title: "Set tutorial API base URL...", actionHandler: { [weak self] in
            self?.showTutorialEndpointPrompt()
        }))
        menu.addItem(CallbackMenuItem(title: "Clear saved tutorial API URL", actionHandler: { [weak self] in
            self?.clearSavedTutorialEndpoint()
        }))
        menu.addItem(NSMenuItem.separator())
        menu.addItem(CallbackMenuItem(title: "Test green bbox", actionHandler: onTestBbox))
        menu.addItem(NSMenuItem.separator())
        let evalItem = CallbackMenuItem(
            title: "Eval Mode: \(isEvalModeEnabled() ? "On" : "Off")",
            actionHandler: { [weak self] in self?.toggleEvalMode() }
        )
        evalItem.toolTip = "When on, the overlay shows ✓/✗ buttons next to each step so you can label runs for eval extraction."
        evalItem.state = isEvalModeEnabled() ? .on : .off
        menu.addItem(evalItem)
        let autoFire = StatusBarController.isGroundingAutoFireEnabled()
        let groundingAutoFireItem = CallbackMenuItem(
            title: "Auto-fire Grounding: \(autoFire ? "On" : "Off")",
            actionHandler: { [weak self] in self?.toggleGroundingAutoFire() }
        )
        groundingAutoFireItem.toolTip = "When off, the grounding agent only runs after you press a step in the overlay. When on, it fires automatically on every step_ready."
        groundingAutoFireItem.state = autoFire ? .on : .off
        menu.addItem(groundingAutoFireItem)
        menu.addItem(NSMenuItem.separator())
        menu.addItem(CallbackMenuItem(title: "Quit Context", actionHandler: quitApplication))
        statusItem.menu = menu
    }

    private func endpointTitle() -> String {
        guard let endpoint = endpointStore.endpoint else {
            return "Grounding endpoint: Not set"
        }

        return "Grounding endpoint: \(endpoint)"
    }

    private func tutorialEndpointTitle() -> String {
        guard let baseURL = tutorialEndpointStore.baseURL else {
            return "Tutorial API: Not set"
        }

        return "Tutorial API: \(baseURL)"
    }

    private func showEndpointPrompt() {
        let textField = NSTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 24))
        textField.stringValue = endpointStore.endpoint ?? ""
        textField.placeholderString = "https://example.com/ground"

        let alert = NSAlert()
        alert.messageText = "Set grounding endpoint"
        alert.informativeText = "Used for debug grounding requests. This overrides CONTEXT_GROUNDING_ENDPOINT until cleared."
        alert.accessoryView = textField
        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")

        guard alert.runModal() == .alertFirstButtonReturn else { return }
        saveEndpoint(textField.stringValue)
    }

    private func showTutorialEndpointPrompt() {
        let textField = NSTextField(frame: NSRect(x: 0, y: 0, width: 420, height: 24))
        textField.stringValue = tutorialEndpointStore.baseURL ?? ""
        textField.placeholderString = "http://localhost:8000"

        let alert = NSAlert()
        alert.messageText = "Set tutorial API base URL"
        alert.informativeText = "Used for chat tutorial plan requests. Context will call POST /tutorials/plan from this base URL."
        alert.accessoryView = textField
        alert.addButton(withTitle: "Save")
        alert.addButton(withTitle: "Cancel")

        guard alert.runModal() == .alertFirstButtonReturn else { return }
        saveTutorialEndpoint(textField.stringValue)
    }

    private func saveEndpoint(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme != nil else {
            showInvalidEndpointAlert()
            return
        }

        endpointStore.save(url.absoluteString)
        rebuildMenu()
    }

    private func saveTutorialEndpoint(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme != nil else {
            showInvalidEndpointAlert()
            return
        }

        tutorialEndpointStore.save(url.absoluteString)
        rebuildMenu()
    }

    private func clearSavedEndpoint() {
        endpointStore.clearSavedEndpoint()
        rebuildMenu()
    }

    private func clearSavedTutorialEndpoint() {
        tutorialEndpointStore.clearSavedBaseURL()
        rebuildMenu()
    }

    private func showInvalidEndpointAlert() {
        let alert = NSAlert()
        alert.messageText = "Invalid endpoint URL"
        alert.informativeText = "Enter an absolute URL with a scheme, such as http://localhost:8000."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }

    private func showOverlay() {
        NSApp.activate(ignoringOtherApps: true)
        onShowOverlay()
    }

    private func isEvalModeEnabled() -> Bool {
        UserDefaults.standard.bool(forKey: StatusBarController.evalModeDefaultsKey)
    }

    private func toggleEvalMode() {
        let next = !isEvalModeEnabled()
        UserDefaults.standard.set(next, forKey: StatusBarController.evalModeDefaultsKey)
        rebuildMenu()
    }

    private func toggleGroundingAutoFire() {
        let next = !StatusBarController.isGroundingAutoFireEnabled()
        UserDefaults.standard.set(next, forKey: StatusBarController.groundingAutoFireDefaultsKey)
        rebuildMenu()
    }

    private func quitApplication() {
        NSApplication.shared.terminate(nil)
    }

    func showRecordings() {
        recordingsWindow.show()
    }
}
