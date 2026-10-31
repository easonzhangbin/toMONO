import SwiftUI

struct RawChannelSeries: Codable {
    var name:String
    var bins:[Int]
    var sample_count:Int
    var black_clipped:Int
    var white_clipped:Int
    var mean_signal:Double
    var color:Color { name == "R" ? .red : name == "G" ? .green : .blue }
}
struct RawSourceHistogram: Codable {
    var scope:String
    var channels:[RawChannelSeries]
    var valid:Bool {
        !channels.isEmpty && channels.count<=3 && Set(channels.map(\.name)).count==channels.count &&
        channels.allSatisfy { ["R","G","B"].contains($0.name) && $0.sample_count>0 && $0.bins.count==256 && $0.bins.allSatisfy { $0>=0 } && $0.bins.reduce(0,+)==$0.sample_count && $0.mean_signal.isFinite }
    }
}

struct PreviewHistogram: Codable {
    var linear_bins: [Int]
    var display_bins: [Int]
    var sample_count: Int
    var black_clipped: Int
    var white_clipped: Int
    var black_level: Int
    var white_level: Int
    var gamma: Double
    var valid: Bool {
        linear_bins.count == 256 && display_bins.count == 256 && sample_count > 0 &&
        linear_bins.allSatisfy { $0 >= 0 } && display_bins.allSatisfy { $0 >= 0 } &&
        linear_bins.reduce(0,+) == sample_count && display_bins.reduce(0,+) == sample_count
    }
    func percentage(_ count: Int) -> String { String(format:"%.2f%%",Double(count)/Double(max(1,sample_count))*100) }
}

struct HistogramPanel: View {
    @ObservedObject var model: AppModel
    @State private var displayValues = false
    @State private var rawValues = false
    @State private var logarithmic = true
    @State private var showHelp = false
    var body: some View {
        VStack(alignment:.leading,spacing:6) {
            HStack(spacing:8) {
                Text(rawValues ? "原始通道直方图" : model.showingReference ? "绿色参考直方图" : "单色直方图").font(.caption.weight(.semibold))
                Button { showHelp = true } label: { Image(systemName:"info.circle") }
                    .buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel("直方图说明")
                    .popover(isPresented:$showHelp,arrowEdge:.leading) {
                        VStack(alignment:.leading,spacing:12) {
                            Text("直方图怎样看").font(.headline)
                            Text("横轴由暗到亮，纵轴表示采样数量。统计当前单色结果的整个默认裁切区域，不依赖缩放或观察位置。")
                            Text("“线性RAW”按黑白电平归一化；“预览灰度”再应用预览伽马。两者都不包含预览亮度滑块或 Camera Raw 的显影。切换彩色原图时，已有统计仍代表单色结果。")
                            Text("“黑端／白端”表示达到或超出记录黑白电平的比例，不等同于证明细节可恢复。“对数”仅改变图形的纵向比例，方便观察较少的采样。")
                            Text("绿色差异校正只处理符合条件的局部采样，整体直方图可能几乎不变；可结合实际校正数量与100%–400%细节检查。")
                            Text("“原始RGB”统计响应混合及校正前的传感器采样，各颜色按自身采样数量归一化。G采样较多，不会因此将绿色曲线人为画高。均值是扣黑并按白电平归一化的信号，不是测得的信噪比。复杂传感器可能显示LibRaw已重建的线性通道，界面会标注。")
                            HStack { Spacer(); Button("知道了") { showHelp = false } }
                        }.font(.callout).padding(18).frame(width:350)
                    }
                Spacer(minLength:0)
                Toggle("对数",isOn:$logarithmic).toggleStyle(.checkbox).font(.caption)
            }
            Picker("直方图来源",selection:$rawValues) {
                Text("单色结果").tag(false);Text("原始 RGB").tag(true)
            }.pickerStyle(.segmented).labelsHidden().controlSize(.small)
            if !rawValues { Picker("统计范围",selection:$displayValues) {
                Text("线性 RAW").tag(false); Text("预览灰度").tag(true)
            }.pickerStyle(.segmented).labelsHidden().controlSize(.small) }
            ZStack {
                RoundedRectangle(cornerRadius:5).fill(Color(nsColor:.underPageBackgroundColor))
                if rawValues,let data=model.rawHistogram {
                    RawHistogramCanvas(data:data,logarithmic:logarithmic).padding(3)
                } else if !rawValues,let data=model.histogram {
                    let bins=displayValues ? data.display_bins : data.linear_bins
                    Canvas { context,size in
                        let peak=Double(bins.max() ?? 0)
                        if peak>0 {
                            var path=Path();path.move(to:CGPoint(x:0,y:size.height))
                            for (i,count) in bins.enumerated() {
                                let amount=logarithmic ? log1p(Double(count))/log1p(peak) : Double(count)/peak
                                path.addLine(to:CGPoint(x:(Double(i)+0.5)/256*size.width,y:size.height*(1-amount)))
                            }
                            path.addLine(to:CGPoint(x:size.width,y:size.height));path.closeSubpath()
                            context.fill(path,with:.color(.primary.opacity(0.65)))
                        }
                    }.padding(.horizontal,3).padding(.top,4).opacity(model.previewBusy ? 0.4 : 1)
                        .accessibilityLabel(displayValues ? "预览灰度分布" : "线性 RAW 信号分布")
                } else { Text(model.previewBusy ? "正在计算…" : "生成单色模拟后显示").font(.caption).foregroundStyle(.secondary) }
            }.frame(height:64)
            if rawValues,let data=model.rawHistogram {
                ForEach(data.channels,id:\.name) { channel in
                    HStack(spacing:5) {
                        Text(channel.name).foregroundStyle(channel.color).fontWeight(.semibold)
                        Text(String(format:"均值 %.2f%%",channel.mean_signal*100))
                        Spacer(minLength:0)
                        Text(String(format:"白端 %.2f%%",Double(channel.white_clipped)/Double(channel.sample_count)*100))
                    }.font(.caption2).foregroundStyle(.secondary)
                }
                Text(data.scope == "sensor_cfa" ? "原始采样 · 未应用响应混合" : "LibRaw 线性重建通道")
                    .font(.caption2).foregroundStyle(.secondary)
            } else if !rawValues,let data=model.histogram {
                HStack(spacing:6) {
                    Text("黑端 \(data.percentage(data.black_clipped))")
                    Spacer(minLength:0)
                    Text(model.previewBusy ? "正在更新…" : "白端 \(data.percentage(data.white_clipped))")
                }.font(.caption2).foregroundStyle(.secondary)
            }
        }
    }
}

struct RawHistogramCanvas: View {
    let data:RawSourceHistogram
    let logarithmic:Bool
    var body:some View {
        Canvas { context,size in
            let peak=data.channels.map { Double($0.bins.max() ?? 0)/Double($0.sample_count) }.max() ?? 0
            if peak>0 {
                for channel in data.channels {
                    var path=Path()
                    for (i,count) in channel.bins.enumerated() {
                        let frequency=Double(count)/Double(channel.sample_count)
                        let amount=logarithmic ? log1p(frequency*1e6)/log1p(peak*1e6) : frequency/peak
                        let p=CGPoint(x:(Double(i)+0.5)/256*size.width,y:size.height*(1-amount))
                        if i==0 { path.move(to:p) } else { path.addLine(to:p) }
                    }
                    context.stroke(path,with:.color(channel.color.opacity(0.85)),lineWidth:1.2)
                }
            }
        }.accessibilityLabel("原始RGB采样的线性信号分布")
    }
}
