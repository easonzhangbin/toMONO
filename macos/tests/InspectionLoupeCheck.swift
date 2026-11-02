import AppKit
import SwiftUI

/// Opt-in UI/worker integration against private sample copies and live sources.
/// This executable never exports or writes a user RAW, installs, or packages.
@main struct InspectionLoupeCheck: App {
    @StateObject private var model: AppModel
    @State private var started = false

    init() {
        let path = ProcessInfo.processInfo.environment["TOMONO_QA_RESOURCES"]!
        _model = StateObject(wrappedValue: AppModel(resourceOverride: URL(fileURLWithPath: path)))
    }

    var body: some Scene {
        Window("toMONO 局部检查验证", id: "workspace") {
            ContentView(model: model)
                .environment(\.locale, Locale(identifier: "zh_Hans"))
                .onAppear {
                    guard !started else { return }; started = true
                    Task { @MainActor in await verify() }
                }
        }.defaultSize(width: 1440, height: 980)
    }

    @MainActor private func verify() async {
        let root = URL(fileURLWithPath: ProcessInfo.processInfo.environment["TOMONO_QA_DIR"]!)
        var result: [String: Any] = [:]
        func require(_ condition: Bool, _ message: String) throws {
            if !condition { throw NSError(domain: "InspectionLoupeCheck", code: 1, userInfo: [NSLocalizedDescriptionKey: message]) }
        }
        func wait(_ description: String, timeout: TimeInterval = 120, _ condition: () -> Bool) async throws {
            let start = Date()
            while !condition() {
                if Date().timeIntervalSince(start) > timeout {
                    throw NSError(domain: "InspectionLoupeCheck", code: 2,
                        userInfo: [NSLocalizedDescriptionKey: "等待超时：\(description)，\(model.previewMessage)，\(model.startupError ?? "")"])
                }
                try await Task.sleep(nanoseconds: 50_000_000)
            }
            // Permit SwiftUI publication and the NSViewRepresentable update.
            try await Task.sleep(nanoseconds: 120_000_000)
        }
        func viewer(in parent: NSView?) -> ImageScrollView? {
            if let view = parent as? ImageScrollView { return view }
            for child in parent?.subviews ?? [] { if let found = viewer(in: child) { return found } }
            return nil
        }
        func pixels(_ detail: PreviewDetail?) -> Data? {
            guard let image = detail?.image,
                  let rep = image.representations.compactMap({ $0 as? NSBitmapImageRep }).first,
                  let bytes = rep.bitmapData else { return nil }
            return Data(bytes: bytes, count: rep.bytesPerRow * rep.pixelsHigh)
        }
        func ready(_ mode: String) -> Bool {
            guard !model.previewBusy, model.preview != nil, let key = model.previewCurrentKey,
                  let parameters = model.previewResolved[key] else { return false }
            return parameters["effective_detail_mode"] as? String == mode
        }
        func pairedLoupe() -> Bool {
            guard let state = model.inspectionLoupe else { return false }
            return !state.loading && state.before != nil && state.after != nil
        }
        func assertPair(_ state: InspectionLoupeState, _ anchor: NSRect) throws {
            try require(state.region.rect == anchor, "局部对照改变了所选检查区域")
            try require(state.before?.rect == anchor && state.after?.rect == anchor, "切换前后并非同一区域")
            for detail in [state.before, state.after].compactMap({ $0 }) {
                try require(detail.image.size == anchor.size, "放大镜使用了缩略图而非原生像素")
                try require(max(detail.image.size.width, detail.image.size.height) <= 192, "局部检查载入了超出所需的整图")
            }
        }
        func capture(_ name: String, window: NSWindow) {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/sbin/screencapture")
            process.arguments = ["-x", "-l", String(window.windowNumber), root.appendingPathComponent(name).path]
            do { try process.run(); process.waitUntilExit() } catch { return }
            result[name] = process.terminationStatus == 0 && FileManager.default.fileExists(atPath: root.appendingPathComponent(name).path)
        }
        do {
            let paths = try JSONDecoder().decode([String].self, from: Data(contentsOf: root.appendingPathComponent("inputs.json")))
            try await wait("启动引擎") { model.startupReady }
            try require(RecipeDocument().detail_mode == "directional", "新照片未默认使用 D10")
            model.add(paths.map { URL(fileURLWithPath: $0) })
            guard model.items.count == 2 else { throw NSError(domain: "需要两个测试样片", code: 1) }
            let first = model.items[0].id, second = model.items[1].id
            model.setSelection([first])
            try await wait("首张 D10 预览") { model.previewInput == first && ready("directional") }
            try require(model.inspectionLoupe == nil, "首次载入不应自动遮住画面")
            result["default_d10_initial_overview"] = true

            guard let window = NSApp.windows.first(where: { $0.title == "toMONO 局部检查验证" }),
                  let view = viewer(in: window.contentView) else { throw NSError(domain: "找不到实际预览视图", code: 1) }
            window.setContentSize(NSSize(width: 1440, height: 980))
            window.center(); window.makeKeyAndOrderFront(nil)
            // Native scale gives the anchor-preservation assertion a non-fit viewport.
            view.setScale(1, centeredAt: NSPoint(x: view.canvas.bounds.width * 0.43, y: view.canvas.bounds.height * 0.54))
            try await wait("100% 原生区域") { !model.previewDetailBusy && model.previewDetail != nil }
            let origin = view.contentView.bounds.origin, scale = view.magnification

            let firstSwitch = Date()
            model.recipe.detail_mode = "spectral"; model.updatePreview()
            try await wait("切换时放大镜加载状态", timeout: 5) { model.inspectionLoupe?.loading == true && model.previewBusy }
            guard let anchor = model.inspectionLoupe?.region.rect else { throw NSError(domain: "缺少自动检查区域", code: 1) }
            result["mode_switch_shows_loading"] = true
            try await wait("D10 与 C01 的同区原生对照") { ready("spectral") && pairedLoupe() }
            let state = model.inspectionLoupe!
            try assertPair(state, anchor)
            try require(state.beforeTitle.contains("方向") && state.afterTitle.contains("频域"), "模式对照标题错误")
            try require(pixels(state.before) != pixels(state.after), "GR IIIx 的不同模式对照意外使用同一张图片")
            try require(abs(view.magnification - scale) < 0.001, "放大镜改变了主预览缩放")
            try require(abs(view.contentView.bounds.origin.x - origin.x) < 1 && abs(view.contentView.bounds.origin.y - origin.y) < 1, "切换模式后主观察位置移动")
            try require(view.canvas.inspectionRect == anchor, "主图定位框未对应放大镜区域")
            result["same_region_native_before_after"] = true
            result["main_zoom_and_pan_preserved"] = true
            result["first_switch_seconds"] = Date().timeIntervalSince(firstSwitch)
            result["inspection_region"] = [anchor.minX, anchor.minY, anchor.width, anchor.height]
            capture("loupe_native.png", window: window)

            let count = model.previewCache.count
            model.nextInspectionRegion()
            try await wait("另一检查区域") { pairedLoupe() && model.inspectionLoupe!.region.rect != anchor }
            let secondAnchor = model.inspectionLoupe!.region.rect
            try assertPair(model.inspectionLoupe!, secondAnchor)
            try require(model.previewTask == nil && model.previewCache.count == count, "更换放大镜区域触发了整图重建")
            result["next_region_reuses_cached_native_rasters"] = true

            model.dismissInspectionLoupe()
            try await wait("关闭本次对照") { model.inspectionLoupe == nil }
            try require(model.inspectionEnabled, "关闭本次对照不应禁用下次自动显示")
            try require(model.previewTask == nil, "关闭对照触发了重建")
            model.setInspectionEnabled(false)
            model.recipe.detail_mode = "spectral_guard"; model.updatePreview()
            try await wait("关闭局部检查后的 D11") { ready("spectral_guard") }
            try require(model.inspectionLoupe == nil, "禁用局部检查后仍自动弹出")
            result["dismiss_and_disable_are_distinct"] = true

            model.setInspectionEnabled(true)
            try await wait("重新启用局部检查") { model.inspectionLoupe?.after != nil && model.inspectionLoupe?.loading == false }
            try require(model.previewTask == nil, "重新启用局部检查触发整图重建")
            result["reenable_does_not_reconstruct"] = true

            // Start an uncached method, then immediately settle on a cached one.
            model.recipe.detail_mode = "lmmse"; model.updatePreview()
            try await Task.sleep(nanoseconds: 250_000_000)
            model.recipe.detail_mode = "spectral_guard"; model.updatePreview()
            try await wait("快速切换后保持 D11") { ready("spectral_guard") && model.inspectionLoupe?.after != nil && model.inspectionLoupe?.loading == false }
            let latestTitle = model.inspectionLoupe!.afterTitle, latestRegion = model.inspectionLoupe!.region.rect
            let latestPixels = pixels(model.inspectionLoupe!.after)
            try await Task.sleep(nanoseconds: 1_000_000_000)
            try require(ready("spectral_guard") && model.inspectionLoupe?.afterTitle == latestTitle && model.inspectionLoupe?.region.rect == latestRegion && pixels(model.inspectionLoupe?.after) == latestPixels, "旧模式的完成回调污染了当前对照")
            result["rapid_switch_ignores_stale_completion"] = true

            // D10 is still the independent default of the second queue item.
            model.recipe.detail_mode = "lmmse"; model.updatePreview()
            try await Task.sleep(nanoseconds: 250_000_000)
            model.setSelection([second])
            try await wait("切换另一张照片") { model.previewInput == second && ready("directional") }
            try require(model.inspectionLoupe == nil, "切换照片后残留了上一张局部对照")
            try await Task.sleep(nanoseconds: 700_000_000)
            try require(model.previewInput == second && model.inspectionLoupe == nil, "旧照片任务污染了新照片")
            result["photo_change_cancels_and_clears_loupe"] = true
            result["no_export_or_package"] = true
            result["passed"] = true
        } catch {
            result["passed"] = false
            result["error"] = error.localizedDescription
        }
        try? JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
            .write(to: root.appendingPathComponent("inspection_loupe.json"))
        model.cleanupPreviews(); model.stopStartup()
        NSApp.terminate(nil)
    }
}
