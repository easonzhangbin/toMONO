import AppKit
import SwiftUI

/// Opt-in integration harness. Its runner copies samples into a temporary QA
/// tree; exports never target the supplied original files or their directories.
@main struct PreviewWorkflowCheck: App {
    @StateObject private var model = AppModel()
    @State private var started = false
    var body: some Scene {
        Window("toMONO 1.1 验证",id:"workspace") {
            ContentView(model:model).onAppear {
                guard !started else { return }; started=true
                Task { @MainActor in await verify() }
            }
        }.defaultSize(width:1440,height:980)
    }
    @MainActor func verify() async {
        let root = URL(fileURLWithPath:ProcessInfo.processInfo.environment["TOMONO_QA_DIR"]!)
        var results:[String:Any] = [:]
        func require(_ condition:Bool,_ message:String) throws {
            if !condition { throw NSError(domain:message,code:1) }
        }
        func wait(_ condition:() -> Bool) async throws {
            let start=Date()
            while !condition() {
                if Date().timeIntervalSince(start)>180 { throw NSError(domain:"等待超时："+model.previewMessage,code:1) }
                try await Task.sleep(nanoseconds:100_000_000)
            }
            try await Task.sleep(nanoseconds:150_000_000)
        }
        func view(_ parent:NSView?) -> ImageScrollView? {
            if let result=parent as? ImageScrollView { return result }
            for child in parent?.subviews ?? [] { if let result=view(child) { return result } }
            return nil
        }
        func pixels() -> Int { model.preview?.representations.map { max($0.pixelsWide,$0.pixelsHigh) }.max() ?? 0 }
        do {
            let paths=try JSONDecoder().decode([String].self,from:Data(contentsOf:root.appendingPathComponent("inputs.json")))
            let inputs=paths.map { URL(fileURLWithPath:$0) }
            try await wait { model.startupReady }
            model.add(inputs)
            var timings:[Double]=[]
            for item in model.items {
                let start=Date();model.setSelection([item.id])
                try await wait { model.previewInput == item.id && model.preview != nil && !model.previewBusy && model.histogram != nil }
                try require(pixels()==2048,"概览长边不是2048：\(pixels())，\(item.url.lastPathComponent)，\(model.previewMessage)，\(String(describing:model.preview?.representations))")
                try require(!model.previewWantsDetail,"切换照片意外请求原生细节")
                timings.append(Date().timeIntervalSince(start))
            }
            try require(model.previewCache.count==3,"三张照片缓存没有保留")
            try require(!((try FileManager.default.contentsOfDirectory(atPath:model.previewDirectory.path)).contains { $0.hasSuffix(".detail.png") }),"默认预览生成了全尺寸细节图")
            results["overview_seconds"]=timings;results["overviews_only"]=true
            let first=model.items[0].id
            let t=Date();model.setSelection([first])
            try require(!model.previewBusy && model.preview != nil,"缓存切回触发了重建")
            results["cached_switch_ms"]=Date().timeIntervalSince(t)*1000
            try await Task.sleep(nanoseconds:800_000_000)
            guard let window=NSApp.windows.first(where:{$0.title=="toMONO 1.1 验证"}), let viewer=view(window.contentView) else { throw NSError(domain:"找不到实际预览视图",code:1) }
            window.setContentSize(NSSize(width:1440,height:980));window.center();window.makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps:true)
            try await Task.sleep(nanoseconds:500_000_000)
            let clickPoint=NSPoint(x:viewer.canvas.bounds.width*0.45,y:viewer.canvas.bounds.height*0.55)
            let location=viewer.canvas.convert(clickPoint,to:nil)
            let event=NSEvent.mouseEvent(with:.leftMouseDown,location:location,modifierFlags:[],timestamp:ProcessInfo.processInfo.systemUptime,windowNumber:window.windowNumber,context:nil,eventNumber:0,clickCount:2,pressure:1)!
            let detailStart=Date()
            viewer.canvas.mouseDown(with:event)
            try require(abs(viewer.magnification-1)<0.001,"双击未到100%")
            try await Task.sleep(nanoseconds:300_000_000)
            let origin=viewer.contentView.bounds.origin
            try await wait { !model.previewBusy && !model.previewDetailBusy && model.previewWantsDetail && model.previewDetail != nil }
            results["native_detail_ready_ms"]=Date().timeIntervalSince(detailStart)*1000
            let after=viewer.contentView.bounds.origin
            try require(abs(origin.x-after.x)<1 && abs(origin.y-after.y)<1,"原生替换后观察位置移动")
            let native=model.previewPixelSize
            try require(model.previewDetail!.image.size.width==model.previewDetail!.rect.width,"100%细节不是原生像素")
            try require(pixels()==2048,"100%载入了全尺寸显示图")
            try require(model.previewTask==nil,"100%重复启动重建进程")
            let region=model.previewDetail!.rect
            results["native_region_size"]=[region.width,region.height]
            try require(region.width<native.width && region.height<native.height,"没有按可见区域加载")
            try require(abs(viewer.canvas.frame.width*window.backingScaleFactor-native.width)<1,"Retina 100%像素比例不正确")
            results["native_size"]=[native.width,native.height];results["double_click_native"]=true;results["anchor_preserved"]=true
            let oldRegion=model.previewDetail!.rect
            let targetOrigin=NSPoint(x:viewer.canvas.bounds.width*0.6,y:viewer.canvas.bounds.height*0.5)
            viewer.contentView.scroll(to:targetOrigin);viewer.reflectScrolledClipView(viewer.contentView)
            try await wait { !model.previewDetailBusy && model.previewDetail != nil && model.previewDetail!.rect != oldRegion }
            let ratio=window.backingScaleFactor
            let visible=viewer.canvas.visibleRect
            let nativeVisible=NSRect(x:visible.minX*ratio,y:visible.minY*ratio,width:visible.width*ratio,height:visible.height*ratio).integral
            try require(model.previewDetail!.rect.contains(nativeVisible),"拖动后细节没有覆盖观察区域")
            try require(model.previewTask==nil,"拖动时启动整图重建")
            results["pan_loads_new_region_without_reconstruction"]=true
            // Deliver a second double-click to the actual AppKit event handler.
            viewer.canvas.mouseDown(with:event)
            try await wait { !model.previewWantsDetail && !model.previewBusy && model.previewDetail==nil && pixels()==2048 }
            results["double_click_returns_overview"]=true
            // Fast changes must not let a cancelled detail task overwrite a new photo.
            viewer.canvas.mouseDown(with:event)
            try await Task.sleep(nanoseconds:300_000_000)
            model.recipe.response_exposure = 0.25
            try await wait { model.previewBusy && model.previewTask?.isRunning == true }
            model.setSelection([model.items[1].id])
            try await wait { model.preview != nil && !model.previewBusy && pixels()==2048 }
            try require(!model.previewWantsDetail && model.previewInput==model.items[1].id,"旧细节任务污染新选中照片")
            results["selection_cancels_detail"]=true
            model.setSelection([first]);model.recipe.response_exposure = 0
            model.updatePreview()
            try await wait { model.preview != nil && !model.previewBusy }
            model.exportLocation = .besideOriginal
            model.selectedIDs=Set(model.items.map(\.id))
            model.startAll()
            // Snapshot must retain source-folder destinations even if model changes.
            model.exportLocation = .chosenFolder; model.folder=root.appendingPathComponent("unused")
            try await wait { !model.running }
            for item in model.items {
                try require(item.status=="已保存","实际导出失败："+item.detail)
                let expected=item.url.deletingLastPathComponent().appendingPathComponent("toMONO")
                try require(item.output?.deletingLastPathComponent()==expected,"原文件夹导出路径错误")
                try require(FileManager.default.fileExists(atPath:item.output!.deletingPathExtension().appendingPathExtension("processing.json").path),"处理记录未放在DNG旁边")
            }
            results["multi_folder_exports"]=model.items.map { $0.output!.path }
            // Re-export one chosen photo. Other items must not be exported again.
            let previous=model.items[0].output!
            model.exportLocation = .besideOriginal;model.setSelection([first]);model.start()
            try await wait { !model.running }
            try require(model.items[0].status=="已保存" && model.items[0].output != previous,"重复导出未自动编号")
            try require(FileManager.default.fileExists(atPath:previous.path),"重复导出覆盖旧结果")
            for item in model.items.dropFirst() {
                let files=try FileManager.default.contentsOfDirectory(atPath:item.output!.deletingLastPathComponent().path)
                try require(files.filter { $0.hasSuffix(".dng") }.count==1,"导出选中误处理其他照片")
            }
            results["selected_export_collision_safe"]=true
            // Existing custom-folder workflow and sidecar-only collision remain valid.
            let custom = root.appendingPathComponent("custom_output")
            try FileManager.default.createDirectory(at:custom,withIntermediateDirectories:true)
            let next = ExportLocation.uniqueOutput(for:model.items[0].url,settings:model.items[0].settings,directory:custom)
            try Data("existing record".utf8).write(to:next.deletingPathExtension().appendingPathExtension("processing.json"))
            model.exportLocation = .chosenFolder;model.folder=custom;model.start()
            try await wait { !model.running }
            try require(model.items[0].status=="已保存" && model.items[0].output!.deletingLastPathComponent().path==custom.path,"指定文件夹导出回归")
            try require(model.items[0].output!.lastPathComponent.hasSuffix("_2.dng"),"覆盖已有处理记录")
            results["custom_folder_and_sidecar_collision"]=true
            let blocked = root.appendingPathComponent("not_a_directory")
            try Data("keep".utf8).write(to:blocked)
            model.folder=blocked;model.start()
            try await wait { !model.running }
            try require(model.items[0].status=="失败" && model.items[0].detail.contains("无法创建保存文件夹"),"目录失败未准确报告")
            try require(try Data(contentsOf:blocked)==Data("keep".utf8),"目录失败改变原有文件")
            results["directory_failure_preserves_existing_file"]=true
            model.exportLocation = .besideOriginal
            model.items[0].status = "已保存"
            model.items[0].detail = "像素回读与文件结构检查通过"
            model.setSelection([first]);try await wait { model.preview != nil && !model.previewBusy }
            let capture=Process();capture.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
            capture.arguments=["-x","-l",String(window.windowNumber),root.appendingPathComponent("workspace.png").path]
            try capture.run();capture.waitUntilExit()
            results["passed"]=true
        } catch { results["passed"]=false;results["error"]=error.localizedDescription }
        try? JSONSerialization.data(withJSONObject:results,options:[.prettyPrinted,.sortedKeys]).write(to:root.appendingPathComponent("workflow.json"))
        model.cleanupPreviews();NSApp.terminate(nil)
    }
}
