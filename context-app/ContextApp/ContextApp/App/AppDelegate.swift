import AppKit

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var overlayCoordinator: OverlayCoordinator?

    func applicationDidFinishLaunching(_ notification: Notification) {
        let coordinator = OverlayCoordinator(screenProvider: { NSScreen.main })
        overlayCoordinator = coordinator
        coordinator.start()
    }

    func applicationWillTerminate(_ notification: Notification) {
        overlayCoordinator?.stop()
        overlayCoordinator = nil
    }
}
