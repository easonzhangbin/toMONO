"""Read the unique single-channel LinearRaw IFD, excluding RGB previews."""
import tifffile

def read_linear_output(path):
    with tifffile.TiffFile(path) as tif:
        candidates=[]
        def visit(pages):
            for page in pages:
                if int(page.photometric)==34892 and page.samplesperpixel==1:candidates.append(page)
                if page.pages is not None:visit(page.pages)
        visit(tif.pages)
        if len(candidates)!=1:raise ValueError('应当包含且仅包含一个单通道LinearRaw图像目录')
        return candidates[0].asarray()
