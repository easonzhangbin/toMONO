import SwiftUI
import AppKit
import Darwin

private enum NativeExceptionRecorder {
    private static let lock = NSLock()
    private static var path = ""
    static func install(_ url: URL) {
        lock.lock(); path = url.path; lock.unlock()
        NSSetUncaughtExceptionHandler { exception in NativeExceptionRecorder.record(exception) }
    }
    static func record(_ exception: NSException) {
            lock.lock(); let destination = path; lock.unlock()
            let row: [String: Any] = ["time": ISO8601DateFormatter().string(from: Date()), "level": "error",
                "stage": "uncaught_native_exception", "name": exception.name.rawValue,
                "message": exception.reason ?? "", "stack": exception.callStackSymbols]
            guard var data = try? JSONSerialization.data(withJSONObject: row), !destination.isEmpty else { return }
            data.append(10)
            let fd = Darwin.open(destination, O_WRONLY | O_CREAT | O_APPEND, mode_t(0o600))
            if fd >= 0 { _ = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress, $0.count) }; Darwin.close(fd) }
    }
}

@MainActor final class ExecutionLogStore: ObservableObject {
    static let shared = ExecutionLogStore()
    let directory: URL
    let file: URL
    @Published var text = ""
    @Published var notice: String?
    private var lastReadSize: UInt64 = 0
    private init() {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        directory = base.appendingPathComponent("toMONO/Logs", isDirectory: true)
        let formatter = DateFormatter(); formatter.dateFormat = "yyyyMMdd-HHmmss"
        file = directory.appendingPathComponent("toMONO-\(formatter.string(from: Date()))-\(UUID().uuidString.prefix(8)).jsonl")
        NativeExceptionRecorder.install(file)
        record("session_started", fields: ["release_label": AppBrand.releaseLabel, "app_version": Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "development", "system": ProcessInfo.processInfo.operatingSystemVersionString, "bundle_path":Bundle.main.bundleURL.path])
    }
    func record(_ stage: String, level: String = "info", fields: [String: Any] = [:]) {
        do {
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            let formatter = ISO8601DateFormatter(); formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            let row: [String: Any] = ["time": formatter.string(from: Date()), "pid": ProcessInfo.processInfo.processIdentifier, "level": level, "stage": stage, "details": fields]
            var data = try JSONSerialization.data(withJSONObject: row, options: [.sortedKeys, .fragmentsAllowed]); data.append(10)
            let fd = Darwin.open(file.path, O_WRONLY | O_CREAT | O_APPEND, mode_t(0o600))
            guard fd >= 0 else { throw NSError(domain: NSPOSIXErrorDomain, code: Int(errno)) }
            defer { Darwin.close(fd) }
            let written = data.withUnsafeBytes { Darwin.write(fd, $0.baseAddress, $0.count) }
            if written != data.count { throw NSError(domain: "日志写入未完成", code: 1) }
        } catch { notice = "无法写入执行日志：\(error.localizedDescription)" }
    }
    func worker(_ output: String, context: String) {
        guard !output.isEmpty else { return }
        record("worker_output", fields: ["context": context, "output": output])
    }
    func refresh() {
        guard let stream = try? FileHandle(forReadingFrom: file) else { return }
        defer { try? stream.close() }
        do {
            let size = try stream.seekToEnd(); let limit: UInt64 = 2_000_000
            if size == lastReadSize { return }
            lastReadSize = size
            try stream.seek(toOffset: size > limit ? size - limit : 0)
            var bytes = try stream.readToEnd() ?? Data()
            if size > limit, let end = bytes.firstIndex(of: 10) { bytes.removeSubrange(...end) }
            let raw = String(decoding: bytes, as: UTF8.self)
            let lines = raw.split(separator: "\n").suffix(1200).map { line -> String in
                guard let row = try? JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any] else { return String(line) }
                let time = row["time"] as? String ?? ""
                let level = (row["level"] as? String ?? "info").uppercased()
                let stage = row["stage"] as? String ?? ""
                var detail = row; detail["time"] = nil; detail["level"] = nil; detail["stage"] = nil
                let pretty = (try? JSONSerialization.data(withJSONObject: detail, options: [.prettyPrinted, .sortedKeys])).flatMap { String(data: $0, encoding: .utf8) } ?? String(line)
                return "\(time)  [\(level)]  \(stage)\n\(pretty)\n"
            }
            let updated = lines.joined(separator: "\n")
            if updated != text { text = updated }
        } catch { notice = "无法读取执行日志：\(error.localizedDescription)" }
    }
    func export() {
        refresh()
        let panel = NSSavePanel(); panel.title = "导出执行日志"; panel.prompt = "导出"
        panel.nameFieldStringValue = file.lastPathComponent
        guard panel.runModal() == .OK, let url = panel.url else { return }
        let scoped = url.startAccessingSecurityScopedResource(); defer { if scoped { url.stopAccessingSecurityScopedResource() } }
        guard url.standardizedFileURL != file.standardizedFileURL else { notice = "请选择其他位置，不能覆盖当前日志"; return }
        do { try Data(contentsOf: file).write(to: url, options: .atomic) }
        catch { notice = "导出日志失败：\(error.localizedDescription)" }
    }
}

struct ExecutionLogView: View {
    @ObservedObject private var store = ExecutionLogStore.shared
    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 5) {
                    Text("执行日志").font(.title2.weight(.semibold))
                    Text("记录导入、预览、参数、处理阶段、保存结果和完整错误；仅保存在本机。").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("刷新", action: store.refresh)
                Button("导出日志", action: store.export)
                Button("打开日志文件夹") { NSWorkspace.shared.open(store.directory) }
            }.padding(16)
            Divider()
            ScrollView {
                Text(store.text.isEmpty ? "暂无日志" : store.text).font(.system(size: 11, design: .monospaced))
                    .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading).padding(16)
            }
            Divider()
            Text(store.file.path).font(.caption).foregroundStyle(.secondary).textSelection(.enabled).padding(12)
        }.frame(minWidth: 820, minHeight: 560)
            .onAppear(perform: store.refresh)
            .onReceive(Timer.publish(every: 1, on: .main, in: .common).autoconnect()) { _ in store.refresh() }
            .alert("日志提示", isPresented: Binding(get: { store.notice != nil }, set: { if !$0 { store.notice = nil } })) {
                Button("好") { store.notice = nil }
            } message: { Text(store.notice ?? "") }
    }
}
