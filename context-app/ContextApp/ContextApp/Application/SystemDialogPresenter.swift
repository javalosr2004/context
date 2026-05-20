import AppKit

@MainActor
enum SystemDialogPresenter {
    static func runSynchronously<T>(_ body: () -> T) -> T {
        let demoted = demoteScreenSaverWindows()
        defer { restore(demoted) }
        return body()
    }

    private static func demoteScreenSaverWindows() -> [(NSWindow, NSWindow.Level)] {
        NSApp.windows.compactMap { window in
            guard window.level == .screenSaver else { return nil }
            let previous = window.level
            window.level = .normal
            return (window, previous)
        }
    }

    private static func restore(_ windows: [(NSWindow, NSWindow.Level)]) {
        for (window, level) in windows {
            window.level = level
        }
    }
}
