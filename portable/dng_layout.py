"""Locate full-resolution CFA data independently of preview IFD placement."""
from collections import ChainMap
from types import SimpleNamespace

def select_raw_ifd(tif,allow_linear=False):
    candidates=[];linear=False
    def visit(pages,prefix=''):
        nonlocal linear
        for index,page in enumerate(pages):
            path=prefix+str(index)
            if int(page.photometric)==34892:linear=True
            if ((int(page.photometric)==32803 and page.samplesperpixel==1) or (allow_linear and int(page.photometric)==34892)) and not int(page.subfiletype)&5:
                candidates.append((int(page.imagewidth)*int(page.imagelength),path,page))
            if page.pages is not None:visit(page.pages,path+'.')
    visit(tif.pages)
    if not candidates:
        if linear:raise ValueError('文件包含已重建的LinearRaw图像；请载入含Bayer采样的原始RAW')
        raise ValueError('文件中没有找到可用的Bayer RAW图像目录')
    candidates.sort(key=lambda item:item[0],reverse=True)
    if len(candidates)>1 and candidates[0][0]==candidates[1][0]:raise ValueError('文件含多个同分辨率RAW图像，暂不能自动选择多帧输入')
    _,path,raw=candidates[0];root=tif.pages[0]
    return SimpleNamespace(tags=ChainMap(raw.tags,root.tags),shape=raw.shape,photometric=raw.photometric,ifd_path=path,raw=raw,root=root)
