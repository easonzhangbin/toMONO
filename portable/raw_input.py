"""LibRaw sensor unpack, with explicit linear reconstruction for complex layouts."""
import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import rawpy


@dataclass
class SensorFrame:
    samples: np.ndarray
    metadata: dict
    linear_channels: np.ndarray|None=None


def decode_sensor(path,force_linear=False,retain_channels=False):
    try:decoder=rawpy.imread(str(path))
    except rawpy.LibRawError as exc:raise ValueError('LibRaw 无法读取此文件：'+str(exc)) from exc
    with decoder as raw:
        sizes=raw.sizes;desc=raw.color_desc.decode('ascii',errors='replace').rstrip('\0')
        try:pattern=raw.raw_pattern
        except (NotImplementedError,rawpy.LibRawError):pattern=None
        channels=None;codes=None;layout='libraw_linear'
        if raw.raw_type==rawpy.RawType.Flat and pattern is not None and pattern.shape==(2,2):
            channels=[[int(raw.raw_color(y,x)) for x in range(2)] for y in range(2)]
            colors=[[desc[c] for c in row] for row in channels]
            if sorted(c for row in colors for c in row)==['B','G','G','R']:
                codes=[[{'R':0,'G':1,'B':2}[c] for c in row] for row in colors]
                if all(codes[y][x]!=codes[y][1-x] and codes[y][x]!=codes[1-y][x] for y in range(2) for x in range(2)):layout='bayer'
        geometry_requires_processing=(abs(getattr(sizes,'pixel_aspect',1.0)-1.0)>1e-6 or getattr(sizes,'iwidth',sizes.width)!=sizes.width or getattr(sizes,'iheight',sizes.height)!=sizes.height)
        if force_linear or geometry_requires_processing:layout='libraw_linear'
        if not force_linear and not geometry_requires_processing and layout!='bayer' and raw.raw_type==rawpy.RawType.Flat and pattern is not None and max(pattern.shape)<=16:
            rows,cols=pattern.shape
            channels=[[int(raw.raw_color(y,x)) for x in range(cols)] for y in range(rows)]
            monochrome=getattr(raw,'num_colors',3)==1
            if monochrome:channels=[[0 for _ in range(cols)] for _ in range(rows)]
            codes=[[1 if monochrome else {'R':0,'G':1,'B':2}.get(desc[c],-1) for c in row] for row in channels]
            if any(1 in row for row in codes) and all(c>=0 for row in codes for c in row):layout='green_lattice'
        blacks=list(raw.black_level_per_channel);white=int(raw.white_level)
        channel_whites=raw.camera_white_level_per_channel
        wb=list(raw.camera_whitebalance)
        linear=False;linear_channels=None
        if layout in ('bayer','green_lattice'):
            samples=raw.raw_image.copy()
            if samples.dtype!=np.uint16:layout='libraw_linear'
        if layout not in ('bayer','green_lattice'):
            raw_rgb=all(c in desc for c in 'RGB')
            image=raw.postprocess(output_color=rawpy.ColorSpace.raw if raw_rgb else rawpy.ColorSpace.sRGB,
                output_bps=16,gamma=(1,1),user_wb=[1,1,1,1],use_camera_wb=False,use_auto_wb=False,
                no_auto_bright=True,adjust_maximum_thr=0,bright=1,user_flip=0,median_filter_passes=0)
            if image.ndim==2:samples=np.ascontiguousarray(image)
            elif raw_rgb:samples=np.ascontiguousarray(image[:,:,min(1,image.shape[2]-1)])
            else:samples=np.clip(np.rint(image[:,:,:3].astype(np.float64)@np.array([.2126,.7152,.0722])),0,65535).astype(np.uint16)
            linear=True;layout='libraw_linear_green' if raw_rgb else 'libraw_linear_luminance'
            if retain_channels and image.ndim==3:linear_channels=image[:,:,:3]
        h,w=samples.shape
        metadata={
            'source':str(Path(path).resolve()),'rawpy_version':rawpy.__version__,'libraw_version':list(rawpy.libraw_version),
            'shape':[h,w],'dtype':str(samples.dtype),'sensor_layout':layout,'linear_reconstruction':linear,
            'cfa_codes_full_origin':codes,'cfa_libraw_channels_full_origin':channels,'color_desc':desc,
            'black_level_by_libraw_channel':[0]*4 if linear else blacks,
            'source_black_levels':blacks,'white_level':65535 if linear else white,'source_white_level':white,
            'white_level_by_libraw_channel':None if linear else channel_whites,
            'visible_area':{'top':0,'left':0,'height':h,'width':w} if linear else {'top':sizes.top_margin,'left':sizes.left_margin,'height':sizes.height,'width':sizes.width},
            'default_crop':{'left':0,'top':0,'width':w,'height':h} if linear else {'left':sizes.crop_left_margin,'top':sizes.crop_top_margin,'width':sizes.crop_width,'height':sizes.crop_height},
            'orientation_flip':sizes.flip,'camera_whitebalance':wb,
            'processing':'LibRaw linear reconstruction; no WB/gamma/auto brightness; camera-green or linear luminance' if linear else 'LibRaw unpack only; no postprocess, normalization, WB, gamma or rotation',
            'minimum':int(samples.min()),'maximum':int(samples.max())}
        return SensorFrame(samples,metadata,linear_channels)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', type=Path)
    p.add_argument('--metadata', required=True, type=Path)
    p.add_argument('--samples', type=Path, help='Optional full sensor array as .npy')
    args = p.parse_args()
    frame = decode_sensor(args.input)
    args.metadata.parent.mkdir(parents=True, exist_ok=True)
    args.metadata.write_text(json.dumps(frame.metadata, indent=2) + '\n')
    if args.samples:
        np.save(args.samples, frame.samples, allow_pickle=False)
    print(json.dumps(frame.metadata, indent=2))
