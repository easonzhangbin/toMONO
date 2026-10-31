import SwiftUI
import AppKit
import UniformTypeIdentifiers
import ImageIO

struct CameraIdentity: Codable, Equatable {
    var make: String
    var model: String
    var serial: String?
    var displayName: String { model.lowercased().hasPrefix(make.lowercased()) ? model : "\(make) \(model)" }
    func differs(from other: CameraIdentity) -> Bool {
        make.caseInsensitiveCompare(other.make) != .orderedSame || model.caseInsensitiveCompare(other.model) != .orderedSame ||
        (serial != nil && serial != other.serial)
    }
}
struct DefectProfile: Codable, Equatable {
    var version: Int
    var make: String
    var model: String
    var sensor_size: [Int]
    var pixels: [[Int]]
    var valid: Bool {
        version == 1 && !make.isEmpty && !model.isEmpty && sensor_size.count == 2 &&
        sensor_size.allSatisfy { (8...100000).contains($0) } && (1...1000000).contains(pixels.count) &&
        pixels.allSatisfy { $0.count == 2 && $0[0] >= 0 && $0[1] >= 0 && $0[0] < sensor_size[0] && $0[1] < sensor_size[1] }
    }
}
struct RecipeDocument: Codable, Equatable {
    var version = 2
    var detail_mode = "spectral"
    var algorithm = "Bicubic"
    var green_mode = "auto"
    var compensation = 1.231
    var focus_red = true
    var focus_blue = false
    var preview_gamma = 2.2
    var match_preview = true
    var preserve_capture = true
    var preserve_description = true
    var defect_profile: DefectProfile? = nil
    var camera_identity: CameraIdentity? = nil
    var lens_correction: LensCorrectionSettings? = nil
    var response_mode = "green"
    var response_red = 0.25
    var response_green = 0.5
    var response_blue = 0.25
    var response_exposure = 0.0
    var narrow_interpolation = "cubic"
    var usesLegacyDetail: Bool { detail_mode == "legacy" }
    var detailModeValid: Bool { ["spectral","spectral_guard","directional","legacy"].contains(detail_mode) }
    static func detailTitle(_ mode: String) -> String {
        ["spectral":"频域精细","spectral_guard":"频域限幅","directional":"方向自适应","legacy":"原有模式（旧预设）"][mode] ?? "其他采样重建"
    }
    var detailModeTitle: String { Self.detailTitle(detail_mode) }
    var detailModeDescription: String {
        switch detail_mode {
        case "spectral": return "优先保留细密织纹与细线；高反差边缘可能振铃，暗部噪声也可能更明显。"
        case "spectral_guard": return "在频域重建后限制局部极值，减少过冲；部分纹理可能产生格点偏差。"
        case "directional": return "按局部方向可靠性补齐绿色采样；红蓝使用同色三次，周期织纹仍可能退化。"
        default: return "保留旧设置中的绿色插值或窄带同色插值，用于重现之前的结果。"
        }
    }
    var greenReferenceRecipe: RecipeDocument {
        var result = self
        result.response_mode = "green"
        result.response_exposure = 0
        result.detail_mode = "legacy"
        return result
    }
    var isNarrowband: Bool { response_mode.hasPrefix("narrow_") }
    var narrowChannel: String? { ["narrow_red":"R","narrow_green":"G","narrow_blue":"B"][response_mode] }
    var responseValid: Bool {
        detailModeValid && ["green","mix","narrow_red","narrow_green","narrow_blue"].contains(response_mode) &&
        ["cubic","linear"].contains(narrow_interpolation) &&
        [response_red,response_green,response_blue].allSatisfy { $0.isFinite && (0...1).contains($0) } &&
        response_exposure.isFinite && (-6...6).contains(response_exposure) &&
        (response_mode != "mix" || response_red+response_green+response_blue>0)
    }
    var usesGreen: Bool { response_mode == "green" || (response_mode == "mix" && response_green>0) }
    enum CodingKeys: String, CodingKey { case version,detail_mode,algorithm,green_mode,compensation,focus_red,focus_blue,preview_gamma,match_preview,preserve_capture,preserve_description,defect_profile,camera_identity,lens_correction,response_mode,response_red,response_green,response_blue,response_exposure,narrow_interpolation }
    init() {}
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let sourceVersion = try c.decodeIfPresent(Int.self,forKey:.version) ?? 1
        guard [1,2].contains(sourceVersion) else {
            throw DecodingError.dataCorruptedError(forKey:.version,in:c,debugDescription:"不支持此设置预设版本")
        }
        version = 2
        detail_mode = try c.decodeIfPresent(String.self,forKey:.detail_mode) ?? (sourceVersion == 1 ? "legacy" : "spectral")
        algorithm = try c.decodeIfPresent(String.self,forKey:.algorithm) ?? "Bicubic"
        green_mode = try c.decodeIfPresent(String.self,forKey:.green_mode) ?? "auto"
        compensation = try c.decodeIfPresent(Double.self,forKey:.compensation) ?? 1.231
        focus_red = try c.decodeIfPresent(Bool.self,forKey:.focus_red) ?? true
        focus_blue = try c.decodeIfPresent(Bool.self,forKey:.focus_blue) ?? false
        preview_gamma = try c.decodeIfPresent(Double.self,forKey:.preview_gamma) ?? 2.2
        match_preview = try c.decodeIfPresent(Bool.self,forKey:.match_preview) ?? true
        preserve_capture = try c.decodeIfPresent(Bool.self,forKey:.preserve_capture) ?? true
        preserve_description = try c.decodeIfPresent(Bool.self,forKey:.preserve_description) ?? true
        defect_profile = try c.decodeIfPresent(DefectProfile.self,forKey:.defect_profile)
        camera_identity = try c.decodeIfPresent(CameraIdentity.self,forKey:.camera_identity)
        lens_correction = try c.decodeIfPresent(LensCorrectionSettings.self,forKey:.lens_correction)
        response_mode = try c.decodeIfPresent(String.self,forKey:.response_mode) ?? "green"
        response_red = try c.decodeIfPresent(Double.self,forKey:.response_red) ?? 0.25
        response_green = try c.decodeIfPresent(Double.self,forKey:.response_green) ?? 0.5
        response_blue = try c.decodeIfPresent(Double.self,forKey:.response_blue) ?? 0.25
        response_exposure = try c.decodeIfPresent(Double.self,forKey:.response_exposure) ?? 0
        narrow_interpolation = try c.decodeIfPresent(String.self,forKey:.narrow_interpolation) ?? "cubic"
    }
}
struct InputItem: Identifiable {
    let id = UUID()
    var url: URL
    var settings = RecipeDocument()
    var presetSnapshot: RecipeDocument? = nil
    var presetMessage = "默认设置 · 可直接转换，无需保存预设"
    var camera: CameraIdentity? = nil
    var cameraChecked = false
    var lensCapture: LensCaptureInfo? = nil
    var thumbnail: NSImage? = nil
    var status = "待处理"
    var detail = ""
    var output: URL? = nil
    var outputRecipe: RecipeDocument? = nil
    var displayStatus:String {
        if status.hasPrefix("已保存") { return output != nil && outputRecipe != settings ? "已修改" : "已保存" }
        return status
    }
    var displayDetail:String { displayStatus == "已修改" ? "当前照片设置尚未导出；上次保存的结果仍保留。" : detail }
}

