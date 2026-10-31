import SwiftUI

#if DEBUG
private struct WorkspaceCanvas: View {
    @StateObject private var model = AppModel()
    var body: some View {
        ContentView(model:model)
            .environment(\.locale,Locale(identifier:"zh_Hans"))
            .frame(width:1200,height:780)
    }
}

#Preview("工作区 · 浅色") {
    WorkspaceCanvas().preferredColorScheme(.light)
}

#Preview("工作区 · 深色") {
    WorkspaceCanvas().preferredColorScheme(.dark)
}

#endif
