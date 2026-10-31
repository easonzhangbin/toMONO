import SwiftUI
import AppKit
import UniformTypeIdentifiers

/// System materials honor appearance, accessibility and active-window state.
struct NativeGlassControls: ViewModifier {
    var cornerRadius: CGFloat = 16
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    func body(content: Content) -> some View {
        if reduceTransparency {
            content.background(Color(nsColor: .controlBackgroundColor), in: RoundedRectangle(cornerRadius: cornerRadius))
        } else if #available(macOS 26.0, *) {
            content.glassEffect(.regular, in: .rect(cornerRadius: cornerRadius))
        } else {
            content.background(.regularMaterial, in: RoundedRectangle(cornerRadius: cornerRadius))
        }
    }
}

/// Behind-window vibrancy lets side panels respond to the desktop and appearance.
/// Keep this separate from the neutral photo canvas and system glass controls.
struct NativeSidebarBackdrop: View {
    var material: NSVisualEffectView.Material = .sidebar
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    var body: some View {
        Group {
            if reduceTransparency { Color(nsColor: .windowBackgroundColor) }
            else { BehindWindowMaterial(material: material) }
        }.allowsHitTesting(false).accessibilityHidden(true)
    }
}

private struct BehindWindowMaterial: NSViewRepresentable {
    let material: NSVisualEffectView.Material
    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.blendingMode = .behindWindow
        view.state = .followsWindowActiveState
        return view
    }
    func updateNSView(_ view: NSVisualEffectView, context: Context) {
        view.material = material
        view.blendingMode = .behindWindow
        view.state = .followsWindowActiveState
    }
}