@MainActor final class AppModel: ObservableObject {
    @Published var startupReady = false
    @Published var startupError: String?
    var startupTask: Process?
    @Published var items: [InputItem] = []
    @Published var selection: UUID? { didSet { if selection != oldValue { activateSelection() } } }
    @Published var selectedIDs: Set<UUID> = []
    @Published var recipe = RecipeDocument() { didSet { persistCurrentSettings() } }
    @Published var folder: URL?
    @Published var running = false
    @Published var fraction = 0.0
    @Published var phase = "添加 RAW 文件，或拖放到窗口中"
    @Published var preview: NSImage?
    @Published var previewBusy = false
    @Published var previewMessage = ""
    @Published var reconstructionSummary = "自动识别传感器布局"
    @Published var greenCorrectionSummary = "生成模拟后显示实际校正数量"
    @Published var histogram: PreviewHistogram?
    @Published var rawHistogram: RawSourceHistogram?
    @Published var responseSummary = "绿色响应 · 频域精细"
    @Published var showingSource = false
    @Published var showingReference = false
    @Published var brightness = 0.0
    @Published var notice: String?
    let lensCatalog = LensCatalog.load()
    @Published var lensCorrectionSummary = "按当前设置生成模拟后显示处理结果"
    @Published var presetMessage = "默认设置 · 可直接转换，无需保存预设" { didSet { persistPresetInfo() } }
    private var presetSnapshot: RecipeDocument? { didSet { persistPresetInfo() } }
    private var restoringSettings = false
    private var importDefaults = RecipeDocument()
    private var process: Process?
    private var pending: [UUID] = []
    private var cameraTasks: Set<UUID> = []
    private var thumbnailTasks: Set<UUID> = []
    private var active: UUID?
    private var cancelRequested = false
    private var jobRecipe = RecipeDocument()
    private var jobRecipes: [UUID:RecipeDocument] = [:]
    private var recipeFile: URL?
    private var scopedResources: [URL] = []
    var previewTask: Process?
    var previewWork: DispatchWorkItem?
    var previewTicket = UUID()
    var previewInput: UUID?
    var previewCache: [String: URL] = [:]
    var previewResolved: [String: [String: Any]] = [:]
    var previewHistograms: [String: PreviewHistogram] = [:]
    let previewDirectory = FileManager.default.temporaryDirectory.appendingPathComponent("toMONO-previews-\(UUID().uuidString)", isDirectory: true)
    var selected: InputItem? { items.first { $0.id == selection } }
    var selectedCount: Int { items.filter { selectedIDs.contains($0.id) }.count }
    var resources: URL { Bundle.main.resourceURL! }

