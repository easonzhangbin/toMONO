"""Strict selected-CFA-channel reconstruction for narrowband film captures.

No legacy green reconstruction, colour-guided correction, WB, automatic
exposure or histogram alignment enters this path. Sensor spectral overlap is
physical: selecting digital R/G/B sites does not undo their spectral response.
"""
import ctypes
from pathlib import Path

import numpy as np
import tifffile

from channel_response import source_view
from defect_map import repair_sensor_map
from dng_layout import select_raw_ifd
from dng_writer import source_structure
from execution_log import event
from raw_input import decode_sensor
from recipe import Recipe


def native_core():
    lib=ctypes.CDLL(str(Path(__file__).parent/'build/native-macos/libtomono_core.dylib'))
    lib.tomono_core_version.restype=ctypes.c_uint
    if lib.tomono_core_version()<0x402 or not hasattr(lib,'tomono_pure_channel_strip'):
        raise RuntimeError('纯通道转换核心版本不匹配，请重新安装完整的toMONO软件')
    u16=ctypes.POINTER(ctypes.c_uint16);u8=ctypes.POINTER(ctypes.c_uint8);f64=ctypes.POINTER(ctypes.c_double)
    lib.tomono_pure_channel_strip.argtypes=[u16,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,
        u8,ctypes.c_int,ctypes.c_int,f64,f64,ctypes.c_int,ctypes.c_int,f64,ctypes.c_size_t]
    lib.tomono_pure_channel_strip.restype=ctypes.c_int
    return lib


def channel_strips(samples,pattern,blacks,whites,target,interpolation='cubic',rows=256):
    """Yield float64 normalized strips; only the selected colour is read."""
    samples=np.asarray(samples)
    if samples.dtype!=np.uint16 or samples.ndim!=2 or min(samples.shape)<8:
        raise ValueError('纯通道重建需要至少8×8的16位原始CFA采样')
    pattern=np.asarray(pattern)
    valid=pattern.shape==(2,2) and tuple(pattern.ravel()) in (
        (0,1,1,2),(2,1,1,0),(1,0,2,1),(1,2,0,1))
    if not valid:raise ValueError('严格纯通道目前仅支持2×2 RGB Bayer排列，不能使用单色或其他CFA替代')
    if type(target)is not int or target not in (0,1,2):raise ValueError('纯通道目标必须为R、G或B')
    if interpolation not in ('cubic','linear'):raise ValueError('纯通道插值必须为cubic或linear')
    if type(rows)is not int or rows<1:raise ValueError('纯通道分块行数无效')
    samples=np.ascontiguousarray(samples);pattern=np.ascontiguousarray(pattern,np.uint8)
    blacks=np.ascontiguousarray(blacks,np.float64);whites=np.ascontiguousarray(whites,np.float64)
    if blacks.shape!=(2,2) or whites.shape!=(2,2) or not np.isfinite(blacks).all() or not np.isfinite(whites).all() or (blacks<0).any() or (whites>65535).any() or (whites<=blacks).any():
        raise ValueError('纯通道采样的黑白电平无效')
    h,w=samples.shape;lib=native_core();fn=lib.tomono_pure_channel_strip
    u16=ctypes.POINTER(ctypes.c_uint16);u8=ctypes.POINTER(ctypes.c_uint8);f64=ctypes.POINTER(ctypes.c_double)
    for start in range(0,h,rows):
        count=min(rows,h-start);output=np.empty((count,w),np.float64)
        status=fn(samples.ctypes.data_as(u16),samples.size,w,h,pattern.ctypes.data_as(u8),target,
            int(interpolation=='linear'),blacks.ctypes.data_as(f64),whites.ctypes.data_as(f64),start,count,
            output.ctypes.data_as(f64),output.size)
        if status:raise RuntimeError('严格纯通道重建失败，输入或核心参数无效')
        yield start,output


