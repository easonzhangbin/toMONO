"""Compare actual Swift mapped-region renderer with Python full detail rendering."""
import json,subprocess,sys,tempfile
from pathlib import Path
import numpy as np
root=Path(__file__).resolve().parents[2];sys.path.insert(0,str(root/'portable'))
from dng_writer import detail_display_lut,make_detail_preview,orient_preview
from display_render import encode_preview_png
with tempfile.TemporaryDirectory(prefix='tomono-raster-') as name:
    work=Path(name);raw=(np.arange(13*19,dtype=np.uint16).reshape(13,19)*231)
    (work/'source.linear16').write_bytes(raw.astype('<u2').tobytes())
    (work/'lut8').write_bytes(detail_display_lut(128,60000,2.2).tobytes())
    (work/'color.png').write_bytes(encode_preview_png(np.full((2,2,3),127,np.uint8)))
    fixtures=[]
    for orientation in range(1,9):
        source=dict(path=str(work/'source.linear16'),lut_path=str(work/'lut8'),width=19,height=13,crop_x=3,crop_y=2,crop_width=13,crop_height=9,orientation=orientation)
        (work/f'{orientation}.json').write_text(json.dumps(source))
        structure=dict(active_area=[0,0,13,19],crop_origin=[3,2],crop_size=[13,9],Orientation=orientation)
        full=orient_preview(make_detail_preview(raw,128,60000,structure,2.2),orientation)
        expected=full[2:7,1:7]
        fixtures.append(expected)
    source=(root/'macos/MonochromePreview.swift').read_text().split('@MainActor extension AppModel {',1)[0]
    (work/'Raster.swift').write_text(source)
    (work/'Main.swift').write_text('''import AppKit
import ImageIO
@main struct Check {
 static func main() throws {
  let root=URL(fileURLWithPath:CommandLine.arguments[1])
  let image=CGImageSourceCreateWithURL(root.appendingPathComponent("color.png") as CFURL,nil)!
  let color=CGImageSourceCreateImageAtIndex(image,0,nil)!.colorSpace!
  for n in 1...8 {
   let source=try JSONDecoder().decode(PreviewRaster.self,from:Data(contentsOf:root.appendingPathComponent("\\(n).json")))
   let rendered=try source.render(NSRect(x:1,y:2,width:6,height:5),colorSpace:color,cancellation:PreviewTileCancellation())
   let cg=rendered.image.cgImage(forProposedRect:nil,context:nil,hints:nil)!
   guard cg.width==6,cg.height==5,cg.bitsPerPixel==32 else { fatalError("Geometry or pixel format") }
   let bytes=cg.dataProvider!.data! as Data
   try bytes.write(to:root.appendingPathComponent("\\(n).rgba"))
   let cancelled=PreviewTileCancellation();cancelled.cancel()
   do { _=try source.render(NSRect(x:0,y:0,width:4,height:4),colorSpace:color,cancellation:cancelled);fatalError("Ignored cancellation") } catch { }
  }
 }
}''')
    subprocess.run(['xcrun','swiftc','-O','-parse-as-library',str(work/'Raster.swift'),str(work/'Main.swift'),'-o',str(work/'Check'),'-framework','AppKit','-framework','ImageIO'],check=True)
    subprocess.run([str(work/'Check'),str(work)],check=True)
    for i,expected in enumerate(fixtures,1):
        result=np.frombuffer((work/f'{i}.rgba').read_bytes(),np.uint8).reshape(5,6,4)
        for c in range(3):np.testing.assert_array_equal(result[:,:,c],expected)
    print(json.dumps(dict(oriented_crops_pixel_exact=8,cancelled_regions_rejected=8,source_sha256=__import__('hashlib').sha256(source.encode()).hexdigest())))