    init() { AppLifecycle.models.add(self); ExecutionLogStore.shared.record("workspace_created"); startStartupCheck() }

    private func persistCurrentSettings() {
        guard !restoringSettings else { return }
        if let index=items.firstIndex(where: { $0.id==selection }) { items[index].settings=recipe }
        else if items.isEmpty { importDefaults=recipe }
    }
    private func persistPresetInfo() {
        guard !restoringSettings,let index=items.firstIndex(where: { $0.id==selection }) else { return }
        items[index].presetSnapshot=presetSnapshot;items[index].presetMessage=presetMessage
    }
    private func activateSelection() {
        restoringSettings=true
        if let item=selected {
            recipe=item.settings;presetSnapshot=item.presetSnapshot;presetMessage=item.presetMessage
            ExecutionLogStore.shared.record("photo_settings_activated",fields:["input":item.url.path,"response_mode":recipe.response_mode,"response_exposure":recipe.response_exposure,"detail_mode":recipe.detail_mode])
        } else { recipe=importDefaults;presetSnapshot=nil;presetMessage="请选择照片后调整" }
        showingReference=false;showingSource=false
        restoringSettings=false
    }
    func copyCurrentResponse(all:Bool) {
        guard !running,selected != nil,recipe.responseValid else { return }
        let ids=Set(exportIDs(all:all));let current=recipe
        for index in items.indices where ids.contains(items[index].id) {
            items[index].settings.response_mode=current.response_mode
            items[index].settings.response_red=current.response_red;items[index].settings.response_green=current.response_green
            items[index].settings.response_blue=current.response_blue;items[index].settings.response_exposure=current.response_exposure
            items[index].settings.narrow_interpolation=current.narrow_interpolation
        }
        phase="已将当前响应同步到 \(ids.count) 张照片"
        ExecutionLogStore.shared.record("response_explicitly_copied",fields:["count":ids.count,"scope":all ? "all" : "selected","response_mode":current.response_mode,"response_exposure":current.response_exposure])
    }

    private func retainAccess(to url: URL) {
        guard !scopedResources.contains(where: { $0.path == url.path }) else { return }
        if url.startAccessingSecurityScopedResource() { scopedResources.append(url) }
    }
    private func releaseAccess(to url: URL) {
        if let i = scopedResources.firstIndex(where: { $0.path == url.path }) {
            scopedResources.remove(at: i).stopAccessingSecurityScopedResource()
        }
    }
    deinit {
        if startupTask?.isRunning == true { startupTask?.interrupt() }
        previewWork?.cancel(); if previewTask?.isRunning == true { previewTask?.interrupt() }
        for url in scopedResources { url.stopAccessingSecurityScopedResource() }
        if previewTask?.isRunning != true { try? FileManager.default.removeItem(at:previewDirectory) }
    }

