import AppKit
import SwiftUI

/// Exercises the production response gate and native alert, using queue values
/// only. No source photo, decoder, export, update request or browser is used.
@main struct RGBMixNoticeCheck: App {
    @StateObject private var model: AppModel
    @StateObject private var notice=RGBMixNoticeController()
    @State private var started=false

    init() {
        let root=URL(fileURLWithPath:ProcessInfo.processInfo.environment["TOMONO_RGB_QA_DIR"]!)
        // Missing runtime deliberately prevents backend startup in this UI-only test.
        _model=StateObject(wrappedValue:AppModel(resourceOverride:root.appendingPathComponent("no-runtime")))
    }
    var body: some Scene {
        Window("toMONO RGB 响应提示验证",id:"rgb-notice-qa") {
            ResponseControls(model:model,noticeController:notice)
                .padding(24).frame(width:520,height:820)
                .environment(\.locale,Locale(identifier:"zh_Hans"))
                .onAppear {
                    guard !started else { return };started=true
                    Task { @MainActor in await verify() }
                }
        }.defaultSize(width:520,height:820)
    }
    @MainActor private func verify() async {
        let root=URL(fileURLWithPath:ProcessInfo.processInfo.environment["TOMONO_RGB_QA_DIR"]!)
        var result:[String:Any]=[:]
        func require(_ value:Bool,_ message:String)throws {
            if !value { throw NSError(domain:"RGBMixNoticeCheck",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
        }
        func wait(_ condition:()->Bool)async throws {
            let start=Date()
            while !condition() {
                if Date().timeIntervalSince(start)>8 { throw NSError(domain:"RGB UI timeout",code:2) }
                try await Task.sleep(nanoseconds:50_000_000)
            }
            try await Task.sleep(nanoseconds:150_000_000)
        }
        func buttons(_ parent:NSView?)->[NSButton] {
            guard let parent else { return [] }
            return (parent as? NSButton).map { [$0] } ?? parent.subviews.flatMap { buttons($0) }
        }
        do {
            var first=InputItem(url:root.appendingPathComponent("photo-a.DNG"))
            var second=InputItem(url:root.appendingPathComponent("photo-b.DNG"))
            first.settings.response_exposure=1.25
            second.settings.response_exposure = -0.5
            model.items=[first,second];model.selection=first.id;model.selectedIDs=[first.id,second.id]
            let initial=model.recipe
            let window=NSApp.windows.first(where:{$0.title=="toMONO RGB 响应提示验证"})!
            window.center();window.makeKeyAndOrderFront(nil)

            notice.select("mix",model:model)
            try require(notice.isPresented && model.recipe==initial && model.items[0].settings==initial,"确认前参数已改变")
            try require(model.previewTask==nil,"确认前启动了预览")
            try await wait { !window.sheets.isEmpty }
            let sheet=window.sheets.first!
            let native=buttons(sheet.contentView)
            result["native_alert_button_titles"]=native.map(\.title)
            let capture=Process();capture.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
            capture.arguments=["-x","-l",String(window.windowNumber),root.appendingPathComponent("rgb-response-notice.png").path]
            try capture.run();capture.waitUntilExit()
            result["screenshot_saved"]=capture.terminationStatus==0
            guard let cancel=native.first(where:{$0.title=="保留当前响应"}) else { throw NSError(domain:"Native cancel button missing",code:3) }
            cancel.performClick(nil)
            try await wait { window.sheets.isEmpty }
            try require(model.recipe==initial && !notice.isPresented,"取消改变了参数")
            result["cancel_native_button_keeps_recipe"]=true
            result["no_change_or_preview_before_confirmation"]=true

            notice.select("mix",model:model)
            try await wait { !window.sheets.isEmpty }
            guard let confirm=buttons(window.sheets.first?.contentView).first(where:{$0.title=="了解，使用 RGB 混合"}) else { throw NSError(domain:"Native confirm button missing",code:4) }
            confirm.performClick(nil)
            try await wait { window.sheets.isEmpty }
            try require(model.recipe.response_mode=="mix" && model.recipe.response_exposure==1.25,"确认未应用当前照片或污染曝光")
            try require(model.items[0].settings.response_mode=="mix" && model.items[1].settings==second.settings,"混合应用到了其他照片")
            result["confirm_native_button_changes_only_current_photo"]=true

            model.selection=second.id
            try await wait { model.recipe.response_mode=="green" }
            notice.select("mix",model:model)
            let stale=notice.request!
            model.selection=first.id
            try await wait { !notice.isPresented && window.sheets.isEmpty }
            notice.confirm(stale,model:model)
            try require(model.recipe.response_mode=="mix" && model.items[1].settings.response_mode=="green","陈旧确认改变了其他照片")
            result["photo_change_dismisses_and_rejects_stale_confirmation"]=true

            model.selection=second.id
            model.recipe.response_mode="mix"
            try await Task.sleep(nanoseconds:200_000_000)
            try require(!notice.isPresented && window.sheets.isEmpty,"恢复已保存的mix意外弹出提示")
            model.selection=first.id
            try await Task.sleep(nanoseconds:200_000_000)
            try require(!notice.isPresented && window.sheets.isEmpty,"切换到mix照片意外弹出提示")
            result["preset_restore_and_photo_activation_do_not_prompt"]=true

            model.recipe.response_mode="green"
            notice.select("mix",model:model)
            let changed=notice.request!
            model.recipe.response_mode="narrow_green"
            try await wait { !notice.isPresented && window.sheets.isEmpty }
            notice.confirm(changed,model:model)
            try require(model.recipe.response_mode=="narrow_green","陈旧确认覆盖了外部恢复的响应")
            result["external_response_restore_rejects_stale_confirmation"]=true
            result["no_input_read_or_export"]=true
            result["passed"]=true
        } catch { result["passed"]=false;result["error"]=error.localizedDescription }
        let data=try! JSONSerialization.data(withJSONObject:result,options:[.prettyPrinted,.sortedKeys])
        try! data.write(to:root.appendingPathComponent("rgb-notice-ui.json"))
        print(String(decoding:data,as:UTF8.self))
        NSApp.terminate(nil)
    }
}
