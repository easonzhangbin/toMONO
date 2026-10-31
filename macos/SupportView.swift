import SwiftUI
import AppKit

/// An offline, voluntary support page. It never starts or verifies a payment.
struct SupportView: View {
    private var artworkURL: URL? {
        Bundle.main.url(forResource: "SupportAlipay", withExtension: "jpg")
    }
    private var artwork: NSImage? { artworkURL.flatMap { NSImage(contentsOf: $0) } }

    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                Image(systemName: "cup.and.saucer")
                    .font(.system(size: 28, weight: .regular)).foregroundStyle(.secondary)
                Text("请我喝杯咖啡").font(.title2.weight(.semibold))
                Text("如果 toMONO 对你有帮助，欢迎支持后续的开发与影像研究。")
                    .font(.callout).multilineTextAlignment(.center)
                Text("支持完全自愿，不影响任何功能，也无需付费解锁。")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)

                if let artwork {
                    Image(nsImage: artwork).resizable().interpolation(.high).scaledToFit()
                        .frame(maxWidth: 280)
                        .clipShape(RoundedRectangle(cornerRadius: 12))
                        .accessibilityLabel("支付宝支持二维码，收款方 StudioPURE。请用支付宝扫码，并在支付前核对收款方。")
                    Text("支付宝扫码 · 收款方 StudioPURE")
                        .font(.callout.weight(.medium))
                    Text("请在支付前核对收款方，金额由你自行决定。")
                        .font(.caption).foregroundStyle(.secondary)
                    Button("查看收款码原图", systemImage: "arrow.up.left.and.arrow.down.right") {
                        if let artworkURL { NSWorkspace.shared.open(artworkURL) }
                    }.buttonStyle(.bordered)
                } else {
                    ContentUnavailableView("收款码暂不可用", systemImage: "qrcode",
                        description: Text("你仍可在项目的 GitHub 支持页面查看。"))
                }
                Link("GitHub 开源项目", destination: URL(string: "https://github.com/easonzhangbin/toMONO")!)
                    .font(.callout).foregroundStyle(.tint)
                Text("感谢每一份支持，也感谢你反馈问题、分享实验和贡献代码。")
                    .font(.caption).foregroundStyle(.secondary).multilineTextAlignment(.center)
            }
            .foregroundStyle(.primary)
            .padding(24).frame(maxWidth: 460)
            .modifier(NativeGlassControls(cornerRadius: 20))
            .padding(20).frame(maxWidth: .infinity)
        }
        .background { NativeSidebarBackdrop(material: .underWindowBackground) }
        .frame(minWidth: 420, minHeight: 520)
        .navigationTitle("支持 toMONO")
    }
}
