"""Validated computation, atomic DNG publication, and independent sidecar status."""
import ctypes,hashlib,json,os,time,uuid
from pathlib import Path
import numpy as np
from recipe import Recipe
from execution_log import event
from metadata_params import parameters_from_dng
from raw_input import decode_sensor
from dng_writer import source_structure,write_dng
from defect_map import repair_sensor_map

class Cancelled(Exception):pass

def _compute_detail_response(mosaic,pattern,blacks,whites,black,white,frame,m,parameters,structure,active,recipe,progress):
    from channel_response import response_weights
    from detail_reconstruction import reconstruct_response,method_info
    if recipe.detail_mode=='lmmse':
        from lmmse_reconstruction import reconstruct_response,method_info
    same_colour=recipe.detail_mode!='lmmse'
    p=np.asarray(pattern,np.uint8);weights=response_weights(recipe);targets=[int(t) for t in np.flatnonzero(weights)]
    defects=[]
    for target in targets:
        report=repair_sensor_map(mosaic,p,recipe.defect_profile,structure,list(frame.samples.shape),active,target=target)
        defects.append(dict(report,target_channel=('R','G','B')[target]))
    defect=dict(mode='explicit_sensor_map' if recipe.defect_profile is not None else 'off',
                repaired=sum(r['repaired'] for r in defects),per_target=defects)
    pixels,stats,changed=reconstruct_response(mosaic,p,blacks,whites,weights,recipe.detail_mode,
        black,white,recipe.response_exposure,progress,green_correction=parameters,
        defer_quantization=recipe.lens_correction is not None)
    response=dict(mode=recipe.response_mode,weights=weights.tolist(),exposure_ev=recipe.response_exposure,
        applied=True,reference_exact=False,selected_kernel_same_colour=same_colour,
        digital_channel_isolation=bool(same_colour and len(targets)==1 and not parameters.get('green_compensation',0)),
        channel_method=method_info(recipe.detail_mode)['code']+' '+recipe.detail_mode,
        normalization='Per-phase float64(DN-black)/(white-black); selected corrections before interpolation; no WB or automatic exposure',
        quantization='Float channel reconstruction and float64 measured restoration/mixing; explicit EV; one final rint',
        physical_profile_calibrated=False,warnings=[],**stats)
    if stats['container_clipped_low'] or stats['container_clipped_high']:
        response['warnings'].append(f"响应处理有{stats['container_clipped_low']+stats['container_clipped_high']}个采样超出16位容器并被限制，请降低响应曝光。")
    h,w=mosaic.shape
    m.update(source_shape=list(frame.samples.shape),shape=[h,w],source_active_area=list(active),
        source_black_levels=frame.metadata['black_level_by_libraw_channel'],source_white_level=frame.metadata['white_level'],
        black_level_by_libraw_channel=[black]*4,white_level=white,cfa_codes_full_origin=p.tolist(),
        visible_area=dict(top=0,left=0,height=h,width=w),normalization=[])
    parameters.update(processing_path='detail_'+recipe.detail_mode,requested_detail_mode=recipe.detail_mode,
        effective_detail_mode=recipe.detail_mode,detail_fallback_reason=None,detail_method_code=method_info(recipe.detail_mode)['code'],
        detail_response_complete=True,detail_reconstruction=method_info(recipe.detail_mode),
        detail_channels=[dict(target_channel=('R','G','B')[t],**method_info(recipe.detail_mode,t)) for t in targets],
        requested_algorithm=recipe.algorithm,source_active_area=list(active),output_black=black,output_white=white,
        source_black_levels_2x2=np.asarray(blacks).tolist(),source_white_levels_2x2=np.asarray(whites).tolist(),
        pattern=p.tolist(),normalization=[],defect_repair=defect,response=response,
        green_replacements=changed,cpu_workers=stats['cpu_workers'],acceleration=('Bounded multicore official IPOL LMMSE tiles; deterministic 16px halos' if not same_colour else 'Bounded multicore NumPy FIR FFT tiles with cached kernel spectra; deterministic 48px halos'),
        green_correction_policy='Selected G-difference policy on normalized float64 observations before kernels; optional R/B eligibility gate is explicit preprocessing' if parameters.get('green_compensation',0) else 'Off',
        measured_samples='Selected observations after explicit defect/G correction hard-restored in float64 before mixing/EV; one final container quantization',
        research_condition_difference='Frozen research disabled defect/G/lens corrections. Product uses the selected recipe corrections.',
        scope=('Experimental cross-colour LMMSE; all CFA colours guide estimates; ordinary photos only' if not same_colour else 'Linear same-colour detail reconstruction; no Nyquist-exceeding recovery or physical spectral-unmixing claim'))
    return pixels,m,parameters,dict(structure,active_area=[0,0,h,w]),changed,frame

