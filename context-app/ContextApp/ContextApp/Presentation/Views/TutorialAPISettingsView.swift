import SwiftUI

struct TutorialAPISettingsView: View {
    private let endpointStore: TutorialAPIEndpointStore

    @State private var baseURLText: String
    @State private var validationMessage: String?

    init(endpointStore: TutorialAPIEndpointStore = TutorialAPIEndpointStore()) {
        self.endpointStore = endpointStore
        self._baseURLText = State(initialValue: endpointStore.savedBaseURL ?? endpointStore.baseURL ?? "")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Text("Tutorial API")
                .font(.headline)

            VStack(alignment: .leading, spacing: 6) {
                Text("Backend base URL")
                    .font(.caption)
                    .foregroundStyle(.secondary)

                TextField("http://localhost:8000", text: $baseURLText)
                    .textFieldStyle(.roundedBorder)
                    .frame(width: 360)

                if let validationMessage {
                    Text(validationMessage)
                        .font(.caption)
                        .foregroundStyle(.red)
                }
            }

            HStack(spacing: 8) {
                Button("Save", action: save)
                    .keyboardShortcut(.defaultAction)

                Button("Clear", action: clear)
            }

            Spacer()
        }
        .padding(20)
        .frame(width: 420, height: 180)
    }

    private func save() {
        let trimmed = baseURLText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let url = URL(string: trimmed), url.scheme != nil else {
            validationMessage = "Enter an absolute URL with a scheme."
            return
        }

        endpointStore.save(url.absoluteString)
        baseURLText = url.absoluteString
        validationMessage = nil
    }

    private func clear() {
        endpointStore.clearSavedBaseURL()
        baseURLText = endpointStore.baseURL ?? ""
        validationMessage = nil
    }
}
