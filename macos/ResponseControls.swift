import SwiftUI

struct ParameterResetButton: View {
    let parameter: String
    let defaultDescription: String
    let isDefault: Bool
    var title = "复位"
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Label(title, systemImage: "arrow.counterclockwise")
                .font(.caption)
                .fixedSize()
        }
        .buttonStyle(.bordered)
        .controlSize(.mini)
        .disabled(isDefault)
        .accessibilityLabel("\(parameter)复位")
        .accessibilityHint("恢复为\(defaultDescription)")
        .help("\(parameter)复位为\(defaultDescription)")
    }
}

struct DetailComputationControls: View {
    @ObservedObject var model: AppModel
    @State private var showHelp = false
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            HStack(spacing:8) {
                Text("细节计算模式").font(.headline)
                Button { showHelp = true } label: { Image(systemName:"info.circle") }
                    .buttonStyle(.plain).foregroundStyle(.secondary)
                    .accessibilityLabel("细节计算模式说明")
                    .popover(isPresented:$showHelp,arrowEdge:.leading) {
                        VStack(alignment:.leading,spacing:12) {
                            Text("选择缺失采样的计算方式").font(.headline)
                            Text("方向自适应（D10，默认）：根据局部方向的可靠性补齐绿色位置，优先稳妥控制边缘；红、蓝使用有界同色三次。细密周期织纹仍可能退化。")
                            Text("频域精细（C01）：按同色采样的频率特性重建，优先保留细密织纹与细线。高反差边缘可能振铃，暗部噪声也可能更明显。")
                            Text("频域限幅（D11）：在频域重建后限制局部极值，可减少过冲；部分周期纹理可能损失极值并出现格点偏差。")
                            Text("LMMSE统计重建（实验）：按Zhang–Wu方向色差统计估算缺失采样，会借助其他颜色。仅用于普通绿色或RGB混合，不用于窄带独立纯通道；高光过冲与不相关颜色纹理仍有风险。")
                            Text("细节重建核保留目标色的实测约束；显式坏点、绿色校正、曝光及镜头处理仍可能改变数值。不作额外相机噪声标定、锐化或生成纹理；LMMSE内部使用局部残差统计。常规模式遇其他排列或线性输入使用原有路径并显示实际结果；严格窄带不符合直接2×2 Bayer时会拒绝。")
                            Text("C01、D11、D10可用于普通单色、RGB混合与窄带纯通道；LMMSE只用于普通照片。预览和导出使用相同计算。切换时可用局部检查放大镜对照同一区域；检查建议不代表已经检测到伪影。")
                            HStack { Spacer(); Button("知道了") { showHelp = false } }
                        }.font(.callout).fixedSize(horizontal:false,vertical:true).padding(20).frame(width:390)
                    }
                Spacer(minLength:0)
            }
            HStack(spacing:8) {
                Picker("计算方式",selection:$model.recipe.detail_mode) {
                    Text("方向自适应（默认）").tag("directional")
                    Text("频域精细").tag("spectral")
                    Text("频域限幅").tag("spectral_guard")
                    Text("LMMSE 统计重建（实验）").tag("lmmse").disabled(model.recipe.isNarrowband)
                    if model.recipe.usesLegacyDetail { Text("原有模式（旧预设）").tag("legacy") }
                }.labelsHidden().accessibilityLabel("细节计算模式")
                ParameterResetButton(parameter:"细节计算模式",defaultDescription:"方向自适应（D10）",isDefault:model.recipe.detail_mode == "directional") {
                    model.recipe.detail_mode = "directional"
                }
            }
            Text(model.recipe.detailModeDescription).font(.caption).foregroundStyle(.secondary)
            if model.recipe.usesLegacyDetail {
                Text("此预设保留了旧版重建方式。选择上方模式后，将按新的计算方式重新生成。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if model.selected != nil {
                Text("仅调整当前照片；会随相机设置预设一并保存。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            if model.previewBusy {
                Text("正在按当前模式重建…").font(.caption).foregroundStyle(.secondary)
            } else if model.preview != nil && !model.showingSource {
                Text(model.showingReference ? "当前对照原有绿色重建，导出仍使用所选模式。" : model.reconstructionSummary)
                    .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            }
        }.disabled(model.selected == nil)
    }
}