def _compute_sensor_monochrome(source,recipe=None,progress=None,diagnostics=False):
    source=Path(source).resolve()
    recipe=Recipe.from_dict((recipe or Recipe()).to_dict())
    if not source.is_file():raise ValueError('输入文件不存在')
    def notify(phase,fraction):
        event('compute_stage',phase=phase,progress=fraction,source=str(source))
        if progress:progress({'type':'progress','phase':phase,'progress':fraction})
    notify('解码原始采样',.03)
    retain=diagnostics or recipe.response_mode not in ('green','narrow_green')
    frame=decode_sensor(source,retain_channels=retain);m=dict(frame.metadata)
    full_h,full_w=frame.samples.shape
    try:structure=source_structure(source,(full_h,full_w),m)
    except ValueError as exc:
        if m.get('linear_reconstruction'):raise
        event('libraw_linear_fallback',reason=str(exc),source=str(source))
        frame=decode_sensor(source,force_linear=True,retain_channels=retain);m=dict(frame.metadata);full_h,full_w=frame.samples.shape
        structure=source_structure(source,(full_h,full_w),m)
    if recipe.lens_correction is not None and structure.get('lens_correction_already_applied'):raise ValueError('此文件已经应用toMONO镜头校正，请关闭额外镜头校正，避免重复处理')
    identity=structure.get('camera_identity',{})
    origin=recipe.camera_identity
    mismatch=bool(origin and (any(str(origin.get(k,'')).strip().casefold()!=str(identity.get(k,'')).strip().casefold() for k in ('make','model')) or (origin.get('serial') and origin.get('serial')!=identity.get('serial'))))
    event('preset_camera_scope',camera=identity,preset_camera=origin,matches=not mismatch)
    if mismatch and recipe.defect_profile is not None:raise ValueError('预设中的坏点坐标来自另一相机或机身编号无法核对，请关闭坏点修复后再转换')
    parameters=None
    if structure.get('source_kind', 'DNG' if source.suffix.lower()=='.dng' else 'RAW')=='DNG' and not m.get('linear_reconstruction') and m.get('sensor_layout','bayer')=='bayer':
        try:parameters=parameters_from_dng(source)
        except ValueError as exc:
            event('libraw_linear_fallback',reason=str(exc),source=str(source))
            frame=decode_sensor(source,force_linear=True,retain_channels=retain);m=dict(frame.metadata);full_h,full_w=frame.samples.shape
            structure=source_structure(source,(full_h,full_w),m)
    if parameters is None:
        wb=m.get('camera_whitebalance',[1,1,1,1])
        green=[float(wb[i]) for i in (1,3) if i<len(wb) and wb[i]>0]
        g=sum(green)/len(green) if green else 1.0
        neutral=[g/float(wb[i]) if i<len(wb) and wb[i]>0 else 1.0 for i in (0,1,2)]
        neutral=[x/max(neutral) for x in neutral]
        parameters=dict(model=structure.get('Model','RAW相机'),camera_white=neutral,green_compensation=0.0,
            focus_red=False,focus_blue=False,preset='generic_bayer',
            provenance='LibRaw unpack and reciprocal camera white balance; generic Bayer reconstruction',
            scope='Generic Bayer; not a Windows-equivalence profile')
    parameters['camera_identity']=identity
    parameters['preset_camera_matches']=not mismatch
    parameters.update(requested_detail_mode=recipe.detail_mode,effective_detail_mode='legacy',
        detail_fallback_reason=None if recipe.detail_mode=='legacy' else 'Input is not a directly unpacked 2x2 RGB Bayer CFA')
    if m.get('linear_reconstruction'):
        if recipe.defect_profile is not None:raise ValueError('缺陷图仅适用于直接读取原始采样的路径，不能对已线性重建的像素重复修复')
        parameters.update(preset=m['sensor_layout'],processing_path=m['sensor_layout'],green_compensation=0.0,output_black=0,output_white=65535,
            provenance=m['processing'],scope='LibRaw linear reconstruction; no Windows-equivalence claim')
        event('linear_reconstruction_complete',source=str(source),model=parameters.get('model'),shape=[full_h,full_w],parameters=parameters)
        return frame.samples,m,parameters,structure,0,frame
    if recipe.green_mode=='off':parameters['green_compensation']=0.0
    elif recipe.green_mode=='manual':parameters.update(green_compensation=recipe.compensation,focus_red=recipe.focus_red,focus_blue=recipe.focus_blue)
    if recipe.response_mode in ('narrow_red','narrow_blue') or (recipe.response_mode=='mix' and recipe.response_green==0):
        parameters['green_compensation']=0.0
    active=list(map(int,structure.get('active_area',[0,0,full_h,full_w])))
    top,left,bottom,right=active
    mosaic=np.array(frame.samples[top:bottom,left:right],dtype=np.uint16,order='C',copy=True);h,w=mosaic.shape
    if h<8 or w<8:raise ValueError('有效RAW区域小于8×8，无法重建')
    full_pattern=m['cfa_codes_full_origin'];channels=m.get('cfa_libraw_channels_full_origin',[[0,1],[3,2]])
    rows,cols=len(full_pattern),len(full_pattern[0])
    pattern=[[full_pattern[(y+top)%rows][(x+left)%cols] for x in range(cols)] for y in range(rows)]
    active_channels=[[channels[(y+top)%rows][(x+left)%cols] for x in range(cols)] for y in range(rows)]
    blacks=list(map(int,m['black_level_by_libraw_channel']));sensor_white=int(m['white_level'])
    green_channels=[active_channels[y][x] for y in range(rows) for x in range(cols) if pattern[y][x]==1]
    green_channel=green_channels[0];black=blacks[green_channel]
    whites=m.get('white_level_by_libraw_channel') or [sensor_white]*4
    candidate=whites[green_channel] if green_channel<len(whites) else None
    white=int(candidate) if candidate is not None and black<candidate<=65535 else sensor_white
    if not 0<=black<white<=65535:raise ValueError('RAW黑白电平无效或超出16位整数范围')
    valid_bayer=(rows,cols)==(2,2) and tuple(np.asarray(pattern).ravel()) in ((0,1,1,2),(2,1,1,0),(1,0,2,1),(1,2,0,1))
    if recipe.detail_mode!='legacy' and valid_bayer:
        phase_blacks=np.empty((2,2),np.float64);phase_whites=np.empty((2,2),np.float64)
        for y in range(2):
            for x in range(2):
                c=active_channels[y][x];phase_blacks[y,x]=blacks[c]
                cw=whites[c] if c<len(whites) else None
                phase_whites[y,x]=cw if cw is not None and phase_blacks[y,x]<cw<=65535 else sensor_white
        return _compute_detail_response(mosaic,pattern,phase_blacks,phase_whites,black,white,frame,m,parameters,structure,active,recipe,progress)
    normalization=[]
    for y in range(rows):
        for x in range(cols):
            channel=active_channels[y][x];cb=blacks[channel]
            cw=int(whites[channel]) if channel<len(whites) and whites[channel] is not None and whites[channel]>cb else white
            if not 0<=cb<cw<=65535:raise ValueError('RAW分通道黑白电平无效')
            if cb!=black or cw!=white:
                values=mosaic[y::rows,x::cols].astype(np.float64)
                values=(values-cb)*((white-black)/(cw-cb))+black
                mosaic[y::rows,x::cols]=np.clip(np.rint(values),0,65535).astype(np.uint16)
                normalization.append({'channel':channel,'source_black':cb,'source_white':cw,'output_black':black,'output_white':white})
    m.update(source_shape=[full_h,full_w],shape=[h,w],source_active_area=active,
        source_black_levels=blacks,source_white_level=sensor_white,white_level=white,black_level_by_libraw_channel=[black]*4,
        cfa_codes_full_origin=pattern,visible_area={'top':0,'left':0,'height':h,'width':w},normalization=normalization)
    structure=dict(structure,active_area=[0,0,h,w])
    defect=repair_sensor_map(mosaic,pattern,recipe.defect_profile,structure,[full_h,full_w],active)
    parameters['defect_repair']=defect
    event('defect_map',**defect)
    reference=(recipe.algorithm=='Bicubic' and parameters.get('preset','reference_bicubic')=='reference_bicubic' and pattern==[[0,1],[1,2]] and not normalization and white==16383)
    if parameters['green_compensation'] and pattern!=[[0,1],[1,2]]:raise ValueError('手动绿色差异校正目前需要RGGB排列；可以使用自动或关闭模式')
    event('raw_decoded',source=str(source),model=parameters.get('model'),raw_ifd=structure.get('raw_ifd'),
        source_shape=[full_h,full_w],active_area=active,output_shape=[h,w],pattern=pattern,black=black,white=white,normalization=normalization,preset=parameters.get('preset'))
    lib=ctypes.CDLL(str(Path(__file__).parent/'build/native-macos/libtomono_core.dylib'))
    lib.tomono_worker_count.restype=ctypes.c_uint
    parameters.update(cpu_workers=lib.tomono_worker_count(),acceleration='CPU row-parallel; deterministic; no GPU RAW kernel',requested_algorithm=recipe.algorithm)
    ptr=ctypes.POINTER(ctypes.c_uint16)
    class GP(ctypes.Structure):
        _fields_=[('compensation',ctypes.c_float),('red_white',ctypes.c_float),('blue_white',ctypes.c_float),('focus_red',ctypes.c_int),('focus_blue',ctypes.c_int)]
    gp=GP(parameters['green_compensation'],parameters['camera_white'][0],parameters['camera_white'][2],parameters['focus_red'],parameters['focus_blue'])
    parameters['green_compensation']=float(gp.compensation)
    correct=lib.tomono_correct_green_rggb;correct.restype=ctypes.c_int
    correct.argtypes=[ptr,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.POINTER(GP),ctypes.POINTER(ctypes.c_size_t)]
    changed=ctypes.c_size_t();notify('应用绿色差异校正',.32)
    if correct(mosaic.ctypes.data_as(ptr),mosaic.size,w,h,ctypes.byref(gp),ctypes.byref(changed)):raise RuntimeError('绿色校正失败')
    pixels=np.empty_like(mosaic);notify('重建单通道图像',.47)
    if (rows,cols)!=(2,2):
        peak=max(white,*[int(mosaic[y::rows,x::cols].max()) for y in range(rows) for x in range(cols) if pattern[y][x]==1])
        ceiling=min(65535,(1<<peak.bit_length())-1)
        reconstruct=lib.tomono_green_lattice_plane
        reconstruct.restype=ctypes.c_int
        reconstruct.argtypes=[ptr,ctypes.c_size_t,ptr,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        if reconstruct(mosaic.ctypes.data_as(ptr),mosaic.size,pixels.ctypes.data_as(ptr),pixels.size,w,h,(ctypes.c_uint8*(rows*cols))(*sum(pattern,[])),rows,cols,ceiling):raise RuntimeError('绿色采样重建失败')
        parameters.update(processing_path='generic_green_lattice',interpolation_ceiling=ceiling,output_black=black,output_white=white,normalization=normalization,source_active_area=active,
            scope='General repeating-CFA green reconstruction; no Windows-equivalence claim',provenance='LibRaw unpack and native green-lattice reconstruction')
        event('reconstruction_complete',pixels=int(pixels.size),parameters=parameters)
        return pixels,m,parameters,structure,0,frame
    if recipe.algorithm in ('Auto','EdgeAware'):
        peak=max(white,*[int(mosaic[y::2,x::2].max()) for y in range(2) for x in range(2) if pattern[y][x]==1])
        ceiling=min(65535,(1<<peak.bit_length())-1)
        reconstruct=lib.tomono_edge_green_plane;reconstruct.restype=ctypes.c_int
        reconstruct.argtypes=[ptr,ctypes.c_size_t,ptr,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_uint8),ctypes.c_uint]
        if reconstruct(mosaic.ctypes.data_as(ptr),mosaic.size,pixels.ctypes.data_as(ptr),pixels.size,w,h,(ctypes.c_uint8*4)(*sum(pattern,[])),ceiling):raise RuntimeError('边缘自适应重建失败')
        parameters.update(processing_path='edge_aware_green',interpolation_ceiling=ceiling,output_black=black,output_white=white,normalization=normalization,source_active_area=active,
            scope='Experimental green-only edge-aware reconstruction; not VNG or a physical monochrome sensor',
            selection_reason='2x2 Bayer: local green gradients weight horizontal and vertical estimates; measured green preserved after selected corrections')
        event('reconstruction_complete',pixels=int(pixels.size),green_replacements=changed.value,parameters=parameters)
        return pixels,m,parameters,structure,changed.value,frame
    args=[mosaic.ctypes.data_as(ptr),mosaic.size,pixels.ctypes.data_as(ptr),pixels.size,w,h,(ctypes.c_uint8*4)(*sum(pattern,[])),0,0]
    types=[ptr,ctypes.c_size_t,ptr,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_uint8),ctypes.c_int,ctypes.c_int]
    if reference:
        interpolate=lib.tomono_bicubic_green_plane;ceiling=16383
    else:
        peak=max(white,*[int(mosaic[y::2,x::2].max()) for y in range(2) for x in range(2) if pattern[y][x]==1])
        ceiling=min(65535,(1<<peak.bit_length())-1)
        interpolate=lib.tomono_bicubic_green_plane_range;args.append(ceiling);types.append(ctypes.c_uint)
    interpolate.restype=ctypes.c_int;interpolate.argtypes=types
    if interpolate(*args):raise RuntimeError('Bicubic处理失败')
    parameters.update(interpolation_ceiling=ceiling,processing_path='reference' if reference else 'generic_bayer',source_active_area=active,output_black=black,output_white=white,normalization=normalization)
    event('reconstruction_complete',pixels=int(pixels.size),green_replacements=changed.value,parameters=parameters)
    return pixels,m,parameters,structure,changed.value,frame

