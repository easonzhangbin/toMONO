"""Linear RAW channel reconstruction and explicit spectral-response mixing.

Weights are user-selected relative sensor responses, not a measured physical
monochrome-camera profile. No white balance, auto exposure, tone curve or learned
detail is applied. Only the final mixed strip is quantized to integer DNG DN.
"""
import ctypes
from pathlib import Path
import numpy as np

def native_core():
    lib=ctypes.CDLL(str(Path(__file__).parent/'build/native-macos/libtomono_core.dylib'))
    lib.tomono_core_version.restype=ctypes.c_uint
    if lib.tomono_core_version()<0x401:raise RuntimeError('转换引擎版本不匹配，请使用完整的toMONO 0.8.1或更新安装包')
    return lib

def response_weights(recipe):
    if recipe.response_mode=='mix':
        weights=np.array([recipe.response_red,recipe.response_green,recipe.response_blue],np.float64)
        if not np.isfinite(weights).all() or weights.sum()<=0:raise ValueError('RGB响应至少需要一个大于零的比例')
        return weights/weights.sum()
    return np.eye(3,dtype=np.float64)[{'green':1,'narrow_red':0,'narrow_green':1,'narrow_blue':2}[recipe.response_mode]]

def source_view(frame,metadata):
    h,w=frame.samples.shape
    top,left,bottom,right=map(int,metadata.get('source_active_area',[0,0,h,w]))
    samples=np.ascontiguousarray(frame.samples[top:bottom,left:right])
    m=frame.metadata
    if m.get('linear_reconstruction'):return samples,None,None,None,None
    codes=m['cfa_codes_full_origin'];channels=m['cfa_libraw_channels_full_origin'];pr,pc=len(codes),len(codes[0])
    pattern=np.array([[codes[(y+top)%pr][(x+left)%pc] for x in range(pc)] for y in range(pr)],np.uint8)
    blacks=np.empty((pr,pc),np.float64);whites=np.empty_like(blacks)
    source_blacks=m['black_level_by_libraw_channel'];source_whites=m.get('white_level_by_libraw_channel')
    for y in range(pr):
        for x in range(pc):
            c=channels[(y+top)%pr][(x+left)%pc];black=source_blacks[c]
            white=source_whites[c] if source_whites and c<len(source_whites) and source_whites[c] is not None and source_whites[c]>black else m['white_level']
            if not 0<=black<white<=65535:raise ValueError('通道响应的原始黑白电平无效')
            blacks[y,x]=black;whites[y,x]=white
    return samples,pattern,blacks,whites,(top,left,bottom,right)

def raw_channel_histogram(frame,metadata,structure,checkpoint=None):
    samples,pattern,blacks,whites,_=source_view(frame,metadata)
    left,top=map(int,structure['crop_origin']);w,h=map(int,structure['crop_size'])
    crop=samples[top:top+h,left:left+w]
    channels=[];values=np.arange(65536,dtype=np.float64)
    for target,name in enumerate(('R','G','B')):
        bins=np.zeros(256,np.int64);count=low=high=0;signal_sum=0.0
        if pattern is None:
            if frame.linear_channels is None and target!=1:continue
            plane=frame.linear_channels[top:top+h,left:left+w,target] if frame.linear_channels is not None else crop
            phases=[(plane,0,65535)]
        else:
            pr,pc=pattern.shape;phases=[]
            for y in range(pr):
                for x in range(pc):
                    if pattern[y,x]!=target:continue
                    sy=(y-top)%pr;sx=(x-left)%pc
                    phases.append((crop[sy::pr,sx::pc],blacks[y,x],whites[y,x]))
        for plane,black,white in phases:
            dn=np.zeros(65536,np.int64)
            for y in range(0,plane.shape[0],256):
                if checkpoint:checkpoint()
                dn+=np.bincount(plane[y:y+256].ravel(),minlength=65536)
            normalized=np.clip((values-black)/(white-black),0,1)
            index=np.minimum((normalized*256).astype(np.int32),255)
            np.add.at(bins,index,dn)
            count+=int(plane.size);low+=int(dn[:int(black)+1].sum());high+=int(dn[int(white):].sum())
            signal_sum+=float(np.dot(normalized,dn))
        if count:channels.append(dict(name=name,bins=bins.tolist(),sample_count=count,black_clipped=low,white_clipped=high,mean_signal=signal_sum/count))
    return dict(scope='libraw_linear' if pattern is None else 'sensor_cfa',channels=channels,
        note='LibRaw linear reconstructed channels' if pattern is None else 'Original CFA samples, before green/defect/lens correction; no WB or auto exposure',
        crop_size=[w,h],normalization='Recorded per-channel black/white levels; each color histogram normalized by its own sample count')