struct ResponseControls: View {
    @ObservedObject var model: AppModel
    @State private var showHelp = false
    private var defaults: RecipeDocument { RecipeDocument() }
    var body: some View {
        VStack(alignment:.leading,spacing:12) {
            HStack(spacing:8) {
                Text("单色响应").font(.headline)
                Button { showHelp = true } label: { Image(systemName:"info.circle") }
                    .buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel("单色响应与窄带模式说明")
                    .popover(isPresented:$showHelp,arrowEdge:.leading) {
                        VStack(alignment:.leading,spacing:12) {
                            Text("让不同颜色参与单色成像").font(.headline)
                            Text("绿色响应按所选细节计算模式重建。RGB混合会从原始采样分别重建红、绿、蓝响应，再按比例合成；改变的是线性RAW，预览与导出共用计算。")
                            Text("窄带模式用于明确使用红、绿或蓝窄带光拍摄的照片。请按实际照明手动选择，不应根据照片内容猜测照明。它会使用对应的真实采样，红蓝采样位置较少，仍需估算缺失位置。")
                            Text("相对比重会归一化为总和100%，总曝光单独调整。本版按文件黑白电平归一化，不自动白平衡或把不同照片直方图拉齐。改变比例仍可能改变某些场景的整体亮度。")
                            Text("这是可控的传感器响应混合，尚未标定为某款实体单色相机的光谱响应，也不能恢复滤色片挡掉的光。")
                            HStack { Spacer(); Button("知道了") { showHelp=false } }
                        }.font(.callout).padding(20).frame(width:365)
                    }
                Spacer()
            }
            if let item=model.selected {
                Text("仅调整当前照片：\(item.url.lastPathComponent)")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
            } else { Text("选择照片后可独立调整响应").font(.caption).foregroundStyle(.secondary) }
            Picker("重建来源",selection:$model.recipe.response_mode) {
                Text(model.recipe.usesLegacyDetail ? "绿色参考（原有模式）" : "绿色响应").tag("green")
                Text("RGB 响应混合").tag("mix")
                if model.recipe.response_mode.hasPrefix("narrow_") { Text("使用下方窄带响应").tag(model.recipe.response_mode) }
            }.labelsHidden().accessibilityLabel("单色重建来源")
            if model.recipe.response_mode == "mix" {
                responseSlider("红色比重",value:$model.recipe.response_red,defaultValue:defaults.response_red,color:.red)
                responseSlider("绿色比重",value:$model.recipe.response_green,defaultValue:defaults.response_green,color:.green)
                responseSlider("蓝色比重",value:$model.recipe.response_blue,defaultValue:defaults.response_blue,color:.blue)
                let total=model.recipe.response_red+model.recipe.response_green+model.recipe.response_blue
                if total>0 {
                    Text(String(format:"实际比例：R %.1f%% · G %.1f%% · B %.1f%%",model.recipe.response_red/total*100,model.recipe.response_green/total*100,model.recipe.response_blue/total*100))
                        .font(.caption).foregroundStyle(.secondary)
                } else { Text("至少保留一个大于零的比重").font(.caption).foregroundStyle(.orange) }
                ParameterResetButton(parameter:"红绿蓝比重整组",defaultDescription:"红25% / 绿50% / 蓝25%",isDefault:responseWeightsAreDefault,title:"整组复位") {
                    model.recipe.response_red=defaults.response_red
                    model.recipe.response_green=defaults.response_green
                    model.recipe.response_blue=defaults.response_blue
                }
            }
            Divider()
            HStack {
                Text("当前照片曝光")
                TextField("EV",value:$model.recipe.response_exposure,format:.number.precision(.fractionLength(2)))
                    .textFieldStyle(.roundedBorder).frame(width:70)
                Text("EV").foregroundStyle(.secondary)
                Spacer(minLength:0)
                ParameterResetButton(parameter:"当前照片曝光",defaultDescription:"0 EV",isDefault:model.recipe.response_exposure == defaults.response_exposure) {
                    model.recipe.response_exposure=defaults.response_exposure
                }
            }
            Slider(value:$model.recipe.response_exposure,in:-6...6).accessibilityLabel("当前照片的RAW响应曝光")
            Text("写入线性RAW，与下方仅供显示的预览亮度分开。提高曝光也会放大噪声，并可能产生高光剪裁。")
                .font(.caption).foregroundStyle(.secondary)
            Text(model.showingReference ? "当前显示绿色参考对照，导出仍使用上方响应设置。" : model.previewBusy ? "正在按当前响应重建…" : model.responseSummary)
                .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
            if model.items.count>1 {
                Menu("批量同步当前响应…") {
                    Button("应用到选中的 \(model.selectedCount) 张") { model.copyCurrentResponse(all:false) }.disabled(model.selectedCount<2)
                    Button("应用到全部 \(model.items.count) 张") { model.copyCurrentResponse(all:true) }
                }.controlSize(.small)
                Text("日常调整仅作用于当前照片；批量导出分别使用各自设置。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }.disabled(model.selected==nil)
    }
    private var responseWeightsAreDefault: Bool {
        model.recipe.response_red == defaults.response_red &&
        model.recipe.response_green == defaults.response_green &&
        model.recipe.response_blue == defaults.response_blue
    }
    private func responseSlider(_ title:String,value:Binding<Double>,defaultValue:Double,color:Color) -> some View {
        VStack(spacing:4) {
            HStack(spacing:8) {
                Text(title)
                Spacer(minLength:0)
                Text(String(format:"%.1f",value.wrappedValue*100)).monospacedDigit().foregroundStyle(.secondary)
                ParameterResetButton(parameter:title,defaultDescription:String(format:"%.0f%%",defaultValue*100),isDefault:value.wrappedValue == defaultValue) {
                    value.wrappedValue=defaultValue
                }
            }
            Slider(value:value,in:0...1).tint(color).accessibilityLabel(title)
        }
    }
}

struct NarrowbandResponseControls: View {
    @ObservedObject var model:AppModel
    @State private var showHelp = false
    private var enabled:Bool { model.recipe.isNarrowband }
    var body:some View {
        VStack(alignment:.leading,spacing:12) {
            HStack {
                Text("窄带纯通道 · 底片翻拍").font(.headline)
                Button { showHelp=true } label: { Image(systemName:"info.circle") }
                    .buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel("窄带纯通道说明")
                    .popover(isPresented:$showHelp,arrowEdge:.leading) {
                        VStack(alignment:.leading,spacing:12) {
                            Text("三张光照，三份独立通道").font(.headline)
                            Text("红光照片只使用R采样，绿光只使用G采样，蓝光只使用B采样。同色插值补齐缺失位置，不借用其他颜色的像素或梯度，不使用RGB引导模型。")
                            Text("输出保留相同的原始空间坐标与完整尺寸。红蓝各只有约四分之一位置是实测值，绿色约二分之一；插值不会增加真实的感光点。")
                            Text("这会去掉软件重建中的跨通道参与，不能消除滤色片自身的光谱重叠。不会自动白平衡、拉齐三张亮度或套用显示伽马。")
                            Text("在NegPy中使用Edit RGB Triplet手动指定R、G、B。单色DNG已没有Bayer颜色身份，自动探测可能把三张都当成同一通道。")
                            HStack { Spacer(); Button("知道了") { showHelp=false } }
                        }.font(.callout).padding(20).frame(width:380)
                    }
                Spacer(minLength:0)
            }
            Toggle("启用独立纯通道",isOn:Binding(get:{enabled},set:{ value in
                if value && model.recipe.detail_mode == "lmmse" {
                    model.recipe.detail_mode = "directional"
                    model.notice = "LMMSE会借助其他颜色采样，不能用于独立纯通道。已切换为方向自适应（D10）。"
                    ExecutionLogStore.shared.record("narrowband_detail_mode_reset",fields:["from":"lmmse","to":"directional","reason":"independent_same_colour_required"])
                }
                model.recipe.response_mode = value ? "narrow_green" : "green"
            }))
            if enabled {
                Text(model.selected.map { "仅调整当前照片："+$0.url.lastPathComponent } ?? "请选择照片")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(2)
                Picker("拍摄光源",selection:Binding(get:{enabled ? model.recipe.response_mode : "narrow_green"},set:{model.recipe.response_mode=$0})) {
                    Text("红光 R").tag("narrow_red");Text("绿光 G").tag("narrow_green");Text("蓝光 B").tag("narrow_blue")
                }.pickerStyle(.segmented)
                if model.recipe.usesLegacyDetail { HStack {
                    Picker("同色插值",selection:$model.recipe.narrow_interpolation) {
                        Text("有界三次（细节优先）").tag("cubic")
                        Text("线性（平滑对照）").tag("linear")
                    }.accessibilityLabel("窄带同色插值")
                    ParameterResetButton(parameter:"窄带插值",defaultDescription:"有界三次",isDefault:model.recipe.narrow_interpolation == "cubic") {
                        model.recipe.narrow_interpolation="cubic"
                    }
                } } else {
                    Text("同色重建使用上方“细节计算模式”："+model.recipe.detailModeTitle)
                        .font(.caption).foregroundStyle(.secondary)
                }
                Text("只保留所选颜色的原始采样，再用同色插值补齐画面；保留全尺寸及原始位置。绿色差异校正与跨颜色LMMSE不参与。")
                    .font(.caption).foregroundStyle(.secondary)
                Text("三张分别选择对应光源。建议曝光0 EV并保持相同裁切和镜头设置；不自动拉齐亮度。")
                    .font(.caption).foregroundStyle(.secondary)
                if model.recipe.response_exposure != 0 {
                    Text("当前照片曝光非0 EV，会改变RGB合成后的色平衡。").font(.caption).foregroundStyle(.orange)
                }
                if model.recipe.lens_correction != nil {
                    Text("已启用镜头校正，将重采样像素。三张需使用一致的几何设置，初次合成建议关闭。").font(.caption).foregroundStyle(.orange)
                }
                Text("导出后缀：_"+(model.recipe.narrowChannel ?? "G")+"_窄带.dng · NegPy中手动指定RGB三张")
                    .font(.caption).foregroundStyle(.secondary)
            } else {
                Text("为RGB三色窄带底片翻拍生成独立单色DNG，与上方普通单色响应分开。").font(.caption).foregroundStyle(.secondary)
            }
        }.disabled(model.selected==nil)
    }
}
