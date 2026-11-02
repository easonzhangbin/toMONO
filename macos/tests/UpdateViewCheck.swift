import SwiftUI
import AppKit

private final class UpdateViewURLProtocol: URLProtocol {
    static var count=0
    override class func canInit(with request:URLRequest)->Bool { true }
    override class func canonicalRequest(for request:URLRequest)->URLRequest { request }
    override func startLoading() {
        Self.count += 1
        let release:[String:Any]=[
            "tag_name":"v1.2.0","name":"toMONO 1.2 正式版","draft":false,"prerelease":false,
            "body":"预览与性能\n• 改进切换照片时的预览加载速度。\n• 优化局部放大与缓存，观察细节更流畅。\n\n重建与使用\n• 改进方向自适应细节重建。\n• 增加逐张参数复位，保留原始 RAW 文件。\n\n本说明为界面验证用的模拟发布内容。",
            "html_url":"https://github.com/easonzhangbin/toMONO/releases/tag/v1.2.0",
            "assets":[["name":"toMONO-1.2-AppleSilicon.dmg","browser_download_url":"https://github.com/easonzhangbin/toMONO/releases/download/v1.2.0/toMONO-1.2-AppleSilicon.dmg"]]
        ]
        let data=try! JSONSerialization.data(withJSONObject:release)
        let response=HTTPURLResponse(url:request.url!,statusCode:200,httpVersion:"HTTP/1.1",headerFields:["Content-Type":"application/json"] )!
        client?.urlProtocol(self,didReceive:response,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:data);client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() { }
}

@main struct UpdateViewCheck: App {
    @StateObject private var checker:UpdateChecker
    @State private var started=false
    @State private var dismissed=0
    init() {
        let config=URLSessionConfiguration.ephemeral;config.protocolClasses=[UpdateViewURLProtocol.self]
        _checker=StateObject(wrappedValue:UpdateChecker(currentVersion:"1.1.0",session:URLSession(configuration:config)))
    }
    var body:some Scene {
        Window("toMONO 更新提示验证",id:"update-qa") {
            VStack(spacing:12) {
                Text("toMONO 更新提示 · 本地验证").font(.headline)
                Text("模拟 GitHub 发布，不访问网络，也不下载。")
            }.frame(width:680,height:540)
                .sheet(isPresented:Binding(get:{checker.availableRelease != nil},set:{if !$0 { checker.dismiss() }})) {
                    if let release=checker.availableRelease {
                        UpdateAvailableView(release:release,onDismiss:{ dismissed += 1;checker.dismiss() })
                            .environment(\.locale,Locale(identifier:"zh_Hans"))
                    }
                }
                .onAppear {
                    guard !started else { return };started=true
                    Task { @MainActor in await verify() }
                }
        }.defaultSize(width:680,height:540)
    }
    @MainActor func verify() async {
        let root=URL(fileURLWithPath:ProcessInfo.processInfo.environment["TOMONO_UPDATE_QA_DIR"]!)
        var result:[String:Any]=[:]
        func require(_ value:Bool,_ message:String)throws {
            if !value { throw NSError(domain:"UpdateViewCheck",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
        }
        func wait(_ condition:()->Bool)async throws {
            let started=Date()
            while !condition() {
                if Date().timeIntervalSince(started)>8 { throw NSError(domain:"UI timeout",code:2) }
                try await Task.sleep(nanoseconds:50_000_000)
            }
            try await Task.sleep(nanoseconds:200_000_000)
        }
        func buttons(_ view:NSView?)->[NSButton] {
            guard let view else { return [] }
            return (view as? NSButton).map { [$0] } ?? view.subviews.flatMap { buttons($0) }
        }
        do {
            await checker.check()
            try await wait { NSApp.windows.first(where:{$0.title=="toMONO 更新提示验证"})?.sheets.isEmpty==false }
            let window=NSApp.windows.first(where:{$0.title=="toMONO 更新提示验证"})!
            window.center();window.makeKeyAndOrderFront(nil)
            let sheet=window.sheets.first!
            try require(checker.availableRelease?.releaseNotes.contains("优化局部放大与缓存")==true,"多行中文改进说明丢失")
            try require(sheet.frame.width>=540 && sheet.frame.height>=300,"更新提示布局尺寸异常")
            let capture=Process();capture.executableURL=URL(fileURLWithPath:"/usr/sbin/screencapture")
            capture.arguments=["-x","-l",String(window.windowNumber),root.appendingPathComponent("update-sheet.png").path]
            try capture.run();capture.waitUntilExit()
            result["screenshot_saved"]=capture.terminationStatus==0
            let nativeButtons=buttons(sheet.contentView)
            result["native_button_titles"]=nativeButtons.map(\.title)
            if let later=nativeButtons.first(where:{$0.title=="稍后"}) {
                later.performClick(nil)
            } else {
                let event=NSEvent.keyEvent(with:.keyDown,location:.zero,modifierFlags:[],timestamp:0,windowNumber:sheet.windowNumber,context:nil,characters:"\u{1b}",charactersIgnoringModifiers:"\u{1b}",isARepeat:false,keyCode:53)!
                NSApp.sendEvent(event)
            }
            try await wait { checker.availableRelease==nil && window.sheets.isEmpty }
            try require(dismissed==1,"稍后关闭没有执行实际视图回调")
            try require(UpdateViewURLProtocol.count==1,"关闭提示触发额外请求")
            result["actual_sheet_presented"]=true
            result["multiline_chinese_notes_retained"]=true
            result["later_dismissed_without_download"]=true
            let same=UpdateChecker(currentVersion:"1.2.0",session:{let c=URLSessionConfiguration.ephemeral;c.protocolClasses=[UpdateViewURLProtocol.self];return URLSession(configuration:c)}())
            await same.check(manual:true)
            try require(same.message?.contains("最新正式版本")==true,"手动检查状态缺失")
            same.clearMessage();try require(same.message==nil,"手动状态无法关闭")
            result["manual_status_clears"]=true
            result["passed"]=true
            result["browser_opened"]=false
            result["real_network_used"]=false
        } catch { result["passed"]=false;result["error"]=error.localizedDescription }
        let bytes=try! JSONSerialization.data(withJSONObject:result,options:[.sortedKeys,.prettyPrinted])
        try! bytes.write(to:root.appendingPathComponent("update-ui.json"))
        print(String(decoding:bytes,as:UTF8.self))
        NSApplication.shared.terminate(nil)
    }
}