struct ContentView: View {
    @ObservedObject var model: AppModel
    @State private var dropTarget = false
    @StateObject private var zoom = PreviewZoom()
    @State private var showInspector = true
    @State private var showQueue = true
    @State private var showDefectHelp = false
    @State private var showPresetHelp = false
    @State private var showPreviewHelp = false
    @State private var showGreenCalibration = false
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(spacing: 0) {
            if !model.startupReady { engineStatus }
            HStack(spacing: 0) {
                if showQueue {
                    queue.frame(width: 240).background { NativeSidebarBackdrop() }
                    Divider()
                }
                preview.frame(maxWidth: .infinity, maxHeight: .infinity)
                if showInspector {
                    Divider()
                    inspector.frame(width: 320).background { NativeSidebarBackdrop() }
                }
            }.frame(maxWidth: .infinity, maxHeight: .infinity)
            statusBar
        }
        .onChange(of: model.recipe) { _, _ in
            if model.recipe.response_mode == "green" && model.recipe.response_exposure == 0 { model.showingReference=false }
            model.updatePreview()
        }
        .toolbar {
            ToolbarItem(placement: .navigation) {
                Button("照片队列", systemImage: "sidebar.left") { showQueue.toggle() }
                    .help("显示或隐藏照片队列")
            }
            ToolbarItem {
                Button("转换设置", systemImage: "sidebar.right") { showInspector.toggle() }
                    .help("显示或隐藏转换设置")
            }
            ToolbarItem {
                Button("执行日志") { openWindow(id: "execution-log") }
            }
            ToolbarItem {
                Button("使用帮助") { openWindow(id: "help") }
            }
            ToolbarItem {
                Button("请我喝咖啡", systemImage: "cup.and.saucer") { openWindow(id: "support") }
                    .help("自愿支持 toMONO 的开发与影像研究")
            }
        }
        .frame(minWidth: 1000, minHeight: 640)
        .onOpenURL { url in if !model.running { model.add([url]) } }
        .onDrop(of: [UTType.fileURL.identifier], isTargeted: $dropTarget) { providers in
            guard !model.running else { return false }
            for provider in providers {
                _ = provider.loadObject(ofClass: URL.self) { url, _ in
                    if let url { DispatchQueue.main.async { model.add([url]) } }
                }
            }
            return true
        }
        .alert("提示", isPresented: Binding(get: { model.notice != nil }, set: { if !$0 { model.notice = nil } })) {
            Button("好") { model.notice = nil }
        } message: { Text(model.notice ?? "") }
    }

    private var engineStatus: some View {
        HStack(spacing:10) {
            if let error = model.startupError {
                Image(systemName:"exclamationmark.triangle").foregroundStyle(.orange)
                Text(error).font(.callout).textSelection(.enabled)
                Spacer(minLength:8)
                Button("重新检查",action:model.startStartupCheck)
                Button("执行日志") { openWindow(id:"execution-log") }
            } else {
                ProgressView().controlSize(.small)
                Text("正在后台检查转换引擎与镜头数据库…").font(.caption).foregroundStyle(.secondary)
                Spacer(minLength:0)
            }
        }.padding(.horizontal,16).padding(.vertical,8).background(.bar)
    }

    private var queue: some View {
        VStack(spacing: 0) {
            HStack {
                Text("照片队列").font(.headline); Spacer()
                Text("\(model.items.count)").foregroundStyle(.secondary)
            }.padding(.horizontal, 16).frame(height: 54)
            Button("添加照片…",systemImage:"plus",action:model.chooseFiles)
                .buttonStyle(.bordered).controlSize(.large)
                .frame(maxWidth:.infinity).padding(.horizontal,12).padding(.bottom,10).disabled(model.running)
            List(selection: Binding(get: { model.selectedIDs }, set: { model.setSelection($0) })) {
                ForEach(model.items) { item in
                    HStack(spacing:9) {
                        if let image = item.thumbnail {
                            Image(nsImage:image).resizable().scaledToFit().frame(width:48,height:48).clipShape(RoundedRectangle(cornerRadius:4))
                        } else { Image(systemName:"photo").frame(width:48,height:48).foregroundStyle(.tertiary) }
                        VStack(alignment: .leading, spacing: 7) {
                            Text(item.url.lastPathComponent).lineLimit(1).fontWeight(.medium)
                            Label(item.displayStatus, systemImage: statusIcon(item.displayStatus))
                                .font(.caption).foregroundStyle(statusColor(item.displayStatus))
                        }
                    }.padding(.vertical,5).tag(item.id).onAppear { model.loadQueueThumbnail(item.id) }
                }
            }
            .listStyle(.sidebar)
            .scrollContentBackground(.hidden)
            .disabled(model.running)
            Text("已选 \(model.selectedCount) / \(model.items.count) 张 · ⌘ / ⇧ 多选")
                .font(.caption).foregroundStyle(.secondary).padding(.horizontal,12).padding(.top,8)
            HStack {
                Button("移除选中", systemImage: "minus", action: model.removeSelected)
                    .disabled(model.running || model.selectedCount == 0)
                Spacer()
            }.padding(12)
            VStack(alignment:.leading,spacing:10) {
                Text("导出").font(.headline)
                Button("保存位置…",systemImage:"folder",action:model.chooseFolder).disabled(model.running)
                Text(model.folder?.lastPathComponent ?? "尚未选择保存位置")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(2).help(model.folder?.path ?? "首次导出时也可选择")
                Button(model.running ? "正在导出…" : "导出选中照片（\(model.selectedCount)）",systemImage:"square.and.arrow.up",action:model.start)
                    .buttonStyle(.borderedProminent).controlSize(.large)
                    .disabled(model.running || model.selectedCount == 0 || !model.startupReady)
                Button("导出全部照片（\(model.items.count)）",action:model.startAll)
                    .disabled(model.running || model.items.isEmpty || !model.startupReady)
                if model.running {
                    ProgressView(value:model.fraction)
                    Button("取消导出",action:model.cancel)
                }
            }.padding(14).frame(maxWidth:.infinity,alignment:.leading)
                .modifier(NativeGlassControls()).padding(10)
        }
    }

    private var preview: some View {
        VStack(spacing: 0) {
            HStack {
                Text(model.selected?.url.lastPathComponent ?? "预览").font(.headline).lineLimit(1)
                Spacer()
                if model.selected != nil {
                    if model.recipe.response_mode != "green" || model.recipe.response_exposure != 0 {
                        Button(model.showingReference ? "返回当前响应" : "对照绿色参考") {
                            model.showingSource=false;model.showingReference.toggle();model.updatePreview()
                        }.controlSize(.small).help("保持缩放与观察位置，对照原有绿色重建；不会改变导出设置")
                    }
                    Toggle("彩色原图", isOn: $model.showingSource).toggleStyle(.switch).controlSize(.small)
                        .onChange(of: model.showingSource) { _, value in if value { model.showingReference=false };model.updatePreview() }
                }
            }.padding(.horizontal, 12).frame(height: 42)
                .modifier(NativeGlassControls(cornerRadius: 12)).padding(10)
            ZStack {
                // Keep image viewing neutral; translucent material belongs to controls.
                Color(nsColor: .underPageBackgroundColor)
                if let image = model.preview {
                    ZoomablePreview(image: image, identity: model.selection, zoom: zoom).brightness(model.brightness)
                } else if model.selected != nil {
                    VStack(spacing: 14) {
                        if model.previewBusy { ProgressView() }
                        else { Image(systemName: "photo.badge.exclamationmark").font(.largeTitle).foregroundStyle(.secondary) }
                        Text(model.previewMessage).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
                    }.padding(24)
                } else {
                    VStack(spacing: 16) {
                        Image(systemName: "photo.on.rectangle.angled")
                            .font(.system(size: 44)).foregroundStyle(.tertiary).accessibilityHidden(true)
                        Text("将 RAW 拖到这里").font(.title2.weight(.medium))
                        Text("或点击左侧“添加照片”").foregroundStyle(.secondary)
                        Button("查看快速开始") { openWindow(id: "help") }.buttonStyle(.link)
                    }
                }
            }
            .overlay { if dropTarget { RoundedRectangle(cornerRadius: 14).stroke(.tint, lineWidth: 3).padding(8) } }
            .overlay(alignment: .topLeading) {
                if model.preview != nil, !model.previewMessage.isEmpty {
                    HStack(spacing: 8) {
                        if model.previewBusy { ProgressView().controlSize(.small) }
                        Text(model.previewMessage).font(.caption)
                    }.padding(9).modifier(NativeGlassControls(cornerRadius: 18)).padding(12)
                }
            }
            .safeAreaInset(edge: .bottom) {
                VStack(spacing: 9) {
                    HStack(spacing: 8) {
                        Button("适合窗口") { zoom.fit() }.controlSize(.small)
                        Button("100%") { zoom.actual() }.controlSize(.small)
                            .help("一个图像像素对应一个屏幕物理像素；彩色原图为内嵌预览像素")
                        Button { zoom.step(1 / 1.5) } label: { Image(systemName:"minus.magnifyingglass") }.help("缩小")
                        Text("\(Int((zoom.scale * 100).rounded()))%").font(.caption.monospacedDigit()).frame(minWidth:40)
                        Button { zoom.step(1.5) } label: { Image(systemName:"plus.magnifyingglass") }.help("放大，可拖动画面或用触控板捏合")
                        Spacer(minLength:0)
                    }
                    HStack(spacing: 10) {
                        Text("预览亮度").font(.caption)
                        Slider(value: $model.brightness, in: -0.5...0.5)
                            .frame(minWidth:50,maxWidth:160).accessibilityLabel("预览亮度，仅影响显示")
                        ParameterResetButton(parameter:"预览亮度",defaultDescription:"0（仅影响显示）",isDefault:model.brightness == 0) {
                            model.brightness = 0
                        }
                        Spacer(minLength:0)
                        Text("仅影响显示").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(12).modifier(NativeGlassControls()).padding(12)
            }
            if let selected = model.selected, !selected.displayDetail.isEmpty {
                HStack(alignment: .top) {
                    Text(selected.displayDetail).font(.caption)
                        .foregroundStyle(selected.status == "失败" ? .red : .secondary).textSelection(.enabled)
                    Spacer()
                    if selected.output != nil { Button("在访达中显示", action: model.reveal) }
                }.padding(12).modifier(NativeGlassControls()).padding(.horizontal,12).padding(.bottom,10)
            }
        }.frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var statusBar: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text(model.phase).font(.callout).lineLimit(1)
                Text("保存至：\(model.folder?.path ?? "请选择保存位置")")
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
            }
            Spacer()
            Text(AppBrand.multilineTagline)
                .font(.caption).foregroundStyle(.secondary).lineSpacing(2)
                .multilineTextAlignment(.trailing).fixedSize(horizontal:false,vertical:true)
                .frame(maxWidth:420,alignment:.trailing)
                .accessibilityLabel(AppBrand.tagline)
        }.padding(.horizontal, 16).padding(.vertical, 11)
            .background { NativeSidebarBackdrop(material: .titlebar) }
            .overlay(alignment:.top) { Divider() }
    }

    private var inspector: some View {
        VStack(spacing: 0) {
            HStack { Text("转换设置").font(.headline); Spacer() }.padding(.horizontal, 16).frame(height: 54)
            HistogramPanel(model:model).padding(12).modifier(NativeGlassControls()).padding(.horizontal,12).padding(.bottom,12)
            Divider()
            ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                DetailComputationControls(model:model).padding(12).modifier(NativeGlassControls())
                ResponseControls(model:model).padding(12).modifier(NativeGlassControls())
                NarrowbandResponseControls(model:model).padding(12).modifier(NativeGlassControls())
                Divider()
                VStack(alignment:.leading,spacing:10) {
                    Text("当前相机与设置预设").font(.headline)
                    if let camera = model.selected?.camera {
                        Text(camera.displayName).fontWeight(.medium).textSelection(.enabled)
                        Text(camera.serial.map { "机身序列号：" + $0 } ?? "未读取到机身序列号")
                            .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    } else {
                        Text(model.selected == nil ? "添加照片后显示相机信息" : model.selected?.cameraChecked == true ? "未识别到相机信息" : "正在读取相机信息…")
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    HStack(spacing: 10) {
                        Menu("相机设置预设") {
                            Button("载入设置预设…",action:model.loadRecipe)
                            Button("保存为相机预设…",action:model.saveRecipe)
                            Divider()
                            Button("恢复默认设置",action:model.restoreDefaultSettings)
                        }.fixedSize()
                        Button { showPresetHelp = true } label: { Image(systemName:"info.circle") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                            .accessibilityLabel("设置预设的用途")
                            .help("说明哪些设置可以保存，以及何时需要使用")
                            .popover(isPresented:$showPresetHelp,arrowEdge:.leading) { PresetHelpPopover { showPresetHelp = false } }
                        Spacer(minLength:0)
                    }
                    Text(model.presetStatus).font(.caption).foregroundStyle(.secondary)
                    if let warning = model.presetScopeWarning { Text(warning).font(.caption).foregroundStyle(.orange) }
                    Text("细节计算模式、响应、绿色校正、坏点表、镜头校正与输出选项会一并保存。默认设置无需另存预设。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Divider()
                Text("预设包含的转换参数").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
                if model.recipe.usesLegacyDetail { VStack(alignment: .leading, spacing: 12) {
                    Picker("绿色插值", selection: $model.recipe.algorithm) {
                        Text("双三次（兼容）").tag("Bicubic")
                        Text("边缘自适应（实验）").tag("EdgeAware")
                        Text("自动适配（实验）").tag("Auto")
                    }.disabled(!model.recipe.usesGreen)
                    Text(model.reconstructionSummary).foregroundStyle(.secondary)
                    Text(model.recipe.usesGreen ? "绿色沿所选算法重建；RGB模式的红蓝使用保留实测位置的有界三次插值。其他排列使用同色格点估算。" : "当前窄带模式直接重建对应通道，绿色插值和绿色差异校正不参与最终输出。")
                        .font(.caption).foregroundStyle(.secondary)

                }
                Divider() }
                DisclosureGroup("高级：绿色采样校正",isExpanded:$showGreenCalibration) {
                VStack(alignment: .leading, spacing: 12) {
                    Picker("模式", selection: $model.recipe.green_mode) {
                        Text("自动").tag("auto"); Text("手动").tag("manual"); Text("关闭").tag("off")
                    }.pickerStyle(.segmented)
                    if model.recipe.green_mode == "manual" {
                        HStack {
                            Text("差异阈值")
                            TextField("阈值", value: $model.recipe.compensation, format: .number.precision(.fractionLength(6)))
                                .textFieldStyle(.roundedBorder)
                                .frame(minWidth:85)
                            ParameterResetButton(parameter:"绿色差异阈值",defaultDescription:"1.231",isDefault:model.recipe.compensation == RecipeDocument().compensation) {
                                model.recipe.compensation = RecipeDocument().compensation
                            }
                        }
                        // A stepped SwiftUI Slider draws one native tick per step on macOS.
                        // Keep coarse adjustment continuous; the field retains exact precision.
                        Slider(value: $model.recipe.compensation, in: 1.005...1.249)
                            .accessibilityLabel("绿色差异阈值")
                        Toggle("优先红色区域", isOn: $model.recipe.focus_red)
                        Toggle("优先蓝色区域", isOn: $model.recipe.focus_blue)
                    } else if model.recipe.green_mode == "auto" {
                        Text("根据文件参数计算白点，应用当前自动校正预设。").font(.caption).foregroundStyle(.secondary)
                    }
                    Text("处理两类绿色采样的差异，不会整体提亮绿色。").font(.caption).foregroundStyle(.secondary)
                    Text(model.previewBusy ? "正在按当前设置计算校正数量…" : model.greenCorrectionSummary)
                        .font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
                    Text("校正少量位置时，整体画面和直方图可能几乎不变。建议放大到100%–400%检查局部纹理。")
                        .font(.caption).foregroundStyle(.secondary)
                    if model.recipe.green_mode == "manual" {
                        Text("阈值越低越容易触发，越高越保守。").font(.caption).foregroundStyle(.secondary)
                    }
                }.padding(.top,10).disabled(!model.recipe.usesGreen)
                }
                Divider()
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 8) {
                        Text("缺陷像素修复").font(.headline)
                        Button { showDefectHelp = true } label: { Image(systemName:"info.circle") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                            .accessibilityLabel("缺陷像素修复说明")
                            .help("了解暗场与坏点坐标表的区别")
                            .popover(isPresented:$showDefectHelp,arrowEdge:.leading) {
                                DefectHelpPopover { showDefectHelp = false }
                            }
                        Spacer(minLength:0)
                    }
                    if let profile = model.recipe.defect_profile {
                        Text("\(profile.make) \(profile.model) · \(profile.pixels.count) 个坐标").font(.caption)
                        Button("关闭缺陷图修复") { model.recipe.defect_profile = nil }
                    } else { Text("未启用额外修复").foregroundStyle(.secondary) }
                    Button("载入坏点坐标表…",action:model.loadDefectProfile)
                    Text(model.recipe.isNarrowband ? "仅修复坐标表中所选通道的已确认采样位置；使用同色邻居，核对机型与完整RAW尺寸。" : !model.recipe.usesLegacyDetail && model.recipe.response_mode == "mix" ? "仅修复当前混合中比重大于零的通道；使用同色邻居，核对机型与完整RAW尺寸。此处不直接载入暗场照片。" : "仅修复坐标表中已确认的绿色采样位置，并核对机型与完整RAW尺寸。此处不直接载入暗场照片。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Divider()
                LensCorrectionSection(model:model).padding(12).modifier(NativeGlassControls())
                Divider()
                VStack(alignment: .leading, spacing: 12) {
                    Text("保留信息").font(.headline)
                    Toggle("拍摄时间、曝光与镜头信息", isOn: $model.recipe.preserve_capture)
                    Toggle("作者、版权与描述", isOn: $model.recipe.preserve_description)
                    Text("拍摄信息可能包含 GPS、机身和镜头序列号；不会继承彩色显影设置。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Divider()
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing:8) {
                        Text("预览与显影外观").font(.headline)
                        Button { showPreviewHelp = true } label: { Image(systemName:"info.circle") }
                            .buttonStyle(.plain).foregroundStyle(.secondary)
                            .accessibilityLabel("预览与 Camera Raw 的区别")
                            .popover(isPresented:$showPreviewHelp,arrowEdge:.leading) {
                                VStack(alignment:.leading,spacing:12) {
                                    Text("保持预览的明暗关系").font(.headline)
                                    Text("这里是线性参考预览：扣除黑电平，按白电平归一化，再应用所选伽马。导出的 RAW 保留线性数据。")
                                    Text("Camera Raw 即使明暗滑块归零，也会应用默认色调处理。开启匹配后，DNG 内会写入 toMONO 校准的初始显影曲线，并关闭额外锐化，使打开时的明暗更接近这里的预览；不会修改线性 RAW 像素。")
                                    Text("已在 Camera Raw 18.7 验证。不同版本、其他显影软件或重置显影设置后仍可能不同。预览亮度滑块仅供观察，不会写入；匹配会包含所选预览伽马。")
                                    HStack { Spacer(); Button("知道了") { showPreviewHelp = false } }
                                }.font(.callout).fixedSize(horizontal:false,vertical:true).padding(20).frame(width:360)
                            }
                        Spacer()
                    }
                    Text("线性参考预览").foregroundStyle(.secondary)
                    HStack(spacing:8) {
                        Picker("预览伽马", selection: $model.recipe.preview_gamma) {
                            Text("2.2").tag(2.2); Text("1.8").tag(1.8)
                        }
                        ParameterResetButton(parameter:"预览伽马",defaultDescription:"2.2",isDefault:model.recipe.preview_gamma == RecipeDocument().preview_gamma) {
                            model.recipe.preview_gamma = RecipeDocument().preview_gamma
                        }
                    }
                    Toggle("匹配预览明暗（Camera Raw）",isOn:$model.recipe.match_preview)
                    Text(model.recipe.match_preview ? "将参考显影曲线与伽马外观写入 DNG，保留线性 RAW。已在 Camera Raw 18.7 验证；重置显影设置后会恢复该软件的默认外观。" : "由显影软件决定默认明暗。预览伽马仅供显示，打开 DNG 后的反差与亮度可能不同。")
                        .font(.caption).foregroundStyle(.secondary)
                }
            }.font(.callout).padding(20).disabled(model.running)
            }
        }
    }

    private func statusIcon(_ value: String) -> String {
        value.hasPrefix("已保存") ? "checkmark.circle.fill" : value == "失败" ? "exclamationmark.circle.fill" : value == "处理中" ? "arrow.triangle.2.circlepath" : "circle"
    }
    private func statusColor(_ value: String) -> Color {
        value == "已保存" ? .green : value == "失败" ? .red : value.contains("提示") ? .orange : .secondary
    }
}

struct DefectHelpPopover: View {
    let dismiss: () -> Void
    var body: some View {
        VStack(alignment:.leading,spacing:13) {
            Text("缺陷像素修复是什么？").font(.headline)
            Text("它根据已确认的像素坐标，用周围同色采样估算异常位置，再进行单色重建。绿色响应修复绿色，窄带纯通道修复所选颜色；新细节模式的RGB混合修复比重大于零的通道，旧模式沿用绿色修复。默认关闭，不会自动把图像细节识别为坏点。")
            Divider()
            Text("暗场照片和坐标表有什么区别？").font(.subheadline.weight(.semibold))
            Text("盖镜头盖拍摄的暗场可帮助找持续发亮的热像素。偏暗或不响应的坏点，需要均匀亮场检查；通常应结合多张照片确认，避免把真实细节当作坏点。")
            Text("“载入坏点坐标表”目前只接受JSON坐标表，不能直接载入黑照片，也不会扣除整张暗场。本版尚未提供从暗场自动生成坐标表的功能。")
            Divider()
            Text("什么时候使用？").font(.subheadline.weight(.semibold))
            Text("确认某些位置持续异常并已有可靠坐标表时再启用。坐标必须与相机型号和完整RAW尺寸吻合；更换读取模式或裁切后需重新核对。没有坐标表时保持关闭，仍可正常转换。")
            Text("格式与处理范围见“使用帮助 → 缺陷像素修复”。").font(.caption).foregroundStyle(.secondary)
            HStack { Spacer(); Button("知道了",action:dismiss).keyboardShortcut(.defaultAction) }
        }.font(.callout).fixedSize(horizontal:false,vertical:true).padding(20).frame(width:400)
    }
}

struct PresetHelpPopover: View {
    let dismiss: () -> Void
    var body: some View {
        VStack(alignment:.leading,spacing:13) {
            Text("设置预设有什么用？").font(.headline)
            Text("预设是一份转换设置的快照，不包含照片，也不是黑白风格滤镜。一直使用默认设置时，可以不保存。")
            Text("适合反复使用同一组设置：例如一批照片的手动绿色校正、比较两种插值方法，或重复使用某台相机的坏点坐标表。")
            Divider()
            Text("会保存：细节计算模式、单色响应与曝光、绿色校正及阈值、输出预览伽马、匹配预览明暗开关、信息保留开关，以及可选的坏点坐标表和镜头校正。")
            Text("不会保存：照片、输出文件夹、预览亮度、缩放比例和观察位置。")
            Text("保存时建议用相机型号和机身序列号命名，读不到序列号时仅用型号；文件中也会记录来源相机。普通参数可跨机型使用，坏点表不能套用另一机身。")
            Text("载入未记录细节计算模式的旧预设时，会保留原有模式；新照片默认使用频域精细。")
            Text("“保存为相机预设”生成JSON；“载入设置预设”恢复参数。载入后刷新模拟，正式输出需再点击“开始转换”。").foregroundStyle(.secondary)
            HStack { Spacer(); Button("知道了",action:dismiss).keyboardShortcut(.defaultAction) }
        }.font(.callout).fixedSize(horizontal:false,vertical:true).padding(20).frame(width:380)
    }
}

struct HelpCommands: Commands {
    @Environment(\.openWindow) private var openWindow
    var body: some Commands {
        CommandGroup(replacing: .help) {
            Button("toMONO 使用帮助") { openWindow(id: "help") }.keyboardShortcut("?", modifiers: .command)
            Button("执行日志") { openWindow(id: "execution-log") }.keyboardShortcut("l", modifiers: [.command, .option])
            Divider()
            Button("请我喝咖啡") { openWindow(id: "support") }
        }
    }
}

@main struct ToMONOApp: App {
    @StateObject private var model = AppModel()
    @NSApplicationDelegateAdaptor(AppLifecycle.self) private var lifecycle
    var body: some Scene {
        mainWindow
        Window("toMONO 使用帮助", id: "help") {
            HelpView().environment(\.locale, Locale(identifier: "zh_Hans"))
        }.defaultSize(width: 880, height: 680).windowToolbarStyle(.unified)
        Window("toMONO 执行日志", id: "execution-log") {
            ExecutionLogView().environment(\.locale, Locale(identifier: "zh_Hans"))
        }.defaultSize(width: 1050, height: 720).windowToolbarStyle(.unified)
        Window("支持 toMONO", id: "support") {
            SupportView().environment(\.locale, Locale(identifier: "zh_Hans"))
        }.defaultSize(width: 520, height: 820).windowToolbarStyle(.unified)
    }
    private var mainWindow: some Scene {
        Window("toMONO", id:"workspace") {
            ContentView(model:model).environment(\.locale, Locale(identifier: "zh_Hans"))
        }.defaultSize(width: 1200, height: 780).windowToolbarStyle(.unifiedCompact(showsTitle: true))
             .commands {
                CommandGroup(replacing:.newItem) {
                    Button("添加照片…",action:model.chooseFiles).keyboardShortcut("o").disabled(model.running)
                    Button("选择保存位置…",action:model.chooseFolder).disabled(model.running)
                    Button("导出选中照片",action:model.start).keyboardShortcut(.return,modifiers:.command).disabled(model.running || model.selectedCount == 0 || !model.startupReady)
                    Button("导出全部照片",action:model.startAll).keyboardShortcut(.return,modifiers:[.command,.shift]).disabled(model.running || model.items.isEmpty || !model.startupReady)
                }
                CommandGroup(replacing:.appInfo) {
                    Button("关于 toMONO") {
                        NSApp.orderFrontStandardAboutPanel(options:[.applicationName:"toMONO",.applicationVersion:AppBrand.releaseLabel,.version:"1"])
                    }
                }
                HelpCommands()
            }
    }
}
