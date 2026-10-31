"""Generate a display preview from the same RAW computation as DNG export."""
import argparse,hashlib,json,signal,sys
from pathlib import Path
import numpy as np,imagecodecs
from recipe import Recipe
from conversion_service import compute_monochrome,Cancelled
from dng_writer import make_preview,make_detail_preview,make_histogram,orient_preview
from display_render import encode_preview_png
from execution_log import configure,event,failure

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path);p.add_argument('-o','--output',type=Path,required=True)
    p.add_argument('--recipe',type=Path,required=True);p.add_argument('--max-width',type=int,default=1600)
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
        if a.output.suffix.lower()!='.png' or not 64<=a.max_width<=2000:raise ValueError('预览输出或尺寸无效')
        if a.output.resolve()==a.input.resolve() or a.output.exists():raise ValueError('预览不能覆盖原图或已有文件')
        if a.detail_output and (a.detail_output.suffix.lower()!='.png' or a.detail_output.resolve() in (a.input.resolve(),a.output.resolve(),a.recipe.resolve()) or a.detail_output.exists()):raise ValueError('细节预览不能覆盖输入、配方或已有文件')
        recipe=Recipe.load(a.recipe)
        pixels,metadata,parameters,structure,replacements=compute_monochrome(a.input,recipe,checkpoint,diagnostics=True)
        checkpoint()
        histogram=make_histogram(pixels,metadata['black_level_by_libraw_channel'][0],metadata['white_level'],structure,recipe.preview_gamma,checkpoint)
        image=make_preview(pixels,metadata['black_level_by_libraw_channel'][0],metadata['white_level'],structure,recipe.preview_gamma,a.max_width)
        image=np.ascontiguousarray(orient_preview(image,int(structure.get('Orientation',1))))
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
        print(json.dumps({'state':'ready','detail_preview':str(a.detail_output) if a.detail_output else None,'detail_size':detail_size,'preview':str(a.output),'size':list(image.shape[:2]),'execution_log':log_path,
            'raw_sha256':hashlib.sha256(memoryview(pixels)).hexdigest(),'green_replacements':replacements,
            'recipe':recipe.to_dict(),'resolved_parameters':parameters,'histogram':histogram},ensure_ascii=False),flush=True)
        return 0
    except Cancelled:
        event('preview_cancelled',input=str(a.input));return 130
    except Exception as exc:
        failure('preview_failed',exc,input=str(a.input))
        print(json.dumps({'state':'failed','message':str(exc)},ensure_ascii=False),flush=True);return 1

if __name__=='__main__':raise SystemExit(main())
