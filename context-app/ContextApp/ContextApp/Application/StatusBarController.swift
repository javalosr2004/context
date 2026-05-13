import AppKit

@MainActor
final class StatusBarController {
    private let endpointStore: GroundingEndpointStore
    private let onTestBbox: () -> Void
    private let statusItem: NSStatusItem
    private let tutorialEndpointStore: TutorialAPIEndpointStore

    init(
        endpointStore: GroundingEndpointStore,
        tutorialEndpointStore: TutorialAPIEndpointStore,
        onTestBbox: @escaping () -> Void
    ) {
        self.endpointStore = endpointStore
        self.onTestBbox = onTestBbox
        self.tutorialEndpointStore = tutorialEndpointStore
        self.statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        configureStatusItem()
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

    private func quitApplication() {
        NSApplication.shared.terminate(nil)
    }
}
