"""Generate a display preview from the same RAW computation as DNG export."""
import argparse,hashlib,json,signal,sys
from pathlib import Path
import numpy as np,imagecodecs
from recipe import Recipe
from conversion_service import compute_monochrome,Cancelled
from dng_writer import make_preview,make_detail_preview,make_histogram,orient_preview,detail_display_lut
from display_render import encode_preview_png
from execution_log import configure,event,failure

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--recipe',type=Path,required=True);p.add_argument('--max-width',type=int,default=1600)
    p.add_argument('--max-edge',type=int,help='概览长边上限；界面使用2048，不放大小图')
    p.add_argument('--cache-linear',action='store_true',help='缓存线性结果与显示LUT，供界面按区域读取真实细节')
    p.add_argument('--log',type=Path)
    p.add_argument('--detail-output',type=Path,help='可选原生分辨率灰度显示预览，不修改RAW')
    a=p.parse_args();cancelled=False
    log_path=configure(a.log);event('preview_requested',input=str(a.input),recipe=str(a.recipe),output=str(a.output))
    def cancel(*_):
        nonlocal cancelled
        cancelled=True
    def checkpoint(*_):
        if cancelled:raise Cancelled()
    signal.signal(signal.SIGINT,cancel)
    try:
        if a.output.suffix.lower()!='.png' or not 64<=a.max_width<=2048 or (a.max_edge is not None and not 64<=a.max_edge<=2048):raise ValueError('预览输出或尺寸无效')
        if a.output.resolve()==a.input.resolve() or a.output.exists():raise ValueError('预览不能覆盖原图或已有文件')
        if a.detail_output and (a.detail_output.suffix.lower()!='.png' or a.detail_output.resolve() in (a.input.resolve(),a.output.resolve(),a.recipe.resolve()) or a.detail_output.exists()):raise ValueError('细节预览不能覆盖输入、配方或已有文件')
        recipe=Recipe.load(a.recipe)
        pixels,metadata,parameters,structure,replacements=compute_monochrome(a.input,recipe,checkpoint,diagnostics=True)
        checkpoint()
        histogram=make_histogram(pixels,metadata['black_level_by_libraw_channel'][0],metadata['white_level'],structure,recipe.preview_gamma,checkpoint)
        image=make_preview(pixels,metadata['black_level_by_libraw_channel'][0],metadata['white_level'],structure,recipe.preview_gamma,a.max_width,max_edge=a.max_edge)
        image=np.ascontiguousarray(orient_preview(image,int(structure.get('Orientation',1))))
        cw,ch=map(int,structure['crop_size'])
        native_size=[cw,ch] if int(structure.get('Orientation',1)) in (5,6,7,8) else [ch,cw]
        raster_source=None
        if a.cache_linear:
            raw_path=a.output.with_suffix('.linear16');lut_path=a.output.with_suffix('.lut8')
            a.output.parent.mkdir(parents=True,exist_ok=True)
            with raw_path.open('xb') as stream:np.asarray(pixels,dtype='<u2').tofile(stream)
            with lut_path.open('xb') as stream:detail_display_lut(metadata['black_level_by_libraw_channel'][0],metadata['white_level'],recipe.preview_gamma).tofile(stream)
            raster_source=dict(path=str(raw_path),lut_path=str(lut_path),width=int(pixels.shape[1]),height=int(pixels.shape[0]),
                crop_x=int(structure['active_area'][1]+structure['crop_origin'][0]),crop_y=int(structure['active_area'][0]+structure['crop_origin'][1]),
                crop_width=cw,crop_height=ch,orientation=int(structure.get('Orientation',1)))
        detail_size=None
        if a.detail_output:
            detail=np.ascontiguousarray(orient_preview(make_detail_preview(pixels,metadata['black_level_by_libraw_channel'][0],metadata['white_level'],structure,recipe.preview_gamma),int(structure.get('Orientation',1))))
            detail_size=list(detail.shape)
            checkpoint()
            a.detail_output.parent.mkdir(parents=True,exist_ok=True)
            with a.detail_output.open('xb') as stream:stream.write(encode_preview_png(detail))
            del detail
        checkpoint()
        a.output.parent.mkdir(parents=True,exist_ok=True)
        with a.output.open('xb') as stream:stream.write(encode_preview_png(image))
        event('preview_ready',input=str(a.input),output=str(a.output),size=list(image.shape[:2]))
        print(json.dumps({'state':'ready','raster_source':raster_source,'native_size':native_size,'detail_preview':str(a.detail_output) if a.detail_output else None,'detail_size':detail_size,'preview':str(a.output),'size':list(image.shape[:2]),'execution_log':log_path,
            'raw_sha256':hashlib.sha256(memoryview(pixels)).hexdigest(),'green_replacements':replacements,
            'recipe':recipe.to_dict(),'resolved_parameters':parameters,'histogram':histogram},ensure_ascii=False),flush=True)
        return 0
    except Cancelled:
        event('preview_cancelled',input=str(a.input));return 130
    except Exception as exc:
        failure('preview_failed',exc,input=str(a.input))
        print(json.dumps({'state':'failed','message':str(exc)},ensure_ascii=False),flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
