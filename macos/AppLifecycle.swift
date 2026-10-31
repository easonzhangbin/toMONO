import AppKit

@MainActor final class AppLifecycle: NSObject, NSApplicationDelegate {
    static let models = NSHashTable<AppModel>.weakObjects()
    private var terminationTimer: Timer?
    private let configuredWindows = NSHashTable<NSWindow>.weakObjects()

    func applicationWillFinishLaunching(_ notification: Notification) { NSWindow.allowsAutomaticWindowTabbing = false }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NotificationCenter.default.addObserver(self, selector: #selector(windowBecameKey(_:)), name: NSWindow.didBecomeKeyNotification, object: nil)
        for window in NSApp.windows { configureToolbar(window) }
    }
    @objc private func windowBecameKey(_ notification: Notification) {
        if let window = notification.object as? NSWindow { configureToolbar(window) }
    }
    private func configureToolbar(_ window: NSWindow) {
        window.tabbingMode = .disallowed
        guard !(window is NSPanel), window.title == "toMONO", !configuredWindows.contains(window) else { return }
        configuredWindows.add(window)
        if let toolbar = window.toolbar, toolbar.displayMode != .iconAndLabel { toolbar.displayMode = .iconAndLabel }
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        if Self.models.allObjects.contains(where: { $0.running }) {
            let alert = NSAlert()
            alert.messageText = "照片仍在转换"
            alert.informativeText = "退出前需要停止当前任务。已经保存的 DNG 会保留，未完成的任务会取消。"
            alert.addButton(withTitle: "取消转换并退出")
            alert.addButton(withTitle: "继续处理")
            guard alert.runModal() == .alertFirstButtonReturn else { return .terminateCancel }
        }
        for model in Self.models.allObjects { model.stopPreview(); model.stopStartup() }
        for model in Self.models.allObjects where model.running { model.cancel() }
        if !Self.models.allObjects.contains(where: { $0.running || $0.previewTask?.isRunning == true || $0.startupTask?.isRunning == true }) {
            for model in Self.models.allObjects { model.cleanupPreviews() }
            return .terminateNow
        }
        terminationTimer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
            MainActor.assumeIsolated {
                if !Self.models.allObjects.contains(where: { $0.running || $0.previewTask?.isRunning == true || $0.startupTask?.isRunning == true }) {
                    self?.terminationTimer?.invalidate(); self?.terminationTimer = nil
                    for model in Self.models.allObjects { model.cleanupPreviews() }
                    NSApp.reply(toApplicationShouldTerminate: true)
                }
            }
        }
        return .terminateLater
    }
}