def apply_response(pixels,metadata,parameters,structure,frame,recipe,progress=None):
    if parameters.get('detail_response_complete'):
        return pixels
    weights=response_weights(recipe);gain=2.0**recipe.response_exposure
    report=dict(mode=recipe.response_mode,weights=weights.tolist(),exposure_ev=recipe.response_exposure,
        normalization='Weights sum to one; recorded sensor black/white levels; no white balance or histogram matching',
        physical_profile_calibrated=False,quantization='Float channel reconstruction and float64 strip mixing; round once at final output',
        applied=False,reference_exact=False,warnings=[])
    parameters['response']=report
    report.update(requested_detail_mode=recipe.detail_mode,
        effective_detail_mode=parameters.get('effective_detail_mode','legacy'),
        detail_fallback_reason=parameters.get('detail_fallback_reason'))
    if np.array_equal(weights,[0,1,0]) and gain==1:
        report.update(reference_exact=True,channel_method='Existing green reference, bit-exact')
        return pixels
    samples,pattern,blacks,whites,_=source_view(frame,metadata)
    h,w=pixels.shape
    if samples.shape!=(h,w):raise ValueError('原始通道与单色重建的有效区域不一致')
    mono=pattern is not None and np.all(pattern==1)
    lib=None;fn=None
    if pattern is not None and not mono:
        pr,pc=pattern.shape
        blacks=np.ascontiguousarray(blacks,np.float64);whites=np.ascontiguousarray(whites,np.float64)
        lib=native_core();fn=lib.tomono_channel_strip
        u16=ctypes.POINTER(ctypes.c_uint16);u8=ctypes.POINTER(ctypes.c_uint8);f64=ctypes.POINTER(ctypes.c_double)
        fn.argtypes=[u16,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,u8,ctypes.c_int,ctypes.c_int,ctypes.c_int,f64,f64,ctypes.c_int,ctypes.c_int,f64,ctypes.c_size_t];fn.restype=ctypes.c_int
        for target,weight in enumerate(weights):
            if weight and not np.any(pattern==target):raise ValueError('此RAW没有所选的'+('红','绿','蓝')[target]+'色采样')
    if pattern is None and frame.linear_channels is None and (weights[0] or weights[2]):
        mono=True
    black=metadata['black_level_by_libraw_channel'][0];white=metadata['white_level'];span=white-black
    output=np.empty_like(pixels);below=above=white_count=0
    for start in range(0,h,256):
        rows=min(256,h-start)
        if progress:progress({'type':'progress','phase':'融合 RAW 单色响应','progress':.48+.10*(start/h)})
        mixed=np.zeros((rows,w),np.float64)
        for target,weight in enumerate(weights):
            if weight==0:continue
            if target==1 or mono:
                signal=(pixels[start:start+rows].astype(np.float64)-black)/span
            elif pattern is None:
                signal=frame.linear_channels[start:start+rows,:,target].astype(np.float64)/65535
            else:
                signal=np.empty((rows,w),np.float64)
                code=fn(samples.ctypes.data_as(u16),samples.size,w,h,pattern.ctypes.data_as(u8),pr,pc,target,blacks.ctypes.data_as(f64),whites.ctypes.data_as(f64),start,rows,signal.ctypes.data_as(f64),signal.size)
                if code:raise RuntimeError('RAW通道重建失败')
            mixed+=weight*signal
        mixed=np.rint(black+mixed*(span*gain))
        below+=int(np.count_nonzero(mixed<0));above+=int(np.count_nonzero(mixed>65535))
        block=np.clip(mixed,0,65535).astype(np.uint16);white_count+=int(np.count_nonzero(block>=white));output[start:start+rows]=block
    report.update(applied=True,channel_method='Monochrome source' if mono else 'LibRaw linear planes' if pattern is None else 'Bayer R/B bounded cubic; existing green reference' if pattern.shape==(2,2) else 'Repeating-CFA same-color IDW; existing green reference',
        container_clipped_low=below,container_clipped_high=above,at_or_above_white=white_count,output_samples=int(output.size))
    if below or above:report['warnings'].append(f'响应处理有{below+above}个采样超出16位容器范围并被截断，请降低响应曝光或检查输入。')
    parameters['processing_path']='raw_channel_response'
    parameters['scope']='Linear camera-channel response mixing; not a calibrated physical monochrome sensor or a Windows-equivalence path'
    return output
