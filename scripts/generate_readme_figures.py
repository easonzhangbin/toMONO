"""Render repeatable scientific comparisons from a locally supplied M11 RAW.

The RAW stays local. Only selected display crops and aggregate provenance are
written to the repository. No per-panel exposure, sharpening or normalization.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import rawpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'portable'))
from raw_input import decode_sensor
from detail_reconstruction import reconstruct
from pure_narrowband import channel_strips
from display_render import preview_icc

METHODS = [('C00', '同色三次基线', None), ('C01', '频域精细 · 默认', 'spectral'),
           ('D11', '频域限幅', 'spectral_guard'), ('D10', '方向自适应', 'directional')]
ROIS = [('hat', '帽子细密织纹', 4336, 2848), ('coat', '外套平滑区域与缝线', 4416, 3776)]

def display(a):
    return np.rint(np.clip(a, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('input', type=Path)
    ap.add_argument('--output', type=Path, default=ROOT / 'docs/images')
    ap.add_argument('--work', type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.work.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(args.input.read_bytes()).hexdigest()
    # Coordinates are intentionally pinned to the previously studied source.
    if source_hash != '09bd27dfb4298256b4c28912a5d8de416a0bbf73b7a26625fa8dd38656a225e0':
        raise ValueError('This gallery uses fixed ROIs of the documented M11 sample')
    frame = decode_sensor(args.input)
    a = frame.samples
    p = np.array(frame.metadata['cfa_codes_full_origin'], np.uint8)
    assert a.shape == (6336, 9536) and np.array_equal(p, [[0, 1], [1, 2]])
    assert frame.metadata['black_level_by_libraw_channel'] == [1023] * 4
    assert frame.metadata['white_level'] == 16383
    black, white = 1023., 16383.
    font_path = '/System/Library/Fonts/STHeiti Medium.ttc'
    font = ImageFont.truetype(font_path, 25)
    title = ImageFont.truetype(font_path, 34)
    small = ImageFont.truetype(font_path, 22)
    manifest = {'source_sha256': source_hash, 'camera': 'LEICA M11', 'target': 'G',
                'rawpy_version': rawpy.__version__, 'libraw_version': list(rawpy.libraw_version),
                'kernel_sha256': {name: hashlib.sha256((ROOT/'portable'/name).read_bytes()).hexdigest()
                                  for name in ('detail_reconstruction.py', 'src/detail_native.c', 'pure_narrowband.py')},
                'display': 'gamma 2.2, EV 0, no per-panel stretch or sharpening',
                'green_correction': 'off', 'defect_repair': 'off', 'lens_correction': 'off',
                'ground_truth': False, 'source_raw_included': False, 'rois': []}
    for key, label, x, y in ROIS:
        halo, n = 64, 512
        raw = np.ascontiguousarray(a[y-halo:y+n+halo, x-halo:x+n+halo])
        normalized = (raw.astype(np.float64) - black) / (white-black)
        canvas = Image.new('RGB', (2168, 714), '#141619')
        draw = ImageDraw.Draw(canvas)
        draw.text((32, 22), 'LEICA M11  /  ' + label, font=title, fill='#f2f3f5')
        draw.text((32, 69), '512 × 512 原生像素裁切 · 同一 G 采样 · 统一 Gamma 2.2 / 0 EV', font=small, fill='#a9b0b9')
        record = {'name': key, 'xywh_full_raw': [x, y, n, n], 'halo': halo, 'methods': []}
        for col, (code, name, method) in enumerate(METHODS):
            if method:
                result = reconstruct(normalized, p, 'G', method)
            else:
                result = np.concatenate([v for _, v in channel_strips(raw, p, np.full((2,2), black), np.full((2,2), white), 1)])
            # Match the product's single final quantization to sensor DN.
            dn = np.clip(np.rint(black + result * (white-black)), 0, 65535).astype(np.uint16)
            crop = dn[halo:-halo, halo:-halo]
            panel = Image.fromarray(display((crop.astype(float)-black)/(white-black))).convert('RGB')
            px = 32 + col * 532
            draw.text((px, 116), code + '  ' + name, font=font, fill='#f2f3f5')
            canvas.paste(panel, (px, 160))
            record['methods'].append({'code': code, 'kernel': method or 'pure_narrowband.channel_strips/cubic',
                                      'dn_sha256': hashlib.sha256(crop.tobytes()).hexdigest()})
        draw.text((32, 682), '实拍无逐像素真值；纹理、噪声与混叠均应一起观察。点击原图按 100% 比较。', font=small, fill='#a9b0b9')
        canvas.save(args.output / (key + '-algorithms.png'), icc_profile=preview_icc(True))
        manifest['rois'].append(record)
    # A scene comparison, not a demosaicking quality benchmark. RGB has camera
    # WB + sRGB conversion; mono is sensor G. Both use a fixed gamma and EV.
    with rawpy.imread(str(args.input)) as raw:
        rgb = raw.postprocess(use_camera_wb=True, use_auto_wb=False, no_auto_bright=True,
                              output_color=rawpy.ColorSpace.sRGB, output_bps=16,
                              gamma=(1, 1), user_flip=0, bright=1)
    # Native source and displayed crop differ by DNG DefaultCrop. Align to raw
    # coordinates using LibRaw's actual visible area, not thumbnail dimensions.
    top = frame.metadata['visible_area']['top']; left = frame.metadata['visible_area']['left']
    assert rgb.shape[:2] == (frame.metadata['visible_area']['height'], frame.metadata['visible_area']['width'])
    x, y, w, h = 2800, 2700, 3000, 2200
    rgb = rgb[y-top:y-top+h, x-left:x-left+w].astype(np.float64)/65535
    raw = a[y-64:y+h+64, x-64:x+w+64]
    mono = reconstruct((raw.astype(np.float64)-black)/(white-black), p, 'G', 'spectral')[64:-64,64:-64]
    mono = (np.clip(np.rint(black+mono*(white-black)),0,65535)-black)/(white-black)
    # One common linear-space area reduction per panel, before gamma encoding.
    def overview(v):
        planes = [v] if v.ndim==2 else [v[:,:,i] for i in range(3)]
        down = [np.asarray(Image.fromarray(z.astype(np.float32)).resize((750,550),Image.Resampling.BOX)) for z in planes]
        out=down[0] if len(down)==1 else np.stack(down,axis=2)
        return Image.fromarray(display(out)).convert('RGB')
    gray = rgb @ np.array([.2126,.7152,.0722])
    canvas=Image.new('RGB',(2330,690),'#141619');draw=ImageDraw.Draw(canvas)
    for i,(name,values) in enumerate([('彩色显影参考',rgb),('RGB 线性亮度参考',gray),('toMONO · C01 绿色响应',mono)]):
        px=20+i*770;draw.text((px,22),name,font=title,fill='#f2f3f5');canvas.paste(overview(values),(px,78))
    draw.text((20,650),'不同响应路径的外观示例，不作为解析力排名；共同 Gamma 2.2 / 0 EV，无逐图明暗拉齐。',font=small,fill='#a9b0b9')
    canvas.save(args.output/'response-comparison.png',icc_profile=preview_icc(True))
    manifest['response_comparison']={'xywh_full_raw':[x,y,w,h], 'rgb':'LibRaw camera WB, linear sRGB, no auto brightness',
        'rgb_gray':'linear sRGB Y = 0.2126 R + 0.7152 G + 0.0722 B; one defined example, not all desaturation tools',
        'mono':'current C01, G only, correction off', 'overview':'linear BOX area reduction to 750x550 before gamma'}
    (args.output/'comparison-provenance.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    assert source_hash == hashlib.sha256(args.input.read_bytes()).hexdigest()
    print('Generated 3 comparison figures; source unchanged.')

if __name__ == '__main__':
    main()
