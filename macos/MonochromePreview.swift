import Foundation
import AppKit
import ImageIO

@MainActor extension AppModel {
    func workerEnvironment() -> [String: String] {
        var env = ProcessInfo.processInfo.environment
        env["PYTHONHOME"] = resources.appendingPathComponent("python").path
        env["PYTHONPATH"] = nil; env["PYTHONNOUSERSITE"] = "1"; env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["TOMONO_EXIFTOOL"] = resources.appendingPathComponent("exiftool/exiftool").path
        env["PATH"] = "/usr/bin:/bin"
        env["TOMONO_EXECUTION_LOG"] = ExecutionLogStore.shared.file.path
        return env
    }

    func thumbnail(_ url: URL) -> NSImage? {
        guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 1600, kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary) else { return nil }
        return NSImage(cgImage: image, size: NSSize(width: image.width, height: image.height))
    }

    func detailURL(_ overview: URL) -> URL { overview.deletingPathExtension().appendingPathExtension("detail.png") }
    func displayImage(_ overview: URL) -> NSImage? {
        let detail = detailURL(overview)
        return NSImage(contentsOf: detail) ?? thumbnail(overview)
    }
    func stopPreview() {
        previewTicket = UUID(); previewWork?.cancel(); previewWork = nil
        if previewTask?.isRunning == true { previewTask?.interrupt() }
        previewBusy = false
    }

    func monochromePreviewState() -> String {
        if showingReference { return "绿色参考对照 · 导出仍使用右侧设置" }
        if let item = selected, item.output != nil, item.outputRecipe == recipe { return "已保存的单色结果" }
        return "单色模拟 · 尚未导出"
    }
    func updatePreview() {
        stopPreview()
        guard let item = selected else { preview = nil; histogram = nil; rawHistogram = nil; previewMessage = ""; previewInput = nil; return }
        guard startupReady else { previewMessage = startupError ?? "正在检查转换引擎…"; return }
        identifyCamera(for:item.id)
        if previewInput != item.id { preview = nil; histogram = nil; rawHistogram = nil; greenCorrectionSummary = "生成模拟后显示实际校正数量"; previewInput = item.id }
        if showingSource { preview = thumbnail(item.url); previewMessage = "彩色原图预览"; return }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let displayRecipe = showingReference ? recipe.greenReferenceRecipe : recipe
        guard displayRecipe.responseValid, let data = try? encoder.encode(displayRecipe) else { previewMessage = "响应参数无效：请检查细节计算模式、RGB比重与±6EV曝光范围"; return }
        let attrs = try? FileManager.default.attributesOfItem(atPath: item.url.path)
        let modified = (attrs?[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        let key = "\(item.url.path)|\(attrs?[.size] ?? 0)|\(modified)|\(data.base64EncodedString())"
        if let cached = previewCache[key], FileManager.default.fileExists(atPath: cached.path) {
            applyResolvedParameters(previewResolved[key])
            histogram = previewHistograms[key]
            preview = displayImage(cached); previewMessage = monochromePreviewState(); return
        }
        if running { previewMessage = "正在转换，完成后显示单色结果"; return }
        previewBusy = true; previewMessage = "正在按当前设置生成单色模拟…"
        let ticket = previewTicket
        schedulePreview(input: item.url, recipe: data, key: key, ticket: ticket, delay: 0.3)
    }

    private func schedulePreview(input: URL, recipe: Data, key: String, ticket: UUID, delay: Double) {
        let work = DispatchWorkItem { [weak self] in
            self?.launchPreview(input: input, recipe: recipe, key: key, ticket: ticket)
        }
        previewWork = work; DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private func launchPreview(input: URL, recipe: Data, key: String, ticket: UUID) {
        guard previewTicket == ticket, !running else { return }
        if previewTask?.isRunning == true {
            schedulePreview(input: input, recipe: recipe, key: key, ticket: ticket, delay: 0.1); return
        }
        let token = UUID().uuidString
        let recipeFile = previewDirectory.appendingPathComponent(token + ".json")
        let output = previewDirectory.appendingPathComponent(token + ".png")
        do {
            try FileManager.default.createDirectory(at: previewDirectory, withIntermediateDirectories: true)
            try recipe.write(to: recipeFile)
            let task = Process(); task.executableURL = resources.appendingPathComponent("python/bin/python3")
            task.arguments = ["-s", resources.appendingPathComponent("backend/monochrome_preview.py").path, input.path, "-o", output.path, "--recipe", recipeFile.path, "--detail-output", detailURL(output).path]
            task.environment = workerEnvironment(); task.currentDirectoryURL = resources.appendingPathComponent("backend")
            let pipe = Pipe(); task.standardOutput = pipe; task.standardError = pipe
            try task.run(); previewTask = task
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                let data = pipe.fileHandleForReading.readDataToEndOfFile(); task.waitUntilExit()
                let event = String(data: data, encoding: .utf8)?.split(separator: "\n").last.flatMap { line in
                    try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any]
                }
                DispatchQueue.main.async {
                    ExecutionLogStore.shared.worker(String(data: data, encoding: .utf8) ?? "", context: "预览")
                    try? FileManager.default.removeItem(at: recipeFile)
                    guard let self else { try? FileManager.default.removeItem(at: output.deletingLastPathComponent()); return }
                    if self.previewTask === task { self.previewTask = nil }
                    if task.terminationStatus == 0, event?["state"] as? String == "ready" {
                        self.previewCache[key] = output
                        self.previewResolved[key] = event?["resolved_parameters"] as? [String: Any]
                        if let value=event?["histogram"],let data=try? JSONSerialization.data(withJSONObject:value),let histogram=try? JSONDecoder().decode(PreviewHistogram.self,from:data),histogram.valid {
                            self.previewHistograms[key]=histogram
                        }
                        // Bound temporary storage while retaining useful recipe comparisons.
                        if self.previewCache.count > 2, let old = self.previewCache.first(where: { $0.key != key }) {
                            try? FileManager.default.removeItem(at: old.value)
                            try? FileManager.default.removeItem(at: self.detailURL(old.value)); self.previewCache[old.key] = nil; self.previewResolved[old.key] = nil; self.previewHistograms[old.key] = nil
                        }
                        if self.previewTicket == ticket {
                            self.applyResolvedParameters(event?["resolved_parameters"] as? [String: Any])
                            self.histogram = self.previewHistograms[key]
                            self.preview = self.displayImage(output); self.previewBusy = false
                            self.previewMessage = self.monochromePreviewState()
                        }
                    } else {
                        try? FileManager.default.removeItem(at: output)
                        try? FileManager.default.removeItem(at: self.detailURL(output))
                        if self.previewTicket == ticket {
                            self.previewBusy = false
                            self.previewMessage = "无法生成单色模拟：" + (event?["message"] as? String ?? "请检查输入文件与设置")
                        }
                    }
                }
            }
        } catch {
            try? FileManager.default.removeItem(at: recipeFile)
            previewBusy = false; previewMessage = "无法生成单色模拟：\(error.localizedDescription)"
        }
    }

    func cleanupPreviews() {
        stopPreview()
        if previewTask?.isRunning != true { try? FileManager.default.removeItem(at: previewDirectory) }
    }
    func applyResolvedParameters(_ parameters: [String: Any]?) {
        if let value=parameters?["raw_histogram"],let data=try? JSONSerialization.data(withJSONObject:value),let histogram=try? JSONDecoder().decode(RawSourceHistogram.self,from:data),histogram.valid { rawHistogram=histogram }
        if let response=parameters?["response"] as? [String:Any],let numbers=response["weights"] as? [NSNumber] {
            let weights=numbers.map(\.doubleValue)
            let mode=response["mode"] as? String ?? "green"
            let greenName = parameters?["effective_detail_mode"] as? String == "legacy" ? "绿色参考" : "绿色响应"
            let name=["green":greenName,"mix":"RGB 响应混合","narrow_red":"红光窄带 · R采样","narrow_green":"绿光窄带 · G采样","narrow_blue":"蓝光窄带 · B采样"][mode] ?? mode
            let exposure=response["exposure_ev"] as? Double ?? 0
            responseSummary=name+" · "+zip(["R","G","B"],weights).map { String(format:"%@ %.0f%%",$0.0,$0.1*100) }.joined(separator:" / ")+String(format:" · %+.2f EV",exposure)
        }
        if let changed=parameters?["green_replacements"] as? Int {
            if (parameters?["green_compensation"] as? Double ?? 0) <= 0 { greenCorrectionSummary="当前未启用绿色差异校正" }
            else if changed == 0 { greenCorrectionSummary="当前条件未触发绿色差异校正" }
            else {
                let count=parameters?["reconstruction_sample_count"] as? Int ?? 0
                let ratio=count>0 ? String(format:"%.4f",Double(changed)/Double(count)*100) : "—"
                greenCorrectionSummary="已校正 \(changed.formatted()) 个绿色采样 · 占重建采样 \(ratio)%"
            }
        }
        if let lens=parameters?["lens_correction"] as? [String:Any],lens["applied"] as? Bool == true { lensCorrectionSummary="当前模拟已应用镜头校正" }
        else { lensCorrectionSummary="未应用额外镜头校正" }
        if let requested = parameters?["requested_detail_mode"] as? String,
           let effective = parameters?["effective_detail_mode"] as? String {
            let title = effective == "legacy" && requested != "legacy" ? "原有采样重建" : RecipeDocument.detailTitle(effective)
            let code = parameters?["detail_method_code"] as? String
            reconstructionSummary = title + (code.map { " · " + $0 } ?? "")
            if let reason = parameters?["detail_fallback_reason"] as? String, !reason.isEmpty {
                reconstructionSummary += "\n" + (reason == "Input is not a directly unpacked 2x2 RGB Bayer CFA" ? "当前输入不是直接读取的2×2 RGB Bayer，已使用原有采样重建。" : reason)
            }
            return
        }
        guard let path = parameters?["processing_path"] as? String else { return }
        reconstructionSummary = path.hasPrefix("pure_narrowband_") ? "窄带纯通道 · "+(path.hasSuffix("linear") ? "线性同色插值" : "有界三次同色插值") : path == "raw_channel_response" ? "RAW 通道响应重建" : path == "edge_aware_green" ? "边缘自适应绿色重建" : path.hasPrefix("libraw_linear") ? "LibRaw 线性重建" : path == "generic_green_lattice" ? "绿色采样重建" : "双三次 Bayer 重建"
    }
}
