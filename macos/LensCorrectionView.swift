import SwiftUI

struct LensProfile: Decodable, Identifiable {
    var id: String
    var maker: String
    var model: String
    var mounts: [String]
    var crop_factor: Double
    var min_focal: Double?
    var max_focal: Double?
    var min_aperture: Double?
    var distortion: Bool
    var tca: Bool
    var vignetting: Bool
    var title: String { model.lowercased().hasPrefix(maker.lowercased()) ? model : maker + " " + model }
    var capabilities: String { [distortion ? "畸变" : nil,vignetting ? "暗角" : nil,tca ? "横向色差资料" : nil].compactMap{$0}.joined(separator:" · ") }
}
struct LensCatalog: Decodable {
    var lensfunpy_version: String
    var lensfun_version: String
    var database_sha256: String
    var profiles: [LensProfile]
    static func load() -> LensCatalog? {
        guard let url=Bundle.main.url(forResource:"LensCatalog",withExtension:"json"),let bytes=try? Data(contentsOf:url) else { return nil }
        return try? JSONDecoder().decode(LensCatalog.self,from:bytes)
    }
}
struct LensCaptureInfo {
    var model: String?
    var focal: Double?
    var aperture: Double?
    var cropFactor: Double?
}
struct LensCorrectionSettings: Codable, Equatable {
    var profile_id: String
    var focal_override: Double? = nil
    var aperture_override: Double? = nil
    var crop_override: Double? = nil
    var distance = 1000.0
    var distortion = true
    var vignetting = false
}

struct LensCorrectionSection: View {
    @ObservedObject var model: AppModel
    @State private var chooseLens = false
    private var profile: LensProfile? { model.lensCatalog?.profiles.first { $0.id == model.recipe.lens_correction?.profile_id } }
    private func usable(_ value: Double?) -> Double? {
        guard let value, value.isFinite, value > 0 else { return nil }
        return value
    }
    private var defaultFocal: Double { usable(model.selected?.lensCapture?.focal) ?? usable(profile?.min_focal) ?? 35 }
    private var defaultAperture: Double { usable(model.selected?.lensCapture?.aperture) ?? usable(profile?.min_aperture) ?? 5.6 }
    private var defaultCrop: Double { usable(model.selected?.lensCapture?.cropFactor) ?? 1 }
    private var defaultDistance: Double { LensCorrectionSettings(profile_id:profile?.id ?? "").distance }
    private func defaultDescription(_ value: Double, unit: String = "") -> String {
        value.formatted(.number.precision(.fractionLength(0...2))) + unit
    }
    private func switchValue(_ key: WritableKeyPath<LensCorrectionSettings,Bool>) -> Binding<Bool> {
        Binding(get:{ model.recipe.lens_correction?[keyPath:key] ?? false },set:{ model.recipe.lens_correction?[keyPath:key] = $0 })
    }
    private func number(_ key: WritableKeyPath<LensCorrectionSettings,Double?>,fallback:Double) -> Binding<Double> {
        Binding(get:{ model.recipe.lens_correction?[keyPath:key] ?? fallback },set:{ model.recipe.lens_correction?[keyPath:key] = $0 })
    }
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            Text("镜头校正").font(.headline)
            if let name = model.selected?.lensCapture?.model {
                Text("照片记录："+name).font(.caption).foregroundStyle(.secondary)
            } else { Text("未记录镜头时，可手动搜索配置。").font(.caption).foregroundStyle(.secondary) }
            if let settings=model.recipe.lens_correction,let profile {
                Text(profile.title).fontWeight(.medium)
                Text(profile.mounts.joined(separator:" / ")).font(.caption).foregroundStyle(.secondary)
                Toggle("畸变校正",isOn:switchValue(\.distortion)).disabled(!profile.distortion)
                Toggle("暗角校正",isOn:switchValue(\.vignetting)).disabled(!profile.vignetting)
                Toggle("手动填写焦距和光圈",isOn:Binding(get:{settings.focal_override != nil},set:{ manual in
                    model.recipe.lens_correction?.focal_override = manual ? defaultFocal : nil
                    model.recipe.lens_correction?.aperture_override = manual ? defaultAperture : nil
                }))
                if settings.focal_override != nil {
                    HStack(spacing:8) {
                        Text("焦距 mm")
                        TextField("焦距",value:number(\.focal_override,fallback:defaultFocal),format:.number).textFieldStyle(.roundedBorder).frame(minWidth:45)
                        ParameterResetButton(parameter:"镜头焦距",defaultDescription:defaultDescription(defaultFocal,unit:" mm"),isDefault:settings.focal_override == defaultFocal) {
                            model.recipe.lens_correction?.focal_override = defaultFocal
                        }
                    }
                    HStack(spacing:8) {
                        Text("光圈 f/")
                        TextField("光圈",value:number(\.aperture_override,fallback:defaultAperture),format:.number).textFieldStyle(.roundedBorder).frame(minWidth:45)
                        ParameterResetButton(parameter:"镜头光圈",defaultDescription:"f/"+defaultDescription(defaultAperture),isDefault:(settings.aperture_override ?? defaultAperture) == defaultAperture) {
                            model.recipe.lens_correction?.aperture_override = defaultAperture
                        }
                    }
                } else { Text("焦距、光圈按每张照片读取；手动镜头可开启手填。").font(.caption).foregroundStyle(.secondary) }
                Toggle("手动画幅系数",isOn:Binding(get:{settings.crop_override != nil},set:{ model.recipe.lens_correction?.crop_override = $0 ? defaultCrop : nil }))
                if settings.crop_override != nil {
                    HStack(spacing:8) {
                        Text("画幅系数")
                        TextField("画幅系数",value:number(\.crop_override,fallback:defaultCrop),format:.number.precision(.fractionLength(2))).textFieldStyle(.roundedBorder).frame(minWidth:45)
                        ParameterResetButton(parameter:"镜头画幅系数",defaultDescription:defaultDescription(defaultCrop),isDefault:settings.crop_override == defaultCrop) {
                            model.recipe.lens_correction?.crop_override = defaultCrop
                        }
                    }
                    Text("全画幅1.0；APS-C常见1.5；M4/3为2.0。按实际画幅填写。").font(.caption).foregroundStyle(.secondary)
                }
                HStack {
                    Text("对焦距离 m")
                    TextField("距离",value:Binding(get:{settings.distance},set:{model.recipe.lens_correction?.distance=$0}),format:.number).textFieldStyle(.roundedBorder).frame(minWidth:45)
                    ParameterResetButton(parameter:"镜头对焦距离",defaultDescription:defaultDescription(defaultDistance,unit:" m（远景近似）"),isDefault:settings.distance == defaultDistance) {
                        model.recipe.lens_correction?.distance = defaultDistance
                    }
                }
                Text("1000m代表远景近似；暗角匹配会使用此距离。").font(.caption).foregroundStyle(.secondary)
                if profile.tca {
                    Text("库含横向色差资料；当前绿色单通道路径不套用红蓝配准。").font(.caption).foregroundStyle(.secondary)
                }
                Text(model.lensCorrectionSummary).font(.caption).foregroundStyle(.secondary)
                Button("关闭镜头校正") { model.recipe.lens_correction=nil }
            } else { Text("未启用额外镜头校正").foregroundStyle(.secondary) }
            Button("搜索或更换镜头…") { chooseLens=true }.disabled(model.lensCatalog == nil)
            Text("畸变与暗角写入输出像素，并记录所用配置。原图保持不变，预览与导出共用校正；默认关闭。").font(.caption).foregroundStyle(.secondary)
        }
        .sheet(isPresented:$chooseLens) {
            LensSelectionView(catalog:model.lensCatalog?.profiles ?? [],recorded:model.selected?.lensCapture?.model) { lens in
                model.recipe.lens_correction=LensCorrectionSettings(profile_id:lens.id,distortion:lens.distortion,vignetting:!lens.distortion && lens.vignetting)
                chooseLens=false
            }
        }
    }
}