def compute_monochrome(source,recipe=None,progress=None,diagnostics=False):
    recipe=recipe or Recipe()
    from channel_response import apply_response,raw_channel_histogram
    if recipe.response_mode in ('narrow_red','narrow_green','narrow_blue'):
        from pure_narrowband import compute_pure_narrowband
        pixels,metadata,parameters,structure,changed,frame=compute_pure_narrowband(source,recipe,progress)
    else:
        pixels,metadata,parameters,structure,changed,frame=_compute_sensor_monochrome(source,recipe,progress,diagnostics)
        pixels=apply_response(pixels,metadata,parameters,structure,frame,recipe,progress)
    if diagnostics:
        def checkpoint():
            if progress:progress({'type':'progress','phase':'统计原始RGB采样','progress':.59})
        parameters['raw_histogram']=raw_channel_histogram(frame,metadata,structure,checkpoint)
    parameters['green_replacements']=int(changed)
    parameters['reconstruction_sample_count']=int(pixels.size)
    parameters['lens_capture']=structure.get('lens_metadata',{})
    if recipe.lens_correction is not None:
        from lens_correction import apply_lens
        def checkpoint():
            if progress:progress({'type':'progress','phase':'应用镜头校正','progress':.59})
        pixels,metadata,parameters,structure=apply_lens(pixels,metadata,parameters,structure,recipe.lens_correction,checkpoint)
        if parameters.get('detail_response_complete'):
            parameters['response']['quantization']='Float channel reconstruction/measurement restoration/mixing and EV; one final quantization after selected lens correction'
            if parameters.get('lens_correction',{}).get('applied'):
                parameters['measured_samples']+='; selected lens correction subsequently changes positions/values'
            if pixels.dtype!=np.uint16:
                # A valid no-op lens configuration returns the unquantized input.
                # Finalize it here once, rather than forcing an integer image
                # between reconstruction and a potential lens transform.
                finalized=np.rint(pixels)
                low=int(np.count_nonzero(finalized<0));high=int(np.count_nonzero(finalized>65535))
                pixels=np.clip(finalized,0,65535).astype(np.uint16)
                parameters['response'].update(container_clipped_low=low,container_clipped_high=high)
                if low or high:parameters['response']['warnings'].append(f'最终输出有{low+high}个采样超出16位容器，已限制到可存储范围。')
        event('lens_correction_complete',parameters=parameters.get('lens_correction'))
    if diagnostics:
        parameters['inspection_regions']=_preview_inspection(frame,metadata,parameters,structure,recipe)
    del frame
    return pixels,metadata,parameters,structure,changed