def compute_pure_narrowband(source,recipe,progress=None):
    source=Path(source).resolve();recipe=Recipe.from_dict(recipe.to_dict())
    if not source.is_file():raise ValueError('输入文件不存在')
    target={'narrow_red':0,'narrow_green':1,'narrow_blue':2}.get(recipe.response_mode)
    if target is None:raise ValueError('严格纯通道入口需要指定红、绿或蓝窄带模式')
    def notify(phase,fraction):
        event('compute_stage',phase=phase,progress=fraction,source=str(source))
        if progress:progress({'type':'progress','phase':phase,'progress':fraction})
    notify('读取纯通道原始采样',.03)
    frame=decode_sensor(source,retain_channels=False);m=dict(frame.metadata)
    if m.get('linear_reconstruction') or m.get('sensor_layout')!='bayer':
        raise ValueError('严格纯通道需要直接读取2×2 RGB Bayer原始采样；不接受已去马赛克、单色或LibRaw线性回退结果')
    full_h,full_w=frame.samples.shape
    # Unsupported DNG transformations are rejected here, never silently sent
    # through LibRaw postprocess, where cross-colour demosaicking can occur.
    try:structure=source_structure(source,(full_h,full_w),m)
    except ValueError as exc:raise ValueError('严格纯通道无法安全处理此文件：'+str(exc))from exc
    if structure.get('source_kind')=='DNG':
        with tifffile.TiffFile(source)as tif:
            if 'LinearizationTable'in select_raw_ifd(tif).tags:
                raise ValueError('严格纯通道尚未验证此DNG的LinearizationTable，不能将其当作线性采样')
    if recipe.lens_correction is not None and structure.get('lens_correction_already_applied'):
        raise ValueError('此文件已经应用toMONO镜头校正，请关闭额外镜头校正，避免重复处理')
    identity=structure.get('camera_identity',{});origin=recipe.camera_identity
    mismatch=bool(origin and(any(str(origin.get(k,'')).strip().casefold()!=str(identity.get(k,'')).strip().casefold()for k in ('make','model'))or(origin.get('serial')and origin.get('serial')!=identity.get('serial'))))
    if mismatch and recipe.defect_profile is not None:
        raise ValueError('预设中的坏点坐标来自另一机身，请关闭坏点修复或载入当前机身的坐标表')
    active=list(map(int,structure.get('active_area',[0,0,full_h,full_w])))
    source_metadata=dict(m,source_active_area=active)
    samples,pattern,blacks,whites,_=source_view(frame,source_metadata)
    valid=pattern is not None and pattern.shape==(2,2) and tuple(pattern.ravel())in(
        (0,1,1,2),(2,1,1,0),(1,0,2,1),(1,2,0,1))
    if not valid:raise ValueError('严格纯通道目前仅支持2×2 RGB Bayer，当前文件没有可验证的目标CFA排列')
    samples=samples.copy(order='C');h,w=samples.shape
    if min(h,w)<8:raise ValueError('纯通道有效采样区域小于8×8')
    # Repair the very buffer passed to the selected-channel kernel. The old
    # green path keeps repair_sensor_map's default target1 semantics unchanged.
    defect=repair_sensor_map(samples,pattern,recipe.defect_profile,structure,[full_h,full_w],active,target=target)
    defect=dict(defect,target_channel=('R','G','B')[target])
    gy,gx=np.argwhere(pattern==1)[0];black=int(blacks[gy,gx]);white=int(whites[gy,gx]);span=white-black
    gain=2.0**recipe.response_exposure;pixels=np.empty((h,w),np.uint16);below=above=at_white=0
    detail_stats={}
    if recipe.detail_mode!='legacy':
        from detail_reconstruction import reconstruct_response,method_info
        notify('准备纯通道细节重建',.34)
        pixels,detail_stats,_=reconstruct_response(samples,pattern,blacks,whites,np.eye(3)[target],
            recipe.detail_mode,black,white,recipe.response_exposure,progress,
            defer_quantization=recipe.lens_correction is not None)
        below=detail_stats['container_clipped_low'];above=detail_stats['container_clipped_high'];at_white=detail_stats['at_or_above_white']
        channel_method=method_info(recipe.detail_mode,target)['code']+' '+recipe.detail_mode
    else:
        notify('同色插值重建完整画面',.47)
        for start,signal in channel_strips(samples,pattern,blacks,whites,target,recipe.narrow_interpolation):
            if progress:progress({'type':'progress','phase':'纯通道同色重建','progress':.47+.11*start/h})
            mapped=np.rint(black+signal*(span*gain))
            below+=int(np.count_nonzero(mapped<0));above+=int(np.count_nonzero(mapped>65535))
            block=np.clip(mapped,0,65535).astype(np.uint16);at_white+=int(np.count_nonzero(block>=white))
            pixels[start:start+len(block)]=block
        channel_method='Strict same-colour '+recipe.narrow_interpolation
    response=dict(mode=recipe.response_mode,weights=np.eye(3)[target].tolist(),exposure_ev=recipe.response_exposure,
        applied=True,reference_exact=False,digital_channel_isolation=True,target_channel=('R','G','B')[target],
        channel_method=channel_method,
        normalization='Each selected phase uses recorded(DN-black)/(white-black), mapped to commonG container; no WB or automatic exposure',
        quantization='Float64 same-colour interpolation; one final rint to16-bit container after explicit EV',
        physical_profile_calibrated=False,container_clipped_low=below,container_clipped_high=above,
        at_or_above_white=at_white,output_samples=int(pixels.size),warnings=[])
    response.update(detail_stats,requested_detail_mode=recipe.detail_mode,effective_detail_mode=recipe.detail_mode)
    if below or above:response['warnings'].append(f'纯通道曝光有{below+above}个采样超出16位容器并被限制，请降低曝光。')
    parameters=dict(processing_path='pure_narrowband_'+(recipe.narrow_interpolation if recipe.detail_mode=='legacy' else recipe.detail_mode),
        scope='Strict selected-channel2x2Bayer reconstruction; no cross-colour pixel guidance or physical spectral-unmixing claim',
        model=structure.get('Model','RAW相机'),camera_identity=identity,preset_camera_matches=not mismatch,
        requested_algorithm=recipe.algorithm,narrow_interpolation=recipe.narrow_interpolation,
        selected_channel=('R','G','B')[target],source_active_area=active,output_black=black,output_white=white,
        source_black_levels_2x2=blacks.tolist(),source_white_levels_2x2=whites.tolist(),
        pattern=pattern.tolist(),normalization=[],green_compensation=0.,green_replacements=0,
        green_correction_policy='Not applied in strict narrowband; no R/B-guided G correction',
        defect_repair=defect,response=response,cpu_workers=int(native_core().tomono_worker_count()) if recipe.detail_mode=='legacy' else detail_stats['cpu_workers'],
        acceleration='Deterministic CPU row strips' if recipe.detail_mode=='legacy' else 'Bounded multicore NumPy FIR FFT tiles with cached kernel spectra; deterministic 48px halos',
        measured_samples='Normalized selected sites preserved before optional target defect repair/explicit EV; final DN may change with container scale',
        physical_caveat='Sensor spectral overlap is physical and is not removed by digital site selection')
    parameters.update(requested_detail_mode=recipe.detail_mode,effective_detail_mode=recipe.detail_mode,
        detail_fallback_reason=None,detail_response_complete=recipe.detail_mode!='legacy')
    if recipe.detail_mode!='legacy':
        parameters.update(detail_method_code=method_info(recipe.detail_mode,target)['code'],
            detail_reconstruction=method_info(recipe.detail_mode,target),
            research_condition_difference='Frozen research disabled defect/G/lens corrections; strict product also disables G correction but uses selected target defect/lens corrections.')
    m.update(source_shape=[full_h,full_w],shape=[h,w],source_active_area=active,
        source_black_levels=frame.metadata['black_level_by_libraw_channel'],source_white_level=frame.metadata['white_level'],
        black_level_by_libraw_channel=[black]*4,white_level=white,cfa_codes_full_origin=pattern.tolist(),
        visible_area=dict(top=0,left=0,height=h,width=w),normalization=[])
    structure=dict(structure,active_area=[0,0,h,w])
    event('pure_narrowband_complete',source=str(source),shape=[h,w],parameters=parameters)
    return pixels,m,parameters,structure,0,frame
