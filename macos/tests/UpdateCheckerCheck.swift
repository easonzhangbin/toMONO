import Foundation

private final class ReleaseURLProtocol: URLProtocol {
    static var payload = Data()
    static var status = 200
    static var nonHTTP = false
    static var error: Error?
    static var delay: TimeInterval = 0
    static var requestCount = 0
    static var lastRequest: URLRequest?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        Self.requestCount += 1; Self.lastRequest = request
        let body=Self.payload, code=Self.status, error=Self.error, nonHTTP=Self.nonHTTP
        DispatchQueue.global().asyncAfter(deadline: .now()+Self.delay) {
            if let error { self.client?.urlProtocol(self,didFailWithError:error);return }
            let response:URLResponse=nonHTTP ? URLResponse(url:self.request.url!,mimeType:"application/json",expectedContentLength:body.count,textEncodingName:"utf-8") : HTTPURLResponse(url:self.request.url!,statusCode:code,httpVersion:"HTTP/1.1",headerFields:["Content-Type":"application/json","Content-Length":String(body.count)])!
            self.client?.urlProtocol(self,didReceive:response,cacheStoragePolicy:.notAllowed)
            self.client?.urlProtocol(self,didLoad:body)
            self.client?.urlProtocolDidFinishLoading(self)
        }
    }
    override func stopLoading() { }
    static func reset(_ data:Data,status:Int=200,nonHTTP:Bool=false,error:Error?=nil,delay:TimeInterval=0) {
        payload=data;self.status=status;self.nonHTTP=nonHTTP;self.error=error;self.delay=delay;requestCount=0;lastRequest=nil
    }
}