def _preview_inspection(frame,metadata,parameters,structure,recipe):
    """Source-based inspection suggestions; never a pixel correction."""
    from preview_inspection import inspection_regions
    orientation=int(structure.get('Orientation',1))
    cw,ch=map(int,structure['crop_size'])
    size=[ch,cw] if orientation>=5 else [cw,ch]
    def center():
        w,h=min(192,size[0]),min(192,size[1])
        return dict(version=1,source='output_centre',native_size=size,
                    regions=[dict(rect=[(size[0]-w)//2,(size[1]-h)//2,w,h],reason='画面中心',score=0)])
    m=frame.metadata;p=m.get('cfa_codes_full_origin')
    if (m.get('linear_reconstruction') or not p or np.shape(p)!=(2,2)
            or parameters.get('lens_correction',{}).get('applied')):return center()
    channels=np.asarray(m['cfa_libraw_channels_full_origin']);blacks=np.asarray(m['black_level_by_libraw_channel'],float)[channels]
    whites=np.asarray(m.get('white_level_by_libraw_channel') or [m['white_level']]*4,float)[channels]
    whites=np.where(np.isfinite(whites)&(whites>blacks),whites,m['white_level'])
    source_active=parameters.get('source_active_area') or metadata.get('source_active_area') or _source_visible_active(frame)
    top,left=map(int,source_active[:2]);x,y=map(int,structure['crop_origin'])
    target={'narrow_red':0,'narrow_green':1,'narrow_blue':2}.get(recipe.response_mode,1)
    if recipe.response_mode=='mix' and not recipe.response_green:target=0 if recipe.response_red>=recipe.response_blue else 2
    try:return inspection_regions(frame.samples,np.asarray(p),blacks,whites,crop=(left+x,top+y,cw,ch),orientation=orientation,target=target)
    except ValueError as exc:
        event('preview_inspection_fallback',reason=str(exc));return center()

def _source_visible_active(frame):
    visible=frame.metadata['visible_area']
    return [visible['top'],visible['left'],visible['top']+visible['height'],visible['left']+visible['width']]

def convert_and_save(source,output,recipe=None,report_path=None,progress=None):
    source=Path(source).resolve();output=Path(output).resolve()
    recipe=Recipe.from_dict((recipe or Recipe()).to_dict())
    report_path=Path(report_path).resolve() if report_path is not None else output.with_suffix('.processing.json')
    if not source.is_file():raise ValueError('输入文件不存在')
    if source==output or report_path in (source,output):raise ValueError('原图、输出和处理记录必须使用不同路径')
    if output.suffix.lower()!='.dng':raise ValueError('输出扩展名必须为.dng')
    if output.exists():raise FileExistsError('输出文件已存在，请选择新的文件名')
    start=time.perf_counter()
    pixels,m,parameters,structure,replacements=compute_monochrome(source,recipe,progress)
    h,w=pixels.shape;blacks=m['black_level_by_libraw_channel']
    def notify(phase,fraction):
        if progress:progress({'type':'progress','phase':phase,'progress':fraction})
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.parent/('.tomono-'+uuid.uuid4().hex+'.dng')
    try:
        notify('写入DNG与拍摄信息',.68)
        metadata=write_dng(source,temporary,pixels,blacks[0],m['white_level'],structure,recipe)
        metadata.setdefault('warnings',[]).extend(parameters.get('response',{}).get('warnings',[]))
        result={'type':'result','state':'saved','dng_saved':True,'sidecar_saved':False,'input':str(source),'output':str(output),
            'report':str(report_path),'recipe':recipe.to_dict(),'resolved_parameters':parameters,
            'shape':[h,w],'pixels':int(pixels.size),'green_replacements':replacements,
            'raw_sha256':hashlib.sha256(memoryview(pixels)).hexdigest(),'roundtrip_exact':True,
            'metadata':metadata,'warnings':list(metadata.get('warnings',[])),'seconds':time.perf_counter()-start,
            'scope':parameters.get('scope','Reference Bicubic path')}
        notify('完成文件校验，准备保存',.94)
        os.link(temporary,output)  # exclusive publication, never replace an existing path
    finally:
        if temporary.exists():temporary.unlink()
    result['metadata']['metadata_validation']['SourceFile']=str(output)
    if result['warnings']:result['state']='saved_with_warning'
    # A successfully published DNG stays successful when optional sidecar fails.
    sidecar_temporary=None
    try:
        report_path.parent.mkdir(parents=True,exist_ok=True)
        sidecar=dict(result,sidecar_saved=True)
        sidecar_temporary=report_path.parent/('.tomono-report-'+uuid.uuid4().hex+'.json')
        with sidecar_temporary.open('x',encoding='utf-8') as stream:
            json.dump(sidecar,stream,ensure_ascii=False,indent=2)
        os.link(sidecar_temporary,report_path)
        result['sidecar_saved']=True
    except Exception as exc:
        result['state']='saved_with_warning'
        result['warnings'].append('DNG已成功保存，但处理记录未写入：'+str(exc))
    finally:
        if sidecar_temporary is not None and sidecar_temporary.exists():sidecar_temporary.unlink()
    event('dng_saved',output=str(output),report=str(report_path),state=result['state'],dng_saved=True,sidecar_saved=result['sidecar_saved'],warnings=result['warnings'])
    return result
