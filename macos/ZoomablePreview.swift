import SwiftUI
import AppKit

@MainActor final class PreviewZoom: ObservableObject {
    @Published var scale = 1.0
    @Published var fitted = true
    var command: ((Double?) -> Void)?
    func fit() { command?(nil) }
    func actual() { command?(1) }
    func step(_ factor: Double) { command?(min(8, max(0.01, scale * factor))) }
}

/// One image pixel equals one backing-display pixel at 100%, including Retina.
/// NSScrollView supplies native scrollbars, pinch zoom and bounded scrolling.
struct ZoomablePreview: NSViewRepresentable {
    let image: NSImage
    let identity: UUID?
    @ObservedObject var zoom: PreviewZoom
    var nativePixelSize: NSSize = .zero
    var detail: PreviewDetail?
    var inspectionRect: NSRect?
    var onZoom: ((Double, Bool, NSRect) -> Void)?
    func makeNSView(context: Context) -> ImageScrollView {
        let scroll = ImageScrollView()
        scroll.hasHorizontalScroller = true; scroll.hasVerticalScroller = true
        scroll.autohidesScrollers = true; scroll.drawsBackground = false
        scroll.allowsMagnification = true; scroll.minMagnification = 0.01; scroll.maxMagnification = 8
        scroll.documentView = scroll.canvas
        scroll.onScale = { scale, fitted, rect in
            DispatchQueue.main.async { zoom.scale = scale; zoom.fitted = fitted; onZoom?(scale,fitted,rect) }
        }
        zoom.command = { [weak scroll] in scroll?.setScale($0) }
        return scroll
    }
    func updateNSView(_ scroll: ImageScrollView, context: Context) {
        scroll.setImage(image, identity: identity, nativePixelSize: nativePixelSize)
        scroll.canvas.detail = detail
        scroll.canvas.inspectionRect = inspectionRect
        scroll.canvas.needsDisplay = true
    }
    static func dismantleNSView(_ view: ImageScrollView, coordinator: ()) { view.onScale = nil }
}