@main struct UpdateCheckerCheck {
    static func require(_ value:Bool,_ message:String) throws {
        if !value { throw NSError(domain:"UpdateCheckerCheck",code:1,userInfo:[NSLocalizedDescriptionKey:message]) }
    }
    static func release(_ tag:String="v1.2.0",draft:Bool=false,prerelease:Bool=false,body:String?="新版改进：\n• 预览更快\n• 修复细节",html:String="https://github.com/easonzhangbin/toMONO/releases/tag/v1.2.0",assets:[[String:String]]?=nil) throws -> Data {
        let assets=assets ?? [["name":"toMONO-1.2-AppleSilicon.dmg","browser_download_url":"https://github.com/easonzhangbin/toMONO/releases/download/v1.2.0/toMONO-1.2-AppleSilicon.dmg"]]
        return try JSONSerialization.data(withJSONObject:["tag_name":tag,"name":"toMONO 1.2","body":body as Any? ?? NSNull(),"html_url":html,"draft":draft,"prerelease":prerelease,"assets":assets])
    }
    @MainActor static func main() async throws {
        var checks:[String:Bool]=[:]
        let config=URLSessionConfiguration.ephemeral;config.protocolClasses=[ReleaseURLProtocol.self]
        let session=URLSession(configuration:config)
        defer { session.invalidateAndCancel() }
        func service(_ current:String="1.1.0") -> UpdateChecker { UpdateChecker(currentVersion:current,session:session) }

        for (a,b) in [("1.1","1.1.0"),("v1.1.0","1.1.0+build15"),("V1.1.0","1.1")] {
            try require(ReleaseVersion(a)==ReleaseVersion(b),"等值版本未归一化")
        }
        for (a,b) in [("1.0.0-beta.8.1","1.1.0"),("1.1.0-rc.2","1.1.0-rc.10"),("1.1.0-rc.10","1.1.0"),("1.2.0","1.10.0")] {
            try require(ReleaseVersion(a)! < ReleaseVersion(b)!,"语义版本排序错误")
        }
        for invalid in ["latest","1.1.0.3","1.2.0-","1.0.0+","v","1.x",String(repeating:"9",count:60)] {
            try require(ReleaseVersion(invalid)==nil,"错误版本被接受："+invalid)
        }
        checks["semantic_version_ordering"]=true

        ReleaseURLProtocol.reset(try release());let newer=service()
        await newer.check()
        try require(newer.availableRelease?.tagName=="v1.2.0" && newer.message==nil && !newer.isChecking,"新版未提示或状态未结束")
        try require(newer.availableRelease?.releaseNotes=="新版改进：\n• 预览更快\n• 修复细节","更新说明丢失")
        try require(newer.availableRelease?.downloadURL.lastPathComponent=="toMONO-1.2-AppleSilicon.dmg","未首选Apple Silicon DMG")
        let request=ReleaseURLProtocol.lastRequest!
        try require(request.url==UpdateChecker.endpoint && request.httpMethod=="GET" && request.httpBody==nil && request.value(forHTTPHeaderField:"Authorization")==nil && request.timeoutInterval<=12 && request.value(forHTTPHeaderField:"User-Agent")=="toMONO/1.1.0","检查请求隐私或超时无效")
        newer.dismiss();try require(newer.availableRelease==nil,"关闭新版提示无效")
        checks["new_release_notes_and_download"]=true;checks["readonly_request_no_token_or_photos"]=true

        for tag in ["v1.1.0","v1.1","v1.0.0-beta.8.1","v1.0.0"] {
            ReleaseURLProtocol.reset(try release(tag));let check=service();await check.check(manual:true)
            try require(check.availableRelease==nil && check.message != nil,"同版本、旧版或测试版误提示")
        }
        for flags in [(true,false),(false,true)] {
            ReleaseURLProtocol.reset(try release(draft:flags.0,prerelease:flags.1));let check=service();await check.check()
            try require(check.availableRelease==nil && check.message==nil,"草稿或测试版误弹窗")
        }
        checks["old_same_draft_prerelease_filtered"]=true

        for (status,fragment) in [(404,"暂无"),(403,"限制"),(429,"限制"),(500,"暂时")] {
            ReleaseURLProtocol.reset(Data(),status:status);let check=service();await check.check()
            try require(check.availableRelease==nil && check.message==nil,"自动失败不应打断")
            await check.check(manual:true)
            try require(check.message?.contains(fragment)==true && !check.isChecking,"手动失败没有正确中文提示")
        }
        checks["http_errors_quiet_auto_clear_manual"]=true

        for data in [Data("not json".utf8),try release("not-a-version"),try release(html:"https://evil.example/releases/tag/v1.2.0")] {
            ReleaseURLProtocol.reset(data);let check=service();await check.check(manual:true)
            try require(check.availableRelease==nil && check.message != nil && !check.isChecking,"错误JSON或非官方地址被接受")
        }
        ReleaseURLProtocol.reset(try release(),nonHTTP:true);let nonHTTP=service();await nonHTTP.check(manual:true)
        try require(nonHTTP.availableRelease==nil && nonHTTP.message != nil,"非HTTP结果未拒绝")
        ReleaseURLProtocol.reset(Data(repeating:65,count:1_048_577));let oversized=service();await oversized.check(manual:true)
        try require(oversized.availableRelease==nil && oversized.message != nil,"过大响应未拒绝")
        checks["malformed_non_http_oversized_rejected"]=true

        ReleaseURLProtocol.reset(Data(),error:URLError(.timedOut));let offline=service();await offline.check()
        try require(offline.message==nil && !offline.isChecking,"自动网络超时未安静结束")
        await offline.check(manual:true);try require(offline.message?.contains("仍可正常使用")==true,"手动超时未说明可继续使用")
        offline.clearMessage();try require(offline.message==nil,"手动提示无法清除")
        checks["network_timeout_and_message_reset"]=true

        ReleaseURLProtocol.reset(try release(),delay:0.08);let duplicate=service()
        let first=Task { await duplicate.check() }
        try await Task.sleep(nanoseconds:10_000_000)
        await duplicate.check(manual:true);await first.value
        try require(ReleaseURLProtocol.requestCount==1 && duplicate.availableRelease != nil,"重复检查没有合并")
        checks["concurrent_checks_do_not_duplicate"]=true

        let badAssets=[["name":"toMONO-AppleSilicon.dmg","browser_download_url":"https://evil.example/toMONO-AppleSilicon.dmg"]]
        let fallback=try JSONDecoder().decode(GitHubRelease.self,from:release(body:nil,assets:badAssets))
        try require(fallback.downloadURL==fallback.releasePageURL && fallback.releaseNotes.contains("未附"),"缺安全DMG或更新说明未回退")
        for bad in ["http://github.com/easonzhangbin/toMONO/releases/tag/v1", "https://github.com.evil.example/easonzhangbin/toMONO/releases/tag/v1", "https://github.com/other/toMONO/releases/tag/v1", "https://user@github.com/easonzhangbin/toMONO/releases/tag/v1", "https://github.com:444/easonzhangbin/toMONO/releases/tag/v1", "https://github.com/easonzhangbin/toMONO/releases/tag/../evil", "https://github.com/easonzhangbin/toMONO/releases/tag/v1?x=evil"] {
            try require(GitHubRelease.officialURL(bad,prefix:"/easonzhangbin/toMONO/releases/tag/")==nil,"危险URL未拒绝")
        }
        checks["official_urls_and_fallbacks"]=true
        let result:[String:Any]=["passed":true,"checks":checks,"test_groups":checks.count,"real_network_used":false]
        let data=try JSONSerialization.data(withJSONObject:result,options:[.sortedKeys])
        print(String(decoding:data,as:UTF8.self))
    }
}
