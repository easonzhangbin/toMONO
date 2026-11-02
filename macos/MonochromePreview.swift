import Foundation
import AppKit
import ImageIO

// A fixed bitmap avoids AppKit manufacturing Retina snapshot representations
// whose reported pixel dimensions are twice the actual preview raster.
private func previewBitmap(_ cg: CGImage) -> NSImage {
    let image = NSImage(size:NSSize(width:cg.width,height:cg.height))
    image.addRepresentation(NSBitmapImageRep(cgImage:cg));image.cacheMode = .never
    return image
}

struct PreviewDetail {
    let image: NSImage
    let rect: NSRect // Oriented RAW crop pixels, never proxy pixels.
}

// The only mutable state is protected by lock on every access.
final class PreviewTileCancellation: @unchecked Sendable {
    private let lock = NSLock()
    private var stopped = false
    func cancel() { lock.lock();stopped=true;lock.unlock() }
    var cancelled: Bool { lock.lock();defer { lock.unlock() };return stopped }
}

struct PreviewRaster: Decodable {
    let path: String
    let lut_path: String
    let width: Int
    let height: Int
    let crop_x: Int
    let crop_y: Int
    let crop_width: Int
    let crop_height: Int
    let orientation: Int
    var byteCount: Int { width * height * 2 }
    var displaySize: NSSize {
        orientation >= 5 ? NSSize(width:crop_height,height:crop_width) : NSSize(width:crop_width,height:crop_height)
    }
    var exists: Bool { FileManager.default.fileExists(atPath:path) && FileManager.default.fileExists(atPath:lut_path) }
    func remove() { try? FileManager.default.removeItem(atPath:path);try? FileManager.default.removeItem(atPath:lut_path) }
    func render(_ requested: NSRect, colorSpace: CGColorSpace, cancellation: PreviewTileCancellation) throws -> PreviewDetail {
        func invalid(_ message:String) -> NSError { NSError(domain:"toMONO",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
        guard width>0,height>0,width<=100_000,height<=100_000,crop_x>=0,crop_y>=0,
              crop_width>0,crop_height>0,crop_x+crop_width<=width,crop_y+crop_height<=height,(1...8).contains(orientation) else {
            throw invalid("细节缓存几何无效")
        }
        let rect=requested.integral.intersection(NSRect(origin:.zero,size:displaySize))
        let w=Int(rect.width),h=Int(rect.height),x0=Int(rect.minX),y0=Int(rect.minY)
        guard w>0,h>0,w*h<=64_000_000,colorSpace.numberOfComponents==3 else { throw invalid("细节区域或色彩空间无效") }
        let source=try Data(contentsOf:URL(fileURLWithPath:path),options:.mappedIfSafe)
        let lut=try Data(contentsOf:URL(fileURLWithPath:lut_path))
        guard source.count==byteCount,lut.count==65536 else { throw invalid("细节缓存不完整，请重新生成预览") }
        var rgba=Data(count:w*h*4)
        try rgba.withUnsafeMutableBytes { destination in
            try source.withUnsafeBytes { bytes in
                try lut.withUnsafeBytes { table in
                    let dst=destination.bindMemory(to:UInt8.self)
                    let src=bytes.bindMemory(to:UInt16.self)
                    let values=table.bindMemory(to:UInt8.self)
                    for row in 0..<h {
                        if row % 32 == 0 && cancellation.cancelled { throw invalid("细节请求已取消") }
                        let y=y0+row
                        for column in 0..<w {
                            let x=x0+column
                            let sx:Int,sy:Int
                            switch orientation {
                            case 2: sx=crop_width-1-x;sy=y
                            case 3: sx=crop_width-1-x;sy=crop_height-1-y
                            case 4: sx=x;sy=crop_height-1-y
                            case 5: sx=y;sy=x
                            case 6: sx=y;sy=crop_height-1-x
                            case 7: sx=crop_width-1-y;sy=crop_height-1-x
                            case 8: sx=crop_width-1-y;sy=x
                            default: sx=x;sy=y
                            }
                            let value=values[Int(UInt16(littleEndian:src[(crop_y+sy)*width+crop_x+sx]))]
                            let at=(row*w+column)*4
                            dst[at]=value;dst[at+1]=value;dst[at+2]=value;dst[at+3]=255
                        }
                    }
                }
            }
        }
        guard let provider=CGDataProvider(data:rgba as CFData),let cg=CGImage(width:w,height:h,bitsPerComponent:8,bitsPerPixel:32,bytesPerRow:w*4,space:colorSpace,bitmapInfo:CGBitmapInfo(rawValue:CGImageAlphaInfo.noneSkipLast.rawValue),provider:provider,decode:nil,shouldInterpolate:false,intent:.defaultIntent) else { throw invalid("无法创建细节显示图") }
        return PreviewDetail(image:previewBitmap(cg),rect:rect)
    }
}

private let previewTileQueue = DispatchQueue(label:"cn.tomono.preview.tiles",qos:.userInitiated)

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
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 2048, kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary) else { return nil }
        return previewBitmap(image)
    }
    func detailURL(_ overview: URL) -> URL { overview.deletingPathExtension().appendingPathExtension("detail.png") }
    func stopPreview() {
        previewTicket = UUID(); previewWork?.cancel(); previewWork = nil
        if previewTask?.isRunning == true { previewTask?.interrupt() }
        previewBusy = false; cancelPreviewTile();previewDetail = nil
    }
    func monochromePreviewState() -> String {
        if showingReference { return "绿色参考对照 · 导出仍使用右侧设置" }
        if let item = selected, item.output != nil, item.outputRecipe == recipe { return "已保存的单色结果" }
        return "单色模拟 · 尚未导出"
    }
    private func cancelPreviewTile() {
        previewTileTicket = UUID();previewTileWork?.cancel();previewTileWork=nil
        previewTileCancellation?.cancel();previewTileCancellation=nil
        previewDetailBusy=false;previewPendingRect=nil
    }
    func previewViewportChanged(scale: Double, fitted: Bool, rect: NSRect) {
        guard !showingSource, preview != nil, previewPixelSize.width > 0 else { return }
        previewViewport = rect
        let overviewScale=min(1,2048/max(previewPixelSize.width,previewPixelSize.height))
        previewWantsDetail = !fitted && scale > overviewScale
        if !previewWantsDetail {
            cancelPreviewTile();previewDetail=nil
            if !previewBusy { previewMessage=monochromePreviewState() }
            return
        }
        loadVisibleDetail()
    }
    private func loadVisibleDetail() {
        guard previewWantsDetail,!previewBusy,!running,let key=previewCurrentKey,let viewport=previewViewport else { return }
        guard let raster=previewRasters[key],raster.exists else {
            previewRasters[key]=nil;updatePreview();return
        }
        let visible=viewport.integral.intersection(NSRect(origin:.zero,size:raster.displaySize))
        guard !visible.isEmpty else { return }
        if previewDetail?.rect.contains(visible) == true || previewPendingRect?.contains(visible) == true { return }
        cancelPreviewTile()
        let padded=visible.insetBy(dx:-256,dy:-256).integral.intersection(NSRect(origin:.zero,size:raster.displaySize))
        guard let color=preview?.cgImage(forProposedRect:nil,context:nil,hints:nil)?.colorSpace else { return }
        let request=PreviewTileCancellation();previewTileCancellation=request
        let ticket=previewTileTicket;previewPendingRect=padded;previewDetailBusy=true
        previewMessage="正在加载可见区域的原生细节…"
        previewRasterOrder.removeAll { $0==key };previewRasterOrder.append(key)
        let start=Date()
        let work=DispatchWorkItem { [weak self] in
            let result=Result { try raster.render(padded,colorSpace:color,cancellation:request) }
            DispatchQueue.main.async {
                guard let self,self.previewTileTicket==ticket,self.previewCurrentKey==key,!request.cancelled else { return }
                self.previewDetailBusy=false;self.previewPendingRect=nil
                switch result {
                case .success(let detail):
                    self.previewDetail=detail;self.previewMessage=self.monochromePreviewState()
                    ExecutionLogStore.shared.record("preview_detail_tile_ready",fields:["milliseconds":Date().timeIntervalSince(start)*1000,"width":Int(detail.rect.width),"height":Int(detail.rect.height),"reconstructed_again":false])
                case .failure(let error): self.previewMessage="细节加载失败："+error.localizedDescription
                }
            }
        }
        previewTileWork=work
        previewTileQueue.asyncAfter(deadline:.now()+0.06,execute:work)
    }
    private func touchPreview(_ key: String) {
        previewOrder.removeAll { $0 == key }; previewOrder.append(key)
    }
    private func removePreviewFiles(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
        try? FileManager.default.removeItem(at: detailURL(url))
        try? FileManager.default.removeItem(at:url.deletingPathExtension().appendingPathExtension("linear16"))
        try? FileManager.default.removeItem(at:url.deletingPathExtension().appendingPathExtension("lut8"))
    }
    private func displayCachedPreview(_ key: String, url: URL) {
        touchPreview(key)
        applyResolvedParameters(previewResolved[key]); histogram = previewHistograms[key]
        previewPixelSize = previewSizes[key] ?? .zero
        preview = NSImage(contentsOf:url)
        preview?.cacheMode = .never
        previewMessage = monochromePreviewState()
        previewShownKey=key;previewShownRecipe=previewRecipes[key]
        if let applied=previewShownRecipe { commitInspectionPreview(key:key,applied:applied) }
    }
    func updatePreview() {
        stopPreview()
        guard let item = selected else {
            dismissInspectionLoupe();previewShownKey=nil;previewShownRecipe=nil
            preview = nil; histogram = nil; rawHistogram = nil; previewMessage = ""; previewInput = nil
            previewPixelSize = .zero; previewWantsDetail = false;previewCurrentKey=nil; return
        }
        guard startupReady else { previewMessage = startupError ?? "正在检查转换引擎…"; return }
        identifyCamera(for:item.id)
        if previewInput != item.id {
            dismissInspectionLoupe();previewShownKey=nil;previewShownRecipe=nil
            preview = nil; histogram = nil; rawHistogram = nil; previewPixelSize = .zero
            greenCorrectionSummary = "生成模拟后显示实际校正数量"; previewInput = item.id
            previewWantsDetail = false;previewViewport=nil
        }
        if showingSource {
            dismissInspectionLoupe()
            previewWantsDetail = false;previewViewport=nil
            preview = thumbnail(item.url); previewPixelSize = .zero; previewMessage = "彩色原图预览"; return
        }
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let displayRecipe = showingReference ? recipe.greenReferenceRecipe : recipe
        if showingReference { dismissInspectionLoupe() }
        guard displayRecipe.responseValid, let data = try? encoder.encode(displayRecipe) else {
            previewMessage = "响应参数无效：请检查细节计算模式、RGB比重与±6EV曝光范围"; return
        }
        let attrs = try? FileManager.default.attributesOfItem(atPath: item.url.path)
        let modified = (attrs?[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        let key = "\(item.url.path)|\(attrs?[.size] ?? 0)|\(modified)|\(data.base64EncodedString())"
        previewCurrentKey=key
        if let cached = previewCache[key], FileManager.default.fileExists(atPath: cached.path) {
            displayCachedPreview(key,url:cached)
            if !previewWantsDetail || previewRasters[key]?.exists == true {
                ExecutionLogStore.shared.record("preview_cache_hit",fields:["input":item.url.path,"detail":previewWantsDetail])
                loadVisibleDetail();return
            }
        }
        if running { previewMessage = "正在转换，完成后显示单色结果"; return }
        previewBusy = true
        previewMessage = previewWantsDetail ? "正在加载细节…" : "正在生成预览"
        schedulePreview(input:item.url,recipe:data,key:key,ticket:previewTicket,detail:previewWantsDetail,delay:0.3)
    }
    private func schedulePreview(input: URL, recipe: Data, key: String, ticket: UUID, detail: Bool, delay: Double) {
        let work = DispatchWorkItem { [weak self] in
            self?.launchPreview(input:input,recipe:recipe,key:key,ticket:ticket,detail:detail)
        }
        previewWork = work; DispatchQueue.main.asyncAfter(deadline:.now()+delay,execute:work)
    }
    private func launchPreview(input: URL, recipe: Data, key: String, ticket: UUID, detail: Bool) {
        guard previewTicket == ticket, !running else { return }
        if previewTask?.isRunning == true {
            schedulePreview(input:input,recipe:recipe,key:key,ticket:ticket,detail:detail,delay:0.1); return
        }
        let token = UUID().uuidString
        let recipeFile = previewDirectory.appendingPathComponent(token+".json")
        let output = previewDirectory.appendingPathComponent(token+".png")
        do {
            try FileManager.default.createDirectory(at:previewDirectory,withIntermediateDirectories:true)
            try recipe.write(to:recipeFile)
            let task = Process(); task.executableURL = resources.appendingPathComponent("python/bin/python3")
            task.arguments = ["-s",resources.appendingPathComponent("backend/monochrome_preview.py").path,input.path,"-o",output.path,"--recipe",recipeFile.path,"--max-edge","2048","--cache-linear"]
            task.environment = workerEnvironment(); task.currentDirectoryURL = resources.appendingPathComponent("backend")
            let pipe = Pipe(); task.standardOutput = pipe; task.standardError = pipe
            try task.run(); previewTask = task
            DispatchQueue.global(qos:.userInitiated).async { [weak self] in
                let data = pipe.fileHandleForReading.readDataToEndOfFile(); task.waitUntilExit()
                let event = String(data:data,encoding:.utf8)?.split(separator:"\n").last.flatMap {
                    try? JSONSerialization.jsonObject(with:Data($0.utf8)) as? [String:Any]
                }
                // Decode off the UI thread, especially the on-demand native image.
                var decoded: NSImage?
                if task.terminationStatus == 0,
                   let source = CGImageSourceCreateWithURL(output as CFURL,nil),
                   let cg = CGImageSourceCreateImageAtIndex(source,0,[kCGImageSourceShouldCacheImmediately:true] as CFDictionary) {
                    decoded = previewBitmap(cg)
                }
                DispatchQueue.main.async {
                    ExecutionLogStore.shared.worker(String(data:data,encoding:.utf8) ?? "",context:"预览")
                    try? FileManager.default.removeItem(at:recipeFile)
                    guard let self else {
                        try? FileManager.default.removeItem(at:output.deletingLastPathComponent()); return
                    }
                    if self.previewTask === task { self.previewTask = nil }
                    guard self.previewTicket == ticket else { self.removePreviewFiles(output); return }
                    self.previewBusy = false
                    guard task.terminationStatus == 0, event?["state"] as? String == "ready", let decoded else {
                        self.removePreviewFiles(output)
                        self.previewMessage = (detail ? "原生细节加载失败：" : "无法生成单色模拟：") + (event?["message"] as? String ?? "请检查输入文件与设置")
                        self.inspectionPreviewFailed("当前模式的预览未完成")
                        return
                    }
                    if let old = self.previewCache[key] { self.removePreviewFiles(old) }
                    if let value=event?["raster_source"],let bytes=try? JSONSerialization.data(withJSONObject:value),
                       let raster=try? JSONDecoder().decode(PreviewRaster.self,from:bytes) {
                        self.previewRasters[key]=raster
                        self.previewRasterOrder.removeAll { $0==key };self.previewRasterOrder.append(key)
                        while self.previewRasterOrder.count>1 && (self.previewRasterOrder.count>6 || self.previewRasters.values.reduce(0,{ $0+$1.byteCount })>768*1024*1024) {
                            let old=self.previewRasterOrder.removeFirst();self.previewRasters.removeValue(forKey:old)?.remove()
                        }
                    }
                    self.previewCache[key] = output; self.touchPreview(key)
                    self.previewResolved[key] = event?["resolved_parameters"] as? [String:Any]
                    self.previewRecipes[key] = try? JSONDecoder().decode(RecipeDocument.self,from:recipe)
                    if let size = event?["native_size"] as? [Int],size.count == 2 {
                        self.previewSizes[key] = NSSize(width:size[1],height:size[0])
                    }
                    if let value = event?["histogram"],let bytes = try? JSONSerialization.data(withJSONObject:value),
                       let histogram = try? JSONDecoder().decode(PreviewHistogram.self,from:bytes),histogram.valid {
                        self.previewHistograms[key] = histogram
                    }
                    while self.previewOrder.count > 12 {
                        let old = self.previewOrder.removeFirst()
                        if let url = self.previewCache.removeValue(forKey:old) { self.removePreviewFiles(url) }
                        self.previewResolved[old] = nil;self.previewHistograms[old] = nil;self.previewSizes[old] = nil
                        self.previewRecipes[old] = nil
                        self.previewRasters.removeValue(forKey:old)?.remove();self.previewRasterOrder.removeAll { $0==old }
                    }
                    self.previewPixelSize = self.previewSizes[key] ?? .zero
                    self.applyResolvedParameters(self.previewResolved[key]);self.histogram = self.previewHistograms[key]
                    self.preview = decoded;self.previewMessage = self.monochromePreviewState()
                    self.previewShownKey=key;self.previewShownRecipe=self.previewRecipes[key]
                    if let applied=self.previewShownRecipe { self.commitInspectionPreview(key:key,applied:applied) }
                    self.loadVisibleDetail()
                }
            }
        } catch {
            try? FileManager.default.removeItem(at:recipeFile)
            removePreviewFiles(output);previewBusy = false;previewMessage = "无法生成单色模拟：\(error.localizedDescription)"
        }
    }
    func cleanupPreviews() {
        dismissInspectionLoupe()
        stopPreview()
        if previewTask?.isRunning != true { try? FileManager.default.removeItem(at:previewDirectory) }
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
