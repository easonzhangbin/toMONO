import AppKit
import Foundation

private let inspectionQueue = DispatchQueue(label:"cn.tomono.preview.inspection",qos:.userInitiated)

@MainActor extension AppModel {
    func setInspectionEnabled(_ enabled:Bool) {
        inspectionEnabled=enabled
        if !enabled { dismissInspectionLoupe();return }
        guard selected != nil,!showingSource,!showingReference else { return }
        beginModeInspection(beforeKey:nil,current:recipe)
        if let key=previewShownKey,previewShownRecipe==recipe { commitInspectionPreview(key:key,applied:recipe) }
    }

    func dismissInspectionLoupe() {
        inspectionCancellation?.cancel();inspectionCancellation=nil;inspectionTicket=UUID()
        inspectionLoupe=nil;inspectionBeforeKey=nil;inspectionAfterKey=nil;inspectionExpectedRecipe=nil
    }

    func recipeInspectionChanged(from previous:RecipeDocument) {
        guard !restoringForInspection,selected != nil,!showingSource,!showingReference else { return }
        if previous.response_mode != recipe.response_mode || previous.lens_correction != recipe.lens_correction {
            if let id=selection { inspectionRegionsByInput[id]=nil;inspectionRegionIndex[id]=nil }
            dismissInspectionLoupe()
            return
        }
        if previous.detail_mode != recipe.detail_mode {
            beginModeInspection(beforeKey:previewShownKey,current:recipe)
        } else if previous != recipe { dismissInspectionLoupe() }
    }

    func beginModeInspection(beforeKey:String?,current:RecipeDocument) {
        guard inspectionEnabled,selected != nil,!showingSource,!showingReference else { return }
        inspectionCancellation?.cancel();inspectionTicket=UUID()
        inspectionBeforeKey=beforeKey;inspectionAfterKey=nil;inspectionExpectedRecipe=current
        if let region=currentInspectionRegion() {
            inspectionLoupe=InspectionLoupeState(region:region,beforeTitle:beforeKey.flatMap { previewRecipes[$0]?.detailModeTitle } ?? "尚无对照",afterTitle:current.detailModeTitle,loading:true)
            loadInspectionComparison()
        } else { inspectionLoupe=nil }
    }

    func nextInspectionRegion() {
        guard let id=selection,inspectionLoupe != nil else { return }
        let regions=inspectionRegionsByInput[id] ?? []
        inspectionRegionIndex[id]=((inspectionRegionIndex[id] ?? 0)+1)%max(1,regions.count)
        guard let region=currentInspectionRegion(),var state=inspectionLoupe else { return }
        state.region=region;state.before=nil;state.after=nil;state.notice=nil;state.loading=true
        inspectionLoupe=state;loadInspectionComparison()
    }

    func commitInspectionPreview(key:String,applied:RecipeDocument) {
        if let id=selection,inspectionRegionsByInput[id]==nil {
            let value=previewResolved[key]?["inspection_regions"] as? [String:Any]
            let raw=value?["regions"] as? [[String:Any]] ?? []
            let bounds=NSRect(origin:.zero,size:previewSizes[key] ?? .zero)
            let regions=raw.prefix(3).compactMap { row -> PreviewInspectionRegion? in
                guard let v=row["rect"] as? [NSNumber],v.count==4,v.allSatisfy({ $0.doubleValue.isFinite }) else { return nil }
                let rect=NSRect(x:v[0].doubleValue,y:v[1].doubleValue,width:v[2].doubleValue,height:v[3].doubleValue).integral.intersection(bounds)
                guard rect.width>0,rect.height>0 else { return nil }
                return PreviewInspectionRegion(rect:rect,reason:row["reason"] as? String ?? "建议检查")
            }
            if !regions.isEmpty { inspectionRegionsByInput[id]=regions }
        }
        guard inspectionEnabled,inspectionExpectedRecipe==applied,!showingSource,!showingReference else { return }
        if inspectionLoupe==nil,let region=currentInspectionRegion() {
            inspectionLoupe=InspectionLoupeState(region:region,beforeTitle:inspectionBeforeKey.flatMap { previewRecipes[$0]?.detailModeTitle } ?? "尚无对照",afterTitle:applied.detailModeTitle,loading:true)
        }
        inspectionAfterKey=key;loadInspectionComparison()
    }

    func inspectionPreviewFailed(_ message:String) {
        guard var state=inspectionLoupe else { return }
        state.loading=false;state.notice=message;inspectionLoupe=state
    }

    private func currentInspectionRegion() -> PreviewInspectionRegion? {
        guard let id=selection else { return nil }
        if let regions=inspectionRegionsByInput[id],!regions.isEmpty {
            return regions[(inspectionRegionIndex[id] ?? 0)%regions.count]
        }
        guard previewPixelSize.width>0,previewPixelSize.height>0 else { return nil }
        let w=min(192,previewPixelSize.width),h=min(192,previewPixelSize.height)
        return PreviewInspectionRegion(rect:NSRect(x:floor((previewPixelSize.width-w)/2),y:floor((previewPixelSize.height-h)/2),width:w,height:h),reason:"画面中心")
    }

    private func loadInspectionComparison() {
        guard let state=inspectionLoupe,inspectionEnabled,let id=selection,
              let color=preview?.cgImage(forProposedRect:nil,context:nil,hints:nil)?.colorSpace else { return }
        inspectionCancellation?.cancel();inspectionTicket=UUID()
        let ticket=inspectionTicket,request=PreviewTileCancellation();inspectionCancellation=request
        let rect=state.region.rect
        let beforeRaster=inspectionBeforeKey.flatMap { previewRasters[$0] }
        let afterRaster=inspectionAfterKey.flatMap { previewRasters[$0] }
        let existingBefore=state.before,existingAfter=state.after
        let waiting=inspectionAfterKey==nil
        let start=Date()
        inspectionQueue.async { [weak self] in
            var before=existingBefore,after=existingAfter,notice:String?
            if before==nil,let source=beforeRaster,source.exists {
                before=try? source.render(rect,colorSpace:color,cancellation:request)
            }
            if let source=afterRaster,source.exists {
                after=try? source.render(rect,colorSpace:color,cancellation:request)
            } else if !waiting { notice="原生细节缓存暂不可用" }
            DispatchQueue.main.async {
                guard let self,self.inspectionTicket==ticket,self.selection==id,!request.cancelled,
                      var current=self.inspectionLoupe,current.region.rect==rect else { return }
                current.before=before;current.after=after;current.loading=waiting;current.notice=notice
                self.inspectionLoupe=current
                ExecutionLogStore.shared.record("inspection_loupe_ready",fields:["milliseconds":Date().timeIntervalSince(start)*1000,"native_width":Int(rect.width),"native_height":Int(rect.height),"before_ready":before != nil,"after_ready":after != nil,"reconstructed_again":false])
            }
        }
    }
}
