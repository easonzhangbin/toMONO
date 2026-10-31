"""Monochrome DNG structure, metadata policy and strict write verification."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
import numpy as np
import tifffile
from metadata_params import values
from dng_reader import read_linear_output
from dng_layout import select_raw_ifd
from execution_log import event
from display_render import preview_icc,dng_xmp,output_camera_model,APPEARANCE_ID

CAPTURE_TAGS=['ExifIFD:ExposureTime','ExifIFD:FNumber','ExifIFD:ISO','ExifIFD:ExposureProgram',
 'ExifIFD:ExposureCompensation','ExifIFD:MeteringMode','ExifIFD:LightSource','ExifIFD:Flash',
 'ExifIFD:FocalLength','ExifIFD:FocalLengthIn35mmFormat','ExifIFD:MaxApertureValue',
 'ExifIFD:ShutterSpeedValue','ExifIFD:ApertureValue','ExifIFD:BrightnessValue',
 'ExifIFD:DateTimeOriginal','ExifIFD:CreateDate','ExifIFD:OffsetTime',
 'ExifIFD:OffsetTimeOriginal','ExifIFD:OffsetTimeDigitized','ExifIFD:SubSecTime',
 'ExifIFD:SubSecTimeOriginal','ExifIFD:SubSecTimeDigitized','ExifIFD:LensMake',
 'ExifIFD:LensModel','ExifIFD:LensInfo','ExifIFD:LensSerialNumber','ExifIFD:BodySerialNumber',
 'ExifIFD:CameraOwnerName','GPS:all']
DESCRIPTION_TAGS=['IFD0:Artist','IFD0:Copyright','IFD0:ImageDescription','XMP-dc:all',
 'XMP-xmp:Rating','XMP-xmp:Label','XMP-photoshop:Headline','XMP-photoshop:Credit',
 'XMP-photoshop:Source','XMP-photoshop:City','XMP-photoshop:State',
 'XMP-photoshop:Country','IPTC:Caption-Abstract','IPTC:Keywords','IPTC:CopyrightNotice']

def exiftool():
    p=os.environ.get('TOMONO_EXIFTOOL') or shutil.which('exiftool')
    if not p:raise RuntimeError('未找到元数据工具，请重新构建应用或安装ExifTool')
    return p

def source_structure(source,shape,decoded_metadata=None):
    h,w=shape
    result=subprocess.run([exiftool(),'-config','','-j','-n','-FileType','-Make','-Model','-UniqueCameraModel','-Orientation','-BodySerialNumber','-CameraSerialNumber','-SerialNumber','-LensMake','-LensModel','-LensID','-FocalLength','-FNumber','-ScaleFactor35efl','-Software','-ImageDescription',str(source)],capture_output=True,text=True)
    try:meta=json.loads(result.stdout)[0]
    except (ValueError,IndexError):meta={}
    if result.returncode:event('source_metadata_warning','warning',source=str(source),message=result.stderr or meta.get('Error','元数据读取不完整'))
    serial=next((str(meta[k]).strip() for k in ('BodySerialNumber','CameraSerialNumber','SerialNumber') if meta.get(k) is not None and str(meta[k]).strip() and set(str(meta[k]).strip())!={'0'}),None)
    identity={'make':str(meta.get('Make','')).strip(),'model':str(meta.get('Model','')).strip(),'serial':serial}
    lens_metadata={'make':meta.get('LensMake'),'model':meta.get('LensModel') or meta.get('LensID'),'focal':meta.get('FocalLength'),'aperture':meta.get('FNumber'),'crop_factor':meta.get('ScaleFactor35efl')}
    marker='[toMONO lens-corrected v1]'
    history=meta.get('ImageDescription','') if str(meta.get('Software','')).startswith('toMONO') and marker in str(meta.get('ImageDescription','')) else ''
    lens_fields={'lens_metadata':lens_metadata,'lens_correction_already_applied':bool(history),'source_description':str(meta.get('ImageDescription','')),'lens_history':history}
    if meta.get('FileType')=='DNG':
      with tifffile.TiffFile(source) as t:
        if decoded_metadata and decoded_metadata.get('linear_reconstruction'):
            p=t.pages[0]
            tags={name:p.tags[name].value for name in ('Make','Model','UniqueCameraModel','Orientation') if name in p.tags}
            tags.update(active_area=[0,0,h,w],crop_origin=[0,0],crop_size=[w,h],safe_render_tags=[],raw_ifd='LibRaw selected image',source_kind='DNG',camera_identity=identity)
            tags.update(lens_fields)
            return tags
        lattice=decoded_metadata.get('cfa_codes_full_origin') if decoded_metadata else None
        p=select_raw_ifd(t,allow_linear=bool(lattice and len(lattice)==1 and len(lattice[0])==1))
        if tuple(p.shape)!=(h,w):raise ValueError('DNG RAW目录与解码器给出的采样尺寸不一致')
        for name in ('OpcodeList1','OpcodeList2','OpcodeList3'):
            if name in p.tags:raise ValueError('原图包含尚未验证的DNG校正指令，暂不能保证导出一致性：'+name)
        for name in ('BlackLevelDeltaH','BlackLevelDeltaV'):
            if name in p.tags:raise ValueError('尚未接入DNG逐行/逐列黑电平修正：'+name)
        if values(p,'DefaultScale',[1,1])!=[1,1]:raise ValueError('非方形像素缩放尚未接入')
        active=values(p,'ActiveArea',[0,0,h,w]);origin=values(p,'DefaultCropOrigin',[0,0]);size=values(p,'DefaultCropSize',[w,h])
        if len(active)!=4 or not(0<=active[0]<active[2]<=h and 0<=active[1]<active[3]<=w):raise ValueError('原图有效区域无效')
        if len(origin)!=2 or len(size)!=2 or min(origin)<0 or min(size)<=0 or origin[0]+size[0]>active[3]-active[1] or origin[1]+size[1]>active[2]-active[0]:raise ValueError('原图裁切范围无效')
        tags={name:p.tags[name].value for name in ('Make','Model','UniqueCameraModel','Orientation') if name in p.tags}
        tags['safe_render_tags']=[(p.tags[name].code,int(p.tags[name].dtype),p.tags[name].count,p.tags[name].value,False)
            for name in ('BaselineExposure','BaselineNoise','BaselineSharpness','LinearResponseLimit') if name in p.tags]
        tags.update(active_area=active,crop_origin=origin,crop_size=size,raw_ifd=p.ifd_path,source_kind='DNG',camera_identity=identity)
        tags.update(lens_fields)
        return tags
    if decoded_metadata is None:raise ValueError('非DNG输入需要解码器尺寸信息')
    visible=decoded_metadata['visible_area']
    top,left,height,width=[int(visible[k]) for k in ('top','left','height','width')]
    if not(0<=top<top+height<=h and 0<=left<left+width<=w):raise ValueError('解码器有效区域无效')
    crop=decoded_metadata.get('default_crop',{})
    x=int(crop.get('left',left))-left;y=int(crop.get('top',top))-top
    cw=int(crop.get('width',width));ch=int(crop.get('height',height))
    if x<0 or y<0 or cw<=0 or ch<=0 or x+cw>width or y+ch>height:x=y=0;cw=width;ch=height
    orientation=int(meta.get('Orientation',{0:1,1:2,2:4,3:3,4:5,5:8,6:6,7:7}.get(decoded_metadata.get('orientation_flip',0),1)))
    return {'Make':meta.get('Make',''),'Model':meta.get('Model','Generic RAW Camera'),
        'UniqueCameraModel':meta.get('UniqueCameraModel',meta.get('Model','Generic RAW Camera')),
        'Orientation':orientation,'safe_render_tags':[],
        'active_area':[top,left,top+height,left+width],'crop_origin':[x,y],'crop_size':[cw,ch],
        'raw_ifd':'LibRaw sensor buffer','source_kind':meta.get('FileType','RAW'),'camera_identity':identity,**lens_fields}

def rational_pair(seq):
    from fractions import Fraction
    return tuple(x for v in seq for x in (lambda f:(f.numerator,f.denominator))(Fraction(v).limit_denominator(1000000)))

def make_preview(pixels,black,white,structure,gamma,max_width=640):
    """Area-average linear DN before display transfer; never subsample phases.

    Keep the returned RGB in sensor orientation: callers still apply
    orient_preview, or retain the original TIFF Orientation tag. max_width
    limits the actual displayed crop width, including transposed orientations.
    Prefix integrals are evaluated in bounded row strips, avoiding a full-size
    floating-point RAW copy even for large sensors and fractional resize ratios.
    """
    h,w=pixels.shape
    if isinstance(max_width,(bool,np.bool_)) or not isinstance(max_width,(int,np.integer)) or max_width<1:
        raise ValueError('预览宽度必须为正整数')
    if not np.isfinite([black,white,gamma]).all() or white<=black or gamma<=0:
        raise ValueError('预览黑白电平或伽马无效')
    left=int(structure['active_area'][1]+structure['crop_origin'][0]);top=int(structure['active_area'][0]+structure['crop_origin'][1])
    cw,ch=map(int,structure['crop_size'])
    if min(left,top)<0 or min(cw,ch)<1 or left+cw>w or top+ch>h:
        raise ValueError('预览裁剪范围无效')
    crop=pixels[top:top+ch,left:left+cw]
    transposed=int(structure.get('Orientation',1)) in (5,6,7,8)
    display_width=ch if transposed else cw
    if display_width<=max_width:
        # Preserve the native-resolution transfer exactly; details/RAW pixels
        # are not filtered or rewritten by the overview downsampling change.
        linear=crop.astype(np.float32)
    else:
        if transposed:
            oh=int(max_width);ow=max(1,int(round(cw*oh/ch)))
        else:
            ow=int(max_width);oh=max(1,int(round(ch*ow/cw)))
        # Pixel cells occupy [i,i+1). Exact overlap weights preserve the crop's
        # area mean at noninteger ratios and never discard a partial edge cell.
        xn=np.arange(ow+1,dtype=np.int64)*cw
        xi=xn//ow;xf=(xn%ow)/ow
        yn=np.arange(oh+1,dtype=np.int64)*ch
        yi=yn//oh;yf=(yn%oh)/oh
        integrals=np.empty((oh+1,ow),dtype=np.float64)
        carry=np.zeros(ow,dtype=np.float64)
        for start in range(0,ch,128):
            end=min(start+128,ch);block=crop[start:end]
            if ow==cw:
                horizontal=block.astype(np.float64)
            else:
                prefix=np.empty((end-start,cw+1),dtype=np.float64);prefix[:,0]=0
                np.cumsum(block,axis=1,dtype=np.float64,out=prefix[:,1:])
                edge=prefix[:,xi]+block[:,np.minimum(xi,cw-1)]*xf
                horizontal=np.diff(edge,axis=1)/(cw/ow)
            prefix_y=np.empty((end-start+1,ow),dtype=np.float64);prefix_y[0]=carry
            np.cumsum(horizontal,axis=0,dtype=np.float64,out=prefix_y[1:]);prefix_y[1:]+=carry
            # An edge exactly at a strip boundary needs no following sample.
            chosen=np.flatnonzero((yi>=start)&((yi<end)|((yi==end)&(yf==0))))
            local=yi[chosen]-start
            integrals[chosen]=prefix_y[local]+horizontal[np.minimum(local,end-start-1)]*yf[chosen,None]
            carry=prefix_y[-1].copy()
        linear=(np.diff(integrals,axis=0)/(ch/oh)).astype(np.float32)
    preview=np.clip((linear-black)/(white-black),0,1)
    return np.repeat((preview**(1/gamma)*255).astype(np.uint8)[:,:,None],3,axis=2)

def make_detail_preview(pixels,black,white,structure,gamma):
    """8-bit display plane at native crop resolution; 64K LUT bounds memory."""
    left=int(structure['active_area'][1]+structure['crop_origin'][0]);top=int(structure['active_area'][0]+structure['crop_origin'][1])
    cw,ch=map(int,structure['crop_size'])
    values=np.arange(65536,dtype=np.float32)
    lut=(np.clip((values-black)/(white-black),0,1)**(1/gamma)*255).astype(np.uint8)
    return lut[pixels[top:top+ch,left:left+cw]]

def make_histogram(pixels,black,white,structure,gamma,checkpoint=None):
    """Full default-crop counts; integer DN bins bound temporary memory."""
    if not 0<=black<white<=65535:raise ValueError('直方图黑白电平无效')
    left=int(structure['active_area'][1]+structure['crop_origin'][0]);top=int(structure['active_area'][0]+structure['crop_origin'][1])
    cw,ch=map(int,structure['crop_size']);crop=pixels[top:top+ch,left:left+cw]
    dn_counts=np.zeros(65536,dtype=np.int64)
    for y in range(0,crop.shape[0],256):
        if checkpoint:checkpoint()
        dn_counts+=np.bincount(crop[y:y+256].ravel(),minlength=65536)
    values=np.arange(65536,dtype=np.float32)
    normalized=np.clip((values-black)/(white-black),0,1)
    linear_index=np.minimum((normalized*256).astype(np.int32),255)
    display_index=(normalized**(1/gamma)*255).astype(np.uint8)
    linear=np.zeros(256,dtype=np.int64);display=np.zeros(256,dtype=np.int64)
    np.add.at(linear,linear_index,dn_counts);np.add.at(display,display_index,dn_counts)
    return dict(linear_bins=linear.tolist(),display_bins=display.tolist(),sample_count=int(crop.size),
        black_clipped=int(dn_counts[:int(black)+1].sum()),white_clipped=int(dn_counts[int(white):].sum()),
        black_level=int(black),white_level=int(white),gamma=float(gamma))

def orient_preview(image,orientation):
    if orientation==2:return image[:,::-1]
    if orientation==3:return image[::-1,::-1]
    if orientation==4:return image[::-1]
    if orientation==5:return image.swapaxes(0,1)
    if orientation==6:return np.rot90(image,-1)
    if orientation==7:return image.swapaxes(0,1)[::-1,::-1]
    if orientation==8:return np.rot90(image,1)
    return image

def write_dng(source,output,pixels,black,white,structure,recipe):
    h,w=pixels.shape
    # Preview is sampled for display; RAW is never gamma encoded.
    preview=make_preview(pixels,black,white,structure,recipe.preview_gamma)
    digest=hashlib.md5(pixels.astype('<u2',copy=False).tobytes()).digest()
    output_model=output_camera_model(structure.get('Model',''))
    output_unique=output_camera_model(structure.get('UniqueCameraModel',structure.get('Model','')))
    common=[(271,'s',0,structure.get('Make',''),False),(272,'s',0,output_model,False),
       (274,'H',1,int(structure.get('Orientation',1)),False),(50706,'B',4,(1,4,0,0),False),
       (50707,'B',4,(1,3,0,0),False),(50708,'s',0,output_unique,False),
       (50827,'B',len(Path(source).name.encode('utf-8'))+1,Path(source).name.encode('utf-8')+b'\0',False),(50972,'B',16,digest,False)]
    common += [tag for tag in structure['safe_render_tags'] if not(recipe.match_preview and tag[0]==50730)]
    icc=preview_icc(rgb=True)
    common += [(34675,7,len(icc),icc,False)]
    xmp=dng_xmp(recipe.preview_gamma,recipe.match_preview,structure)
    common += [(700,'B',len(xmp),xmp,False)]
    if recipe.match_preview:
        common += [(50730,'2i',1,(0,1),False)]
    rawtags=[(254,'I',1,0,False),(50713,'H',2,(1,1),False),(50714,'2I',1,(int(black),1),False),
       (50717,'I',1,int(white),False),(50719,'2I',2,rational_pair(structure['crop_origin']),False),
       (50720,'2I',2,rational_pair(structure['crop_size']),False),(50829,'I',4,tuple(structure['active_area']),False)]
    with tifffile.TiffWriter(output,byteorder='<') as t:
        t.write(preview,photometric='rgb',subifds=1,subfiletype=1,metadata=None,software='toMONO 1.0 Beta 8.1',extratags=common)
        t.write(pixels,photometric=34892,metadata=None,software=False,rowsperstrip=h,extratags=rawtags)
    with Path(output).open('r+b') as stream:
        with tifffile.TiffFile(stream) as t:
            tag=t.pages[0].tags[330];tag.overwrite(tag.value,dtype=4)
    copy=[];warnings=[]
    omitted=[]
    if recipe.preserve_capture:
        copy+=CAPTURE_TAGS
        # Manual lenses sometimes record undefined zero-valued aperture/focal
        # fields. Do not copy those invalid values into a newly validated DNG.
        lens=structure.get('lens_metadata',{})
        for tag,key in (('ExifIFD:FNumber','aperture'),('ExifIFD:FocalLength','focal')):
            value=lens.get(key)
            if value is not None:
                try:valid=np.isfinite(float(value)) and float(value)>0
                except (TypeError,ValueError):valid=False
                if not valid:copy.remove(tag);omitted.append(tag)
    if recipe.preserve_description:copy+=DESCRIPTION_TAGS
    if copy:
        result=subprocess.run([exiftool(),'-config','','-overwrite_original','-TagsFromFile',str(source),*['-'+x for x in copy],str(output)],capture_output=True,text=True)
        if result.returncode:
            warnings.append('RAW已重建，但部分拍摄信息未复制：'+result.stderr.strip())
            event('metadata_copy_warning','warning',source=str(source),message=result.stderr.strip())
    correction=structure.get('lens_correction')
    if correction or structure.get('lens_history'):
        description=structure.get('source_description','') if recipe.preserve_description else ''
        if correction:
            marker='[toMONO lens-corrected v1] '+json.dumps({k:correction[k] for k in ('maker','model','focal','aperture','distortion','vignetting','database_sha256')},ensure_ascii=False,separators=(',',':'))
            description=(description+'\n'+marker).strip()
        elif '[toMONO lens-corrected v1]' not in description:
            description=structure['lens_history'][structure['lens_history'].find('[toMONO lens-corrected v1]'):]
        command=[exiftool(),'-config','','-overwrite_original','-ImageDescription='+description]
        if correction and recipe.preserve_capture:
            command+=['-ExifIFD:LensMake='+correction['maker'],'-ExifIFD:LensModel='+correction['model'],'-ExifIFD:FocalLength='+str(correction['focal']),'-ExifIFD:FNumber='+str(correction['aperture'])]
        subprocess.run([*command,str(output)],capture_output=True,text=True,check=True)
        if correction:warnings+=correction.get('warnings',[])
    readback=read_linear_output(output)
    if not np.array_equal(readback,pixels):raise RuntimeError('输出像素回读校验失败，未保存结果')
    check=subprocess.run([exiftool(),'-config','','-j','-validate','-warning','-error','-a',str(output)],capture_output=True,text=True,check=True)
    validation=json.loads(check.stdout)[0]
    if 'Error' in validation or validation.get('Validate')!='OK':raise RuntimeError('DNG结构检查未通过：'+json.dumps(validation,ensure_ascii=False))
    return {'raw_md5':digest.hex(),'metadata_validation':validation,'copied_metadata_groups':copy,'omitted_undefined_capture_fields':omitted,'warnings':warnings,
        'render_appearance':{'mode':APPEARANCE_ID if recipe.match_preview else 'decoder-default',
            'preview_gamma':recipe.preview_gamma,'calibrated_with':'Camera Raw 18.7',
            'raw_samples_modified':False,'scope':'Initial Adobe development settings; resetting settings or another renderer may change appearance'},
        'source_camera':{key:structure.get(key,'') for key in ('Make','Model','UniqueCameraModel')},
        'output_camera_model':output_model,'output_unique_camera_model':output_unique,
        'metadata_policy':'Preserve capture/descriptive tags; omit MakerNotes, prior raw digests and source development XMP. Optional toMONO reference appearance is newly authored XMP; linear RAW samples remain unchanged.'}
