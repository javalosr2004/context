import SwiftUI

@main
struct ContextAppApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate

    var body: some Scene {
        Settings {
            TutorialAPISettingsView()
        }
    }
}