struct LensSelectionView: View {
    let catalog: [LensProfile]
    let recorded: String?
    let select: (LensProfile) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var search=""
    @State private var selection: String?
    private var matches:[LensProfile] {
        let aliases=["索尼":"Sony","佳能":"Canon","尼康":"Nikon","松下":"Panasonic","富士":"Fujifilm","徕卡":"Leica","理光":"Ricoh","蔡司":"Zeiss","适马":"Sigma","腾龙":"Tamron"]
        var query=search
        for (name,value) in aliases { query=query.replacingOccurrences(of:name,with:value) }
        let terms=query.lowercased().split(whereSeparator:{$0.isWhitespace}).map { String($0.filter{$0.isLetter || $0.isNumber}) }.filter{!$0.isEmpty}
        return catalog.filter { lens in
            let text=(lens.title+" "+lens.mounts.joined(separator:" ")).lowercased().filter{$0.isLetter || $0.isNumber}
            return terms.allSatisfy { text.contains($0) }
        }
    }
    private var chosen:LensProfile? { catalog.first{$0.id==selection} }
    var body: some View {
        VStack(alignment:.leading,spacing:14) {
            Text("选择镜头校正配置").font(.title2.weight(.semibold))
            if let recorded { Text("照片中的镜头："+recorded).foregroundStyle(.secondary) }
            TextField("搜索厂商、镜头型号或卡口",text:$search).textFieldStyle(.roundedBorder)
            List(matches,selection:$selection) { lens in
                VStack(alignment:.leading,spacing:5) {
                    Text(lens.title).fontWeight(.medium)
                    Text(lens.mounts.joined(separator:" / ")+" · "+lens.capabilities).font(.caption).foregroundStyle(.secondary)
                }.padding(.vertical,4).tag(lens.id)
            }
            if matches.isEmpty { Text("未找到匹配配置；不会用其他镜头替代。可尝试只搜索焦距或厂商。").foregroundStyle(.secondary) }
            Text("内置 \(catalog.count) 条配置。名称相似或卡口相同不代表光学版本相同，请核对具体镜头。只有部分配置包含全部校正项目。")
                .font(.caption).foregroundStyle(.secondary)
            HStack { Button("取消"){dismiss()};Spacer();Button("使用此配置"){if let chosen {select(chosen)}}.keyboardShortcut(.defaultAction).disabled(chosen == nil || !(chosen!.distortion || chosen!.vignetting)) }
        }.padding(22).frame(width:760,height:600)
    }
}
