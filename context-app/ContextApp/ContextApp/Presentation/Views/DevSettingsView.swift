import SwiftUI

struct DevSettingsView: View {
    private let visualStore: GroundingEndpointStore
    private let webStore: WebGroundingEndpointStore
    private let tutorialStore: TutorialAPIEndpointStore
    private let onClose: () -> Void

    @State private var visualText: String
    @State private var webText: String
    @State private var backendText: String
    @State private var validationMessage: String?
    @State private var savedAt: Date?

    init(
        visualStore: GroundingEndpointStore,
        webStore: WebGroundingEndpointStore,
        tutorialStore: TutorialAPIEndpointStore,
        onClose: @escaping () -> Void
    ) {
        self.visualStore = visualStore
        self.webStore = webStore
        self.tutorialStore = tutorialStore
        self.onClose = onClose
        _visualText = State(initialValue: visualStore.savedEndpoint ?? visualStore.endpoint ?? "")
        _webText = State(initialValue: webStore.savedEndpoint ?? webStore.endpoint ?? "")
        _backendText = State(initialValue: tutorialStore.savedBaseURL ?? tutorialStore.baseURL ?? "")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Text("Developer Settings")
                    .font(.headline)
                Spacer()
                Button(action: onClose) {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundStyle(.secondary)
                }
                .buttonStyle(.plain)
                .keyboardShortcut(.cancelAction)
            }

            field(
                title: "Visual grounding URL",
                placeholder: "https://example.com/ground",
                text: $visualText
            )
            field(
                title: "Web grounding URL",
                placeholder: "https://example.com/web-ground",
                text: $webText
            )
            field(
                title: "Backend URL",
                placeholder: "http://localhost:8000",
                text: $backendText
            )

            if let validationMessage {
                Text(validationMessage)
                    .font(.caption)
                    .foregroundStyle(.red)
            } else if savedAt != nil {
                Text("Saved.")
                    .font(.caption)
                    .foregroundStyle(.green)
            }

            HStack(spacing: 8) {
                Button("Save", action: save)
                    .keyboardShortcut(.defaultAction)
                Button("Clear All", action: clearAll)
                Spacer()
                Button("Close", action: onClose)
            }
        }
        .padding(20)
        .frame(width: 460)
    }

    @ViewBuilder
    private func field(title: String, placeholder: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption)
                .foregroundStyle(.secondary)
            TextField(placeholder, text: text)
                .textFieldStyle(.roundedBorder)
        }
    }

    private func save() {
        if let error = validate(visualText, label: "Visual grounding URL") { validationMessage = error; return }
        if let error = validate(webText, label: "Web grounding URL") { validationMessage = error; return }
        if let error = validate(backendText, label: "Backend URL") { validationMessage = error; return }

        apply(visualText, save: { visualStore.save($0) }, clear: { visualStore.clearSavedEndpoint() })
        apply(webText, save: { webStore.save($0) }, clear: { webStore.clearSavedEndpoint() })
        apply(backendText, save: { tutorialStore.save($0) }, clear: { tutorialStore.clearSavedBaseURL() })

        validationMessage = nil
        savedAt = Date()
    }

    private func validate(_ raw: String, label: String) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty { return nil }
        guard let url = URL(string: trimmed), url.scheme != nil else {
            return "\(label) must be an absolute URL with a scheme."
        }
        return nil
    }

    private func apply(_ raw: String, save: (String) -> Void, clear: () -> Void) {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            clear()
        } else {
            save(trimmed)
        }
    }

    private func clearAll() {
        visualStore.clearSavedEndpoint()
        webStore.clearSavedEndpoint()
        tutorialStore.clearSavedBaseURL()
        visualText = visualStore.endpoint ?? ""
        webText = webStore.endpoint ?? ""
        backendText = tutorialStore.baseURL ?? ""
        validationMessage = nil
        savedAt = Date()
    }
}
