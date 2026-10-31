import SwiftUI

struct ResearchReference: Decodable, Identifiable {
    let id: String
    let category: String
    let title: String
    let authors: String
    let year: String?
    let version: String?
    let url: String
    let codeURL: String?
    let function: String
    let relationship: String
    let materialStatus: String
    let referenceIDs: [String]?

    var searchableText: String {
        ([id, title, authors, year ?? "", version ?? "", function, relationship, materialStatus]
            + (referenceIDs ?? [])).joined(separator: " ")
    }
    var categoryTitle: String {
        switch category {
        case "integrated": return "已使用的组件与算法"
        case "experiment": return "本地实验候选"
        default: return "仅作研究参考"
        }
    }
    var sourceURL: URL? { Self.webURL(url) }
    var projectURL: URL? { codeURL.flatMap(Self.webURL) }
    private static func webURL(_ text: String) -> URL? {
        guard let value = URL(string: text), let scheme = value.scheme,
              scheme == "https" || scheme == "http" else { return nil }
        return value
    }
}

struct ResearchCatalog: Decodable {
    let schema: Int
    let updated: String
    let introduction: [String]
    let entries: [ResearchReference]

    static let shared: ResearchCatalog? = {
        guard let url = Bundle.main.url(forResource: "ResearchReferences", withExtension: "json"),
              let data = try? Data(contentsOf: url) else { return nil }
        return try? JSONDecoder().decode(ResearchCatalog.self, from: data)
    }()
    static func references(_ ids: [String]) -> [ResearchReference] {
        ids.compactMap { id in shared?.entries.first(where: { $0.id == id }) }
    }
    static var searchableText: String { shared?.entries.map(\.searchableText).joined(separator: " ") ?? "" }
}

struct ResearchReferencesView: View {
    @Binding var search: String
    private let categories: [(id: String, title: String, note: String)] = [
        ("integrated", "已使用的组件与算法", "随当前软件使用的读取、计算、输出和界面基础，以及已接入的细节模式。具体实现关系以每条记录为准。"),
        ("experiment", "本地实验候选", "在独立研究工具中做过实测的候选，不代表已进入软件默认重建核心。"),
        ("reference", "仅作研究参考", "提供方法、数据或评价依据。阅读或引用论文，不表示已采用其原始代码、模型或结论。")
    ]

    private func matches(_ entry: ResearchReference) -> Bool {
        search.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
        entry.searchableText.localizedCaseInsensitiveContains(search)
    }
    private var visible: [ResearchReference] { ResearchCatalog.shared?.entries.filter(matches) ?? [] }

    var body: some View {
        if let catalog = ResearchCatalog.shared {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    Text("技术与研究来源").font(.title2.weight(.semibold))
                    ForEach(catalog.introduction, id: \.self) { Text($0).font(.callout).foregroundStyle(.secondary) }
                    TextField("搜索标题、作者、功能或来源编号", text: $search)
                        .textFieldStyle(.roundedBorder)
                        .accessibilityLabel("搜索技术与研究来源")
                    Text("资料记录：\(catalog.updated) · 文字可离线阅读 · 打开链接需要联网")
                        .font(.caption).foregroundStyle(.secondary)
                    Text(search.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty ? "共收录 \(catalog.entries.count) 项技术来源" : "显示 \(visible.count) / \(catalog.entries.count) 项技术来源")
                        .font(.caption).foregroundStyle(.secondary)
                    if visible.isEmpty {
                        ContentUnavailableView("没有匹配的技术来源", systemImage: "doc.text.magnifyingglass")
                    } else {
                        ForEach(categories, id: \.id) { category in
                            let entries = visible.filter { $0.category == category.id }
                            if !entries.isEmpty {
                                VStack(alignment: .leading, spacing: 10) {
                                    Text(category.title).font(.headline)
                                    Text(category.note).font(.caption).foregroundStyle(.secondary)
                                    ForEach(entries) { entry in ResearchReferenceCard(entry: entry) }
                                }
                            }
                        }
                    }
                }
                .textSelection(.enabled)
                .padding(24)
                .frame(maxWidth: 800, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .leading)
            }
            .accessibilityIdentifier("research-sources-page")
        } else {
            ContentUnavailableView("技术来源资料暂不可用", systemImage: "doc.text",
                                   description: Text("请使用包含完整帮助资源的构建版本。"))
        }
    }
}

private struct ResearchReferenceCard: View {
    let entry: ResearchReference

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(entry.title).font(.subheadline.weight(.semibold))
            Text([entry.authors, entry.year, entry.version.map { "版本 \($0)" }]
                .compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · "))
                .font(.caption).foregroundStyle(.secondary)
            Text("对应功能：\(entry.function)").font(.callout)
            Text("实现关系：\(entry.relationship)").font(.callout)
            Text("材料状态：\(entry.materialStatus)").font(.caption).foregroundStyle(.secondary)
            HStack(spacing: 16) {
                Text(entry.id).font(.caption.monospaced()).foregroundStyle(.secondary)
                if let url = entry.sourceURL { Link("原始资料", destination: url) }
                if let url = entry.projectURL { Link("代码 / 项目", destination: url) }
            }.font(.caption)
            if let ids = entry.referenceIDs, !ids.isEmpty {
                ResearchReferenceLinks(ids: ids, showsHeading: false)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

struct ResearchReferenceLinks: View {
    let ids: [String]
    var showsHeading = true
    private var entries: [ResearchReference] { ResearchCatalog.references(ids) }

    var body: some View {
        if !entries.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                if showsHeading {
                    Divider()
                    Text("相关技术与研究来源").font(.subheadline.weight(.semibold))
                    Text("实验候选与参考论文不等于当前默认算法；完整实现关系见“技术与研究来源”。")
                        .font(.caption).foregroundStyle(.secondary)
                }
                ForEach(entries) { entry in
                    VStack(alignment: .leading, spacing: 3) {
                        if let url = entry.sourceURL {
                            Link(destination: url) { Text("[\(entry.id)] \(entry.title)").multilineTextAlignment(.leading) }
                        } else { Text("[\(entry.id)] \(entry.title)") }
                        Text(entry.categoryTitle + " · " + entry.relationship)
                            .foregroundStyle(.secondary)
                    }.font(.caption)
                }
            }
        }
    }
}
