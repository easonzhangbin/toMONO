import SwiftUI

enum AppBrand {
    static let multilineTagline = "单色重建，让每一台数码相机，\n都能呈现 MONOCHROME 的影像魅力。"
    static let tagline = multilineTagline.replacingOccurrences(of:"\n",with:"")
    static var releaseLabel: String { Bundle.main.object(forInfoDictionaryKey:"ToMONOReleaseLabel") as? String ?? "toMONO" }
}

@MainActor extension AppModel {
    func startStartupCheck() {
        guard startupTask?.isRunning != true else { return }
        startupReady=false;startupError=nil
        let task=Process();task.executableURL=resources.appendingPathComponent("python/bin/python3")
        task.arguments=["-s","-c","import json,rawpy,conversion_service,lens_correction,channel_response,pure_narrowband,detail_reconstruction,lmmse_reconstruction,ctypes; core=channel_response.native_core(); pure_narrowband.native_core(); detail_reconstruction._library(); lmmse_reconstruction._library(); print(json.dumps({'libraw':list(rawpy.libraw_version),'lens_profiles':len(lens_correction.database().lenses),'detail_modes':list(detail_reconstruction.METHODS)+list(lmmse_reconstruction.METHODS)}))"]
        task.currentDirectoryURL=resources.appendingPathComponent("backend");task.environment=workerEnvironment()
        let pipe=Pipe();task.standardOutput=pipe;task.standardError=pipe
        do {
            try task.run();startupTask=task
            DispatchQueue.global(qos:.userInitiated).async { [weak self] in
                let bytes=pipe.fileHandleForReading.readDataToEndOfFile();task.waitUntilExit()
                DispatchQueue.main.async {
                    guard let self else { return }
                    if self.startupTask === task { self.startupTask=nil }
                    let output=String(data:bytes,encoding:.utf8) ?? ""
                    ExecutionLogStore.shared.worker(output,context:"启动检查")
                    if task.terminationStatus == 0 {
                        self.startupReady=true;ExecutionLogStore.shared.record("startup_ready");self.updatePreview()
                    } else {
                        self.startupError="转换引擎未能完成检查，请查看执行日志或重新安装完整的软件包。"
                        ExecutionLogStore.shared.record("startup_failed",level:"error",fields:["exit_code":task.terminationStatus])
                    }
                }
            }
        } catch { startupError="无法启动转换引擎："+error.localizedDescription }
    }
    func stopStartup() { if startupTask?.isRunning == true { startupTask?.interrupt() } }
}