final class ImageScrollView: NSScrollView {
    let canvas = PanImageView()
    var onScale: ((Double, Bool, NSRect) -> Void)?
    private var imageIdentity: UUID?
    private var imageObject: ObjectIdentifier?
    private var fitting = true
    private var backing = 2.0
    private var resizing = false
    override init(frame: NSRect) {
        super.init(frame: frame)
        contentView = CenteredClipView()
        contentView.drawsBackground = false
        contentView.postsBoundsChangedNotifications = true
        NotificationCenter.default.addObserver(self,selector:#selector(scaleChanged),name:NSView.boundsDidChangeNotification,object:contentView)
        NotificationCenter.default.addObserver(self, selector: #selector(magnified), name: NSScrollView.willStartLiveMagnifyNotification, object: self)
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    deinit { NotificationCenter.default.removeObserver(self) }
    func setImage(_ image: NSImage, identity: UUID?, nativePixelSize: NSSize = .zero) {
        let changed = imageIdentity != identity
        guard changed || imageObject != ObjectIdentifier(image) else { return }
        imageObject = ObjectIdentifier(image); imageIdentity = identity
        canvas.image = image
        let rep = image.representations.max { $0.pixelsWide < $1.pixelsWide }
        // Both proxy and detail occupy the same RAW crop canvas. Replacing the
        // proxy must not move the inspected region or redefine "100%".
        canvas.pixelSize = nativePixelSize.width > 0 && nativePixelSize.height > 0 ? nativePixelSize : NSSize(width: rep?.pixelsWide ?? Int(image.size.width), height: rep?.pixelsHigh ?? Int(image.size.height))
        resizeCanvas()
        if changed || fitting { setScale(nil) }
        canvas.needsDisplay = true
    }
    override func viewDidMoveToWindow() { super.viewDidMoveToWindow(); resizeCanvas(); if fitting { setScale(nil) } }
    private func resizeCanvas() {
        let current = window?.backingScaleFactor ?? 2
        backing = current
        canvas.frame.size = NSSize(width: max(1,canvas.pixelSize.width/current), height: max(1,canvas.pixelSize.height/current))
    }
    override func layout() {
        super.layout()
        guard !resizing else { return }
        resizing = true
        if backing != (window?.backingScaleFactor ?? 2) { resizeCanvas() }
        if fitting, canvas.image != nil { setScale(nil) }
        resizing = false
    }
    func setScale(_ scale: Double?, centeredAt point: NSPoint? = nil) {
        guard canvas.image != nil else { return }
        fitting = scale == nil
        let fit = min(contentSize.width/max(1,canvas.frame.width),contentSize.height/max(1,canvas.frame.height))
        let amount = min(maxMagnification,max(minMagnification,scale ?? fit))
        let center = point ?? NSPoint(x: contentView.bounds.midX,y: contentView.bounds.midY)
        setMagnification(amount, centeredAt: center)
        if fitting {
            contentView.scroll(to: NSPoint(x: (canvas.bounds.width-contentView.bounds.width)/2,y: (canvas.bounds.height-contentView.bounds.height)/2))
        }
        reflectScrolledClipView(contentView)
        reportViewport()
    }
    private func reportViewport() {
        let rect=canvas.visibleRect
        let ratio=canvas.pixelSize.width/max(1,canvas.bounds.width)
        onScale?(magnification,fitting,NSRect(x:rect.minX*ratio,y:rect.minY*ratio,width:rect.width*ratio,height:rect.height*ratio))
    }
    @objc private func scaleChanged() { if !fitting { reportViewport() } }
    @objc private func magnified() { fitting = false; reportViewport() }
    func doubleClick(at point: NSPoint) {
        if !fitting && abs(magnification - 1) < 0.001 { setScale(nil) }
        else { setScale(1,centeredAt:point) }
    }
}

final class CenteredClipView: NSClipView {
    override func constrainBoundsRect(_ proposedBounds: NSRect) -> NSRect {
        var result = super.constrainBoundsRect(proposedBounds)
        if let document = documentView {
            if document.frame.width < result.width { result.origin.x = (document.frame.width-result.width)/2 }
            if document.frame.height < result.height { result.origin.y = (document.frame.height-result.height)/2 }
        }
        return result
    }
}
final class PanImageView: NSView {
    var image: NSImage?
    var detail: PreviewDetail?
    var inspectionRect: NSRect?
    var pixelSize = NSSize(width: 1,height: 1)
    override var isFlipped: Bool { true }
    override func resetCursorRects() { addCursorRect(visibleRect,cursor:.openHand) }
    override func draw(_ dirtyRect: NSRect) {
        NSGraphicsContext.current?.imageInterpolation = (enclosingScrollView?.magnification ?? 1) >= 1 ? .none : .high
        image?.draw(in: bounds, from:.zero, operation:.sourceOver, fraction:1,respectFlipped:true,hints:nil)
        if let detail {
            let factor=bounds.width/max(1,pixelSize.width)
            let rect=detail.rect
            detail.image.draw(in:NSRect(x:rect.minX*factor,y:rect.minY*factor,width:rect.width*factor,height:rect.height*factor),from:.zero,operation:.sourceOver,fraction:1,respectFlipped:true,hints:nil)
        }
        if let inspectionRect {
            let native = inspectionRect.intersection(NSRect(origin: .zero, size: pixelSize))
            guard !native.isEmpty else { return }
            let factor = bounds.width / max(1, pixelSize.width)
            let rect = NSRect(x: native.minX * factor, y: native.minY * factor,
                              width: native.width * factor, height: native.height * factor)
            // Keep the locator legible at fit and 100%, without changing pixels.
            let unit = 1 / max(0.01, enclosingScrollView?.magnification ?? 1)
            let path = NSBezierPath(rect: rect)
            NSGraphicsContext.saveGraphicsState()
            NSColor.black.withAlphaComponent(0.65).setStroke()
            path.lineWidth = 3 * unit; path.stroke()
            NSColor.controlAccentColor.setStroke()
            path.lineWidth = 1.5 * unit
            path.setLineDash([5 * unit, 3 * unit], count: 2, phase: 0)
            path.stroke()
            NSGraphicsContext.restoreGraphicsState()
        }
    }
    override func mouseDown(with event: NSEvent) {
        guard let scroll = enclosingScrollView else { return }
        if event.clickCount == 2,let viewer = scroll as? ImageScrollView {
            viewer.doubleClick(at:convert(event.locationInWindow,from:nil));return
        }
        NSCursor.closedHand.push(); defer { NSCursor.pop() }
        let initial = event.locationInWindow,origin = scroll.contentView.bounds.origin
        while let next = window?.nextEvent(matching:[.leftMouseDragged,.leftMouseUp]) {
            if next.type == .leftMouseUp { break }
            let factor = max(0.01,scroll.magnification)
            let target = NSPoint(x:origin.x-(next.locationInWindow.x-initial.x)/factor,y:origin.y+(next.locationInWindow.y-initial.y)/factor)
            scroll.contentView.scroll(to:scroll.contentView.constrainBoundsRect(NSRect(origin:target,size:scroll.contentView.bounds.size)).origin)
            scroll.reflectScrolledClipView(scroll.contentView)
        }
    }
    override func mouseUp(with event: NSEvent) {}
}
