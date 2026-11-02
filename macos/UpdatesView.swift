import SwiftUI
import AppKit

/// Release text is displayed as plain text; it cannot run HTML or scripts.
struct UpdateAvailableView: View {
    let release: GitHubRelease
    let onDismiss: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(spacing: 12) {
                Image(systemName: "arrow.down.circle")
                    .font(.system(size: 32)).foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 5) {
                    Text("发现 toMONO 新版本").font(.title2.weight(.semibold))
                    Text(verbatim: release.versionLabel).font(.headline)
                }
            }
            Text("新版改进内容").font(.subheadline.weight(.semibold))
            ScrollView {
                Text(verbatim: release.releaseNotes)
                    .font(.body).textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(14)
            }
            .frame(minHeight: 160, maxHeight: 340)
            .background(.quaternary, in: RoundedRectangle(cornerRadius: 12))
            Text("下载后请退出 toMONO，再安装新版。照片与转换设置不会上传。").font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("在 GitHub 查看") { NSWorkspace.shared.open(release.releasePageURL) }
                Spacer()
                Button("稍后", action: onDismiss).keyboardShortcut(.cancelAction)
                Button("下载新版") {
                    NSWorkspace.shared.open(release.downloadURL)
                    onDismiss()
                }.keyboardShortcut(.defaultAction).buttonStyle(.borderedProminent)
            }
        }
        .padding(24).frame(width: 540)
        .accessibilityIdentifier("update-available")
    }
}
