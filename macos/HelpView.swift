import SwiftUI
import AppKit

struct HelpTopic: Decodable, Identifiable {
    let id: String
    let title: String
    let symbol: String
    let paragraphs: [String]
    let steps: [String]?
    let tips: [String]?
    let referenceIDs: [String]?
    var searchableText: String {
        let text = ([title] + paragraphs + (steps ?? []) + (tips ?? [])).joined(separator: " ")
        if id == "research-sources" { return text + " " + ResearchCatalog.searchableText }
        return text + " " + ResearchCatalog.references(referenceIDs ?? []).map(\.searchableText).joined(separator: " ")
    }
}

struct HelpView: View {
    @State private var selection: String? = "quickstart"
    @State private var search = ""
    private let topics: [HelpTopic] = {
        guard let url = Bundle.main.url(forResource: "HelpContent", withExtension: "json"),
              let data = try? Data(contentsOf: url),
              let result = try? JSONDecoder().decode([HelpTopic].self, from: data) else { return [] }
        return result
    }()
    private var filtered: [HelpTopic] { topics.filter { search.isEmpty || $0.searchableText.localizedCaseInsensitiveContains(search) } }

    var body: some View {
        HStack(spacing: 0) {
            VStack(spacing: 0) {
                TextField("搜索使用帮助", text: $search).textFieldStyle(.roundedBorder).padding(12)
                List(filtered, selection: $selection) { topic in
                    Label(topic.title, systemImage: topic.symbol).tag(topic.id)
                }.listStyle(.sidebar).scrollContentBackground(.hidden)
            }.frame(width: 220).background(.regularMaterial)
                .onChange(of: search) { _, _ in
                    if !filtered.contains(where: { $0.id == selection }) { selection = filtered.first?.id }
                }
            Divider()
            if let topic = topics.first(where: { $0.id == selection }) {
                if topic.id == "donate" {
                    SupportView()
                } else if topic.id == "research-sources" {
                    ResearchReferencesView(search: $search)
                } else if topic.id == "licenses" {
                    VStack(alignment: .leading, spacing: 12) {
                        Text(topic.title).font(.largeTitle.weight(.semibold)).padding([.top, .horizontal], 24)
                        Text(topic.paragraphs.joined(separator: "\n")).font(.callout).padding(.horizontal, 24)
                        LicenseTextView().padding([.horizontal, .bottom], 16)
                    }
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 20) {
                            Text(topic.title).font(.largeTitle.weight(.semibold))
                            if topic.id == "principles" {
                                ReconstructionPrinciplesDiagram()
                            }
                            ForEach(Array(topic.paragraphs.enumerated()), id: \.offset) { _, paragraph in
                                Text(.init(paragraph)).lineSpacing(5)
                            }
                            if let steps = topic.steps {
                                ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
                                    HStack(alignment: .top, spacing: 14) {
                                        Text("\(index + 1)").font(.headline).foregroundStyle(.tint).frame(width: 24)
                                        Text(.init(step)).frame(maxWidth: .infinity, alignment: .leading).lineSpacing(5)
                                    }
                                }
                            }
                            if let tips = topic.tips {
                                Divider()
                                ForEach(tips, id: \.self) { Text(.init($0)).font(.callout).foregroundStyle(.secondary).lineSpacing(4) }
                            }
                            ResearchReferenceLinks(ids: topic.referenceIDs ?? [])
                            Spacer(minLength: 12)
                        }.font(.body).textSelection(.enabled).padding(28).frame(maxWidth: 720, alignment: .leading)
                    }.id(topic.id)
                }
            } else {
                ContentUnavailableView(search.isEmpty ? "使用帮助暂不可用" : "没有匹配的帮助", systemImage: "book.closed")
            }
        }
        .navigationTitle("toMONO 使用帮助")
        .navigationSubtitle("离线使用 · 简体中文")
        .frame(minWidth: 760, minHeight: 560)
    }
}

private struct ReconstructionPrinciplesDiagram: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 18) {
                Grid(horizontalSpacing: 4, verticalSpacing: 4) {
                    GridRow { sample("红", .red); sample("绿", .green) }
                    GridRow { sample("绿", .green); sample("蓝", .blue) }
                }
                .accessibilityElement(children: .ignore)
                .accessibilityLabel("典型拜耳排列：一个红色、两个绿色、一个蓝色采样")
                Image(systemName: "arrow.right").foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 6) {
                    Text("从 RAW 实测采样开始").font(.headline)
                    Text("按用途选择重建路径，输出线性单通道 DNG")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
            Divider()
            path("绿色参考", detail: "从绿色采样补齐；按选择执行绿色差异校正", color: .green)
            path("RGB 响应混合", detail: "三色分别重建，再按比例线性合成", color: .secondary)
            path("窄带纯通道", detail: "按拍摄光源只选 R、G 或 B，用同色采样补齐", color: .blue)
            Divider()
            VStack(alignment: .leading, spacing: 6) {
                Text("三条路径共用细节计算模式").font(.callout.weight(.semibold))
                Text("频域精细（C01，默认） · 频域限幅（D11） · 方向自适应（D10）")
                    .font(.callout)
                Text("新核适用于直接 2×2 Bayer；D10 的红蓝使用有界三次。窄带跳过绿色差异校正。")
                    .font(.caption).foregroundStyle(.secondary)
                Text("其他普通输入保留兼容回退并记录原因；旧预设保留原有算法。")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Text("插值补齐输出位置，不会增加真实感光点，也不会移除传感器上的滤色片。")
                .font(.caption).foregroundStyle(.secondary)
        }
        .padding(16).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        .accessibilityLabel("三种单色重建路径")
    }
    private func sample(_ label: String, _ color: Color) -> some View {
        Text(label).font(.callout.weight(.semibold)).frame(width: 40, height: 32)
            .background(color.opacity(0.22), in: RoundedRectangle(cornerRadius: 6))
    }
    private func path(_ title: String, detail: String, color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.callout.weight(.semibold)).foregroundStyle(color)
            Text(detail).font(.callout).foregroundStyle(.secondary)
        }
    }
}

private struct LicenseTextView: NSViewRepresentable {
    func makeNSView(context: Context) -> NSScrollView {
        let scroll = NSTextView.scrollableTextView()
        let text = scroll.documentView as! NSTextView
        text.isEditable = false; text.isRichText = false
        text.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        text.textContainerInset = NSSize(width: 14, height: 14)
        text.textColor = .textColor; text.backgroundColor = .textBackgroundColor
        text.setAccessibilityLabel("第三方组件与许可原文")
        if let url = Bundle.main.url(forResource: "ThirdPartyNotices", withExtension: "txt"), let content = try? String(contentsOf: url, encoding: .utf8) {
            text.string = content
        } else { text.string = "未能读取许可文件，请重新构建应用。" }
        return scroll
    }
    func updateNSView(_ nsView: NSScrollView, context: Context) {}
}
