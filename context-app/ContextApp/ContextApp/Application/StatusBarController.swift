import AppKit

@MainActor
final class StatusBarController {
    private let endpointStore: GroundingEndpointStore
    private let onTestBbox: () -> Void
    private let statusItem: NSStatusItem

    init(
        endpointStore: GroundingEndpointStore,
        onTestBbox: @escaping () -> Void
    ) {
        self.endpointStore = endpointStore
        self.onTestBbox = onTestBbox
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
        menu.addItem(CallbackMenuItem(title: "Test green bbox", actionHandler: onTestBbox))
        statusItem.menu = menu
    }

    private func endpointTitle() -> String {
        guard let endpoint = endpointStore.endpoint else {
            return "Grounding endpoint: Not set"
        }

        return "Grounding endpoint: \(endpoint)"
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

    private func saveEndpoint(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme != nil else {
            showInvalidEndpointAlert()
            return
        }

        endpointStore.save(url.absoluteString)
        rebuildMenu()
    }

    private func clearSavedEndpoint() {
        endpointStore.clearSavedEndpoint()
        rebuildMenu()
    }

    private func showInvalidEndpointAlert() {
        let alert = NSAlert()
        alert.messageText = "Invalid endpoint URL"
        alert.informativeText = "Enter an absolute URL with a scheme, such as https://example.com/ground."
        alert.addButton(withTitle: "OK")
        alert.runModal()
    }
}
