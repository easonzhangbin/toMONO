import Foundation
import AppKit

/// Uses the actual Codable recipe and queue value types, without a worker or window.
@main struct DetailModeModelCheck {
    static func require(_ value:Bool,_ message:String) throws {
        if !value { throw NSError(domain:message,code:1) }
    }
    static func decode(_ json:String) throws -> RecipeDocument {
        try JSONDecoder().decode(RecipeDocument.self,from:Data(json.utf8))
    }
    static func encoded(_ value:RecipeDocument) throws -> Data {
        let e=JSONEncoder();e.outputFormatting=[.sortedKeys]
        return try e.encode(value)
    }
    static func main() throws {
        let initial=RecipeDocument()
        try require(initial.version==2 && initial.detail_mode=="spectral" && initial.responseValid,"新设置未默认C01")
        let legacy=try decode("{\"version\":1,\"algorithm\":\"EdgeAware\",\"narrow_interpolation\":\"linear\",\"response_mode\":\"narrow_blue\"}")
        try require(legacy.version==2 && legacy.detail_mode=="legacy" && legacy.algorithm=="EdgeAware" && legacy.narrow_interpolation=="linear" && legacy.response_mode=="narrow_blue","旧设置迁移改动重建语义")
        let unversioned=try decode("{\"algorithm\":\"Bicubic\"}")
        try require(unversioned.detail_mode=="legacy" && unversioned.version==2,"无版本的旧设置未保持原有模式")
        let v2=try decode("{\"version\":2}")
        try require(v2.detail_mode=="spectral","v2缺字段没有采用C01默认")
        let explicit=try decode("{\"version\":1,\"detail_mode\":\"spectral_guard\"}")
        try require(explicit.detail_mode=="spectral_guard" && explicit.version==2,"明确记录的细节模式被迁移覆盖")
        let invalid=try decode("{\"version\":2,\"detail_mode\":\"unknown\"}")
        try require(!invalid.responseValid,"未知细节模式被允许导出")
        do {
            _=try decode("{\"version\":3}")
            throw NSError(domain:"未知版本未拒绝",code:2)
        } catch is DecodingError { }
        var fingerprints=Set<Data>()
        for mode in ["spectral","spectral_guard","directional","legacy"] {
            var r=initial;r.detail_mode=mode;r.response_mode="mix";r.response_exposure=0.35
            let bytes=try encoded(r)
            let loaded=try JSONDecoder().decode(RecipeDocument.self,from:bytes)
            try require(loaded==r,"细节模式未完整预设往返："+mode)
            fingerprints.insert(bytes)
        }
        try require(fingerprints.count==4,"完整recipe缓存负载没有区分细节模式")
        var narrow=initial;narrow.detail_mode="spectral_guard";narrow.response_mode="narrow_blue";narrow.response_exposure=1.15
        let reference=narrow.greenReferenceRecipe
        try require(reference.detail_mode=="legacy" && reference.response_mode=="green" && reference.response_exposure==0,"对照没有使用旧绿色重建")
        try require(narrow.detail_mode=="spectral_guard" && narrow.response_mode=="narrow_blue" && narrow.response_exposure==1.15,"对照污染实际导出recipe")
        var saved=InputItem(url:URL(fileURLWithPath:"/tmp/detail-mode-state-only.RAW"))
        saved.output=URL(fileURLWithPath:"/tmp/detail-mode-state-only.dng")
        saved.outputRecipe=saved.settings;saved.status="已保存"
        try require(saved.displayStatus=="已保存","初始保存状态不正确")
        saved.settings.detail_mode="directional"
        try require(saved.displayStatus=="已修改","切换细节模式没有使保存状态失效")
        saved.settings=saved.outputRecipe!
        try require(saved.displayStatus=="已保存","恢复保存时模式未恢复保存状态")
        var second=InputItem(url:URL(fileURLWithPath:"/tmp/detail-mode-independent.RAW"))
        saved.settings.detail_mode="spectral_guard";second.settings.detail_mode="directional"
        let queued=[saved.settings,second.settings]
        saved.settings.detail_mode="spectral"
        try require(queued[0].detail_mode=="spectral_guard" && queued[1].detail_mode=="directional" && second.settings.detail_mode=="directional","逐张设置或导出值快照发生串扰")
        print("{\"default_C01\":true,\"recipe_v1_migration\":true,\"unversioned_migration\":true,\"v2_default\":true,\"explicit_mode_preserved\":true,\"unknown_mode_rejected\":true,\"unknown_version_rejected\":true,\"preset_roundtrip_modes\":4,\"distinct_preview_payloads\":4,\"legacy_reference_recipe\":true,\"reference_keeps_export_settings\":true,\"saved_state_invalidates\":true,\"per_photo_value_snapshots\":true,\"windows_opened\":0}")
    }
}