    func add(_ urls: [URL]) {
        var added: Set<UUID> = []
        for url in urls where url.isFileURL {
            if (try? url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true { continue }
            if !items.contains(where: { $0.url.standardizedFileURL == url.standardizedFileURL }) {
                ExecutionLogStore.shared.record("input_added", fields: ["input": url.path])
                retainAccess(to: url)
                let item = InputItem(url: url,settings:importDefaults); items.append(item); added.insert(item.id)
            }
        }
        if let first = items.first(where: { added.contains($0.id) }) { setSelection([first.id]) }
        if items.isEmpty { notice = "请选择 RAW 文件。载入后由 LibRaw 检查文件并生成单色模拟。" }
        else { phase = "已添加 \(items.count) 张照片"; updatePreview() }
    }
    func setSelection(_ ids: Set<UUID>) {
        let valid = ids.intersection(Set(items.map(\.id)))
        let newlySelected = valid.subtracting(selectedIDs)
        selectedIDs = valid
        if let newest = items.first(where: { newlySelected.contains($0.id) }) { selection = newest.id }
        else if selection == nil || !valid.contains(selection!) { selection = items.first(where: { valid.contains($0.id) })?.id }
        updatePreview()
    }
    func loadQueueThumbnail(_ id: UUID) {
        guard let item = items.first(where: { $0.id == id }),item.thumbnail == nil,!thumbnailTasks.contains(id) else { return }
        thumbnailTasks.insert(id)
        let url = item.url
        DispatchQueue.global(qos:.utility).async { [weak self] in
            var image: NSImage?
            if let source = CGImageSourceCreateWithURL(url as CFURL,nil),let cg = CGImageSourceCreateThumbnailAtIndex(source,0,[kCGImageSourceCreateThumbnailFromImageAlways:true,kCGImageSourceThumbnailMaxPixelSize:96,kCGImageSourceCreateThumbnailWithTransform:true] as CFDictionary) {
                image = NSImage(cgImage:cg,size:NSSize(width:cg.width,height:cg.height))
            }
            DispatchQueue.main.async {
                guard let self else { return }; self.thumbnailTasks.remove(id)
                if let index = self.items.firstIndex(where: { $0.id == id }) { self.items[index].thumbnail = image }
            }
        }
    }
    func chooseFiles() {
        let p = NSOpenPanel(); p.title = "添加 RAW 原图"; p.prompt = "添加"
        p.allowsMultipleSelection = true; p.canChooseDirectories = false
        // Let LibRaw identify bytes; the system UTI list may omit valid vendor RAWs.
        p.allowsOtherFileTypes = true
        ExecutionLogStore.shared.record("file_picker_opened")
        if p.runModal() == .OK {
            ExecutionLogStore.shared.record("file_picker_selected",fields:["files":p.urls.map(\.path)])
            add(p.urls)
        }
    }
    func chooseFolder() {
        let p = NSOpenPanel(); p.title = "选择单色DNG保存位置"; p.prompt = "选择文件夹"
        p.canChooseDirectories = true; p.canChooseFiles = false; p.canCreateDirectories = true
        if p.runModal() == .OK, let url = p.url {
            if let previous = folder, previous != url { releaseAccess(to: previous) }
            retainAccess(to: url); folder = url
            ExecutionLogStore.shared.record("output_folder_selected", fields: ["folder": url.path])
        }
    }
    func loadRecipe() {
        let p = NSOpenPanel(); p.title = "载入相机设置预设"; p.prompt = "载入"; p.allowedContentTypes = [.json]
        guard p.runModal() == .OK, let url = p.url else { return }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: url)
            let keys = Set(["version","detail_mode","algorithm","green_mode","compensation","focus_red","focus_blue","preview_gamma","match_preview","preserve_capture","preserve_description","defect_profile","camera_identity","lens_correction","response_mode","response_red","response_green","response_blue","response_exposure","narrow_interpolation"])
            guard let raw = try JSONSerialization.jsonObject(with: data) as? [String: Any], Set(raw.keys).isSubset(of: keys) else { throw NSError(domain: "设置预设包含未知字段", code: 1) }
            let value = try JSONDecoder().decode(RecipeDocument.self, from: data)
            guard value.responseValid, value.version == 2, ["Bicubic","EdgeAware","Auto"].contains(value.algorithm), value.defect_profile?.valid != false, ["auto","manual","off"].contains(value.green_mode), value.compensation.isFinite, (0...1.255).contains(value.compensation), (1...3).contains(value.preview_gamma) else { throw NSError(domain: "设置预设版本或参数不受支持", code: 1) }
            if let origin = value.camera_identity, let current = selected?.camera, origin.differs(from:current), value.defect_profile != nil {
                throw NSError(domain:"预设坏点坐标来自另一机身，请先使用不含坏点表的设置",code:1)
            }
            recipe = value; phase = "已载入设置预设：\(url.lastPathComponent)"
            presetMessage = "已载入：\(url.deletingPathExtension().lastPathComponent)" + (value.camera_identity == nil ? " · 未记录来源机身" : "")
            presetSnapshot = value
            ExecutionLogStore.shared.record("recipe_loaded", fields: ["path": url.path,"detail_mode":value.detail_mode])
        } catch { notice = "无法载入设置预设：\(error.localizedDescription)" }
    }
    var presetStatus: String {
        guard let snapshot = presetSnapshot else { return recipe == RecipeDocument() ? "默认设置 · 可直接转换，无需保存预设" : "自定义设置 · 尚未保存为预设" }
        return presetMessage + (recipe == snapshot ? "" : "\n设置已更改，尚未保存到预设")
    }
    func restoreDefaultSettings() {
        recipe = RecipeDocument(); presetSnapshot = nil
        presetMessage = "默认设置 · 可直接转换，无需保存预设"
    }
    var suggestedPresetName: String {
        guard let camera = selected?.camera ?? recipe.camera_identity else { return "通用单色设置.json" }
        let serial = camera.serial.map { "_机身" + $0 } ?? ""
        let text = camera.displayName + serial + "_单色设置"
        let clean = text.components(separatedBy:CharacterSet(charactersIn:"/\\:\n\r")).joined(separator:"_")
        return String(clean.prefix(180)) + ".json"
    }
    var presetScopeWarning: String? {
        guard let origin = recipe.camera_identity,let camera = selected?.camera,origin.differs(from:camera) else { return nil }
        return recipe.defect_profile == nil ? "预设来自另一机身；普通转换参数可用。" : "坏点表的机身来源不匹配，请关闭坏点修复。"
    }
    func identifyCamera(for id: UUID) {
        guard let item = items.first(where: { $0.id == id }), !item.cameraChecked, !cameraTasks.contains(id) else { return }
        cameraTasks.insert(id)
        let task = Process(); task.executableURL = URL(fileURLWithPath:"/usr/bin/perl")
        task.arguments = [resources.appendingPathComponent("exiftool/exiftool").path,"-config","","-n","-j","-Make","-Model","-BodySerialNumber","-CameraSerialNumber","-SerialNumber","-LensModel","-LensID","-FocalLength","-FNumber","-ScaleFactor35efl",item.url.path]
        let pipe = Pipe(); task.standardOutput = pipe; task.standardError = Pipe()
        do {
            try task.run()
            DispatchQueue.global(qos:.userInitiated).async { [weak self] in
                let bytes = pipe.fileHandleForReading.readDataToEndOfFile();task.waitUntilExit()
                let row = (try? JSONSerialization.jsonObject(with:bytes) as? [[String:Any]])?.first
                var identity: CameraIdentity?
                if let make = row?["Make"] as? String,let model = row?["Model"] as? String,!make.isEmpty,!model.isEmpty {
                    let serial = ["BodySerialNumber","CameraSerialNumber","SerialNumber"].compactMap { row?[$0] }.map { String(describing:$0).trimmingCharacters(in:.whitespacesAndNewlines) }.first { !$0.isEmpty && Set($0) != Set("0") }
                    identity = CameraIdentity(make:make,model:model,serial:serial)
                }
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.cameraTasks.remove(id)
                    guard let index = self.items.firstIndex(where: { $0.id == id }) else { return }
                    self.items[index].camera = identity; self.items[index].cameraChecked = true
                    self.items[index].lensCapture=LensCaptureInfo(model:row?["LensModel"] as? String ?? row?["LensID"] as? String,focal:(row?["FocalLength"] as? NSNumber)?.doubleValue,aperture:(row?["FNumber"] as? NSNumber)?.doubleValue,cropFactor:(row?["ScaleFactor35efl"] as? NSNumber)?.doubleValue)
                }
            }
        } catch { cameraTasks.remove(id); if let index = items.firstIndex(where: { $0.id == id }) { items[index].cameraChecked = true } }
    }
    func loadDefectProfile() {
        let p = NSOpenPanel(); p.title = "载入传感器缺陷图"; p.allowedContentTypes = [.json]
        guard p.runModal() == .OK, let url = p.url else { return }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            let value = try JSONDecoder().decode(DefectProfile.self, from:Data(contentsOf:url))
            guard value.valid else { throw NSError(domain:"缺陷图字段或坐标无效",code:1) }
            recipe.defect_profile = value
            ExecutionLogStore.shared.record("defect_profile_loaded",fields:["model":value.model,"pixels":value.pixels.count])
        } catch { notice = "无法载入缺陷图：\(error.localizedDescription)" }
    }
    func saveRecipe() {
        let p = NSSavePanel(); p.title = "保存相机设置预设"; p.prompt = "保存"; p.nameFieldStringValue = suggestedPresetName; p.allowedContentTypes = [.json]
        guard p.runModal() == .OK, let url = p.url else { return }
        let scoped = url.startAccessingSecurityScopedResource()
        defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        do {
            var document = recipe
            document.camera_identity = selected?.camera ?? recipe.camera_identity
            let encoder = JSONEncoder(); encoder.outputFormatting = [.prettyPrinted,.sortedKeys]
            try encoder.encode(document).write(to:url,options:.atomic)
            recipe = document; presetSnapshot = document
            phase = "相机设置预设已保存"
            presetMessage = "已保存：\(url.deletingPathExtension().lastPathComponent)"
        }
        catch { notice = "保存设置预设失败：\(error.localizedDescription)" }
    }
    func uniqueOutput(for url: URL, settings: RecipeDocument? = nil) -> URL {
        let suffix = (settings ?? recipe).narrowChannel.map { "_" + $0 + "_窄带" } ?? "_单色"
        let base = url.deletingPathExtension().lastPathComponent + suffix
        var n = 1
        var result = folder!.appendingPathComponent(base + ".dng")
        while FileManager.default.fileExists(atPath: result.path) || FileManager.default.fileExists(atPath: result.deletingPathExtension().appendingPathExtension("processing.json").path) {
            n += 1; result = folder!.appendingPathComponent(base + "_\(n).dng")
        }
        return result
    }
    func start() { startExport(all: false) }
    func startAll() { startExport(all: true) }
    func exportIDs(all: Bool) -> [UUID] { items.filter { all || selectedIDs.contains($0.id) }.map(\.id) }
    private func startExport(all: Bool) {
        let ids = exportIDs(all: all)
        guard !running, !ids.isEmpty else { return }
        guard startupReady else { notice = startupError ?? "转换引擎正在检查，请稍后再导出。"; return }
        if let bad=items.first(where: { ids.contains($0.id) && !$0.settings.responseValid }) {
            notice="\(bad.url.lastPathComponent) 的响应参数无效：RGB至少保留一个大于零的比例，曝光限于±6EV";return
        }
        if folder == nil { chooseFolder() }
        guard folder != nil else { phase = "请选择保存位置后开始转换"; return }
        stopPreview(); pending = ids;jobRecipes=Dictionary(uniqueKeysWithValues:items.filter { ids.contains($0.id) }.map { ($0.id,$0.settings) }); cancelRequested = false; running = true
        ExecutionLogStore.shared.record("queue_started", fields: ["count": ids.count,"scope": all ? "all" : "selected","inputs":items.filter { ids.contains($0.id) }.map { $0.url.path }])
        startNext()
    }
    private func startNext() {
        guard !cancelRequested, !pending.isEmpty else {
            running = false; process = nil; active = nil; fraction = 0;jobRecipes=[:]
            phase = cancelRequested ? "已取消，已保存的文件会保留" : "队列处理完成"
            ExecutionLogStore.shared.record("queue_finished", fields: ["cancelled": cancelRequested])
            updatePreview()
            return
        }
        let id = pending.removeFirst(); active = id
        guard let index = items.firstIndex(where: { $0.id == id }) else { startNext(); return }
        jobRecipe=jobRecipes[id] ?? items[index].settings
        let input = items[index].url; let output = uniqueOutput(for: input, settings: jobRecipe)
        ExecutionLogStore.shared.record("conversion_started", fields: ["input": input.path, "output": output.path])
        items[index].status = "处理中"; items[index].detail = ""; items[index].output = nil; items[index].outputRecipe = nil; updatePreview(); fraction = 0; phase = "准备处理 \(input.lastPathComponent)"
        let temp = FileManager.default.temporaryDirectory.appendingPathComponent("tomono-recipe-\(UUID().uuidString).json")
        recipeFile = temp
        do {
            try JSONEncoder().encode(jobRecipe).write(to: temp)
            let p = Process(); p.executableURL = resources.appendingPathComponent("python/bin/python3")
            p.arguments = ["-s", resources.appendingPathComponent("backend/tomono_cli.py").path, input.path, "-o", output.path, "--recipe", temp.path, "--json"]
            p.environment = workerEnvironment(); p.currentDirectoryURL = resources.appendingPathComponent("backend")
            let pipe = Pipe(); p.standardOutput = pipe; p.standardError = pipe
            try p.run(); process = p
            DispatchQueue.global(qos: .userInitiated).async { [weak self] in
                var buffer = Data()
                while true {
                    let data = pipe.fileHandleForReading.availableData
                    if data.isEmpty { break }
                    buffer.append(data)
                    while let range = buffer.range(of: Data([10])) {
                        let line = String(data: buffer.subdata(in: 0..<range.lowerBound), encoding: .utf8) ?? ""
                        buffer.removeSubrange(0..<range.upperBound)
                        DispatchQueue.main.async { self?.consume(line, id: id) }
                    }
                }
                if !buffer.isEmpty {
                    let line = String(data: buffer, encoding: .utf8) ?? ""
                    DispatchQueue.main.async { self?.consume(line, id: id) }
                }
                p.waitUntilExit(); let code = p.terminationStatus
                DispatchQueue.main.async {
                    try? FileManager.default.removeItem(at: temp)
                    self?.finish(id: id, code: code)
                }
            }
        } catch {
            try? FileManager.default.removeItem(at: temp)
            items[index].status = "失败"; items[index].detail = "无法启动转换：\(error.localizedDescription)"; startNext()
        }
    }
    private func consume(_ line: String, id: UUID) {
        ExecutionLogStore.shared.worker(line, context: "导出")
        guard let data = line.data(using: .utf8), let event = try? JSONSerialization.jsonObject(with: data) as? [String: Any], let i = items.firstIndex(where: { $0.id == id }) else { return }
        if event["type"] as? String == "progress" {
            fraction = event["progress"] as? Double ?? fraction; phase = event["phase"] as? String ?? phase
        } else if event["type"] as? String == "result" {
            if selection==id { applyResolvedParameters(event["resolved_parameters"] as? [String: Any]) }
            switch event["state"] as? String {
            case "saved", "saved_with_warning":
                items[i].status = "已保存"
                if let path = event["output"] as? String { items[i].output = URL(fileURLWithPath: path) }
                items[i].outputRecipe = jobRecipes[id] ?? jobRecipe
                items[i].detail = (event["warnings"] as? [String] ?? []).joined(separator: "\n")
                if items[i].detail.isEmpty { items[i].detail = "像素回读与文件结构检查通过" }
                if selection==id { showingSource = false; showingReference = false; updatePreview() }
            case "cancelled": items[i].status = "已取消"
            default: items[i].status = "失败"; items[i].detail = event["message"] as? String ?? "转换失败"
            }
        }
    }
    private func finish(id: UUID, code: Int32) {
        if let i = items.firstIndex(where: { $0.id == id }), items[i].status == "处理中" {
            items[i].status = (cancelRequested || code == 130) ? "已取消" : "失败"
            items[i].detail = "转换进程已退出（\(code)）"
        }
        process = nil; startNext()
    }
    func cancel() { ExecutionLogStore.shared.record("cancel_requested"); cancelRequested = true; phase = "正在取消，等待当前步骤结束……"; process?.interrupt() }
    func reveal() { if let url = selected?.output { NSWorkspace.shared.activateFileViewerSelecting([url]) } }
    func removeSelected() {
        guard !running, !selectedIDs.isEmpty else { return }
        for item in items where selectedIDs.contains(item.id) { releaseAccess(to: item.url) }
        items.removeAll { selectedIDs.contains($0.id) }
        setSelection(items.first.map { [$0.id] } ?? [])
    }
}

