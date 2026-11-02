import SwiftUI
import AppKit

/// A suggestion for visual inspection, in oriented native RAW-crop pixels.
/// It identifies a useful place to compare; it is not an artifact diagnosis.
struct PreviewInspectionRegion: Equatable {
    var rect: NSRect
    var reason: String
}

struct InspectionLoupeState {
    var region: PreviewInspectionRegion
    var before: PreviewDetail? = nil
    var after: PreviewDetail? = nil
    var beforeTitle: String
    var afterTitle: String
    var loading = false
    var notice: String? = nil
}

/// A fixed-region, native-pixel comparison which leaves the main zoom alone.
struct InspectionLoupeView: View {
    let state: InspectionLoupeState
    let brightness: Double
    let close: () -> Void
    let next: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 6) {
                Label("建议检查区域", systemImage: "viewfinder.circle")
                    .font(.caption.weight(.semibold))
                Spacer(minLength: 4)
                Button(action: close) { Image(systemName: "xmark") }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                    .accessibilityLabel("关闭局部检查")
                    .help("关闭本次对照；下次切换模式时仍可自动显示")
            }
            HStack(alignment: .top, spacing: 10) {
                pane(state.before, title: state.beforeTitle, role: "切换前", loading: false)
                pane(state.after, title: state.afterTitle, role: "当前", loading: state.loading)
            }
            HStack(spacing: 8) {
                Text(state.region.reason)
                    .font(.caption2).foregroundStyle(.secondary).lineLimit(1)
                Spacer(minLength: 4)
                Button("换一区域", action: next)
                    .controlSize(.mini).disabled(state.loading)
                    .accessibilityLabel("更换建议检查区域")
                    .help("在同一张照片的其他建议区域对照")
            }
            if let notice = state.notice, !notice.isEmpty {
                Text(notice).font(.caption2).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text("检查建议，不代表已检测到伪影")
                .font(.caption2).foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(width: 296)
        .padding(12)
        .modifier(NativeGlassControls(cornerRadius: 16))
        .accessibilityElement(children: .contain)
        .accessibilityLabel("局部放大对照")
    }

    private func pane(_ detail: PreviewDetail?, title: String, role: String, loading: Bool) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            ZStack {
                Color(nsColor: .underPageBackgroundColor)
                if let detail {
                    Image(nsImage: detail.image)
                        .resizable().interpolation(.none).scaledToFit()
                        .brightness(brightness)
                        .accessibilityLabel("\(role)的原生局部细节")
                } else if loading {
                    ProgressView().controlSize(.small)
                        .accessibilityLabel("正在加载当前模式局部细节")
                } else {
                    Image(systemName: "photo")
                        .foregroundStyle(.tertiary).accessibilityHidden(true)
                }
            }
            .frame(width: 143, height: 143)
            .clipShape(RoundedRectangle(cornerRadius: 9))
            .overlay { RoundedRectangle(cornerRadius: 9).strokeBorder(.white.opacity(0.12)) }
            Text(role).font(.caption2).foregroundStyle(.secondary)
            Text(title).font(.caption.weight(.medium)).lineLimit(1)
                .truncationMode(.middle).help(title)
        }
        .frame(width: 143, alignment: .leading)
    }
}
