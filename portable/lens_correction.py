"""Offline Lensfun profiles and explicit, single-pass linear monochrome correction."""
import ctypes,hashlib,json,math
from functools import lru_cache
from pathlib import Path
import numpy as np
import lensfunpy

DBDIR=Path(lensfunpy.__file__).parent/'db_files'

@lru_cache(maxsize=1)
def database():return lensfunpy.Database(load_common=False,load_bundled=True)

def profile_key(lens):
    return hashlib.sha256(json.dumps([lens.maker,lens.model,sorted(lens.mounts),round(lens.crop_factor,6)],ensure_ascii=False,separators=(',',':')).encode()).hexdigest()

@lru_cache(maxsize=1)
def catalog():
    digest=hashlib.sha256()
    for path in sorted(DBDIR.glob('*.xml')):digest.update(path.name.encode());digest.update(path.read_bytes())
    rows=[]
    for lens in database().lenses:
        rows.append(dict(id=profile_key(lens),maker=lens.maker,model=lens.model,mounts=lens.mounts,crop_factor=lens.crop_factor,
            min_focal=lens.min_focal,max_focal=lens.max_focal,min_aperture=lens.min_aperture,
            distortion=bool(lens.calib_distortion),tca=bool(lens.calib_tca),vignetting=bool(lens.calib_vignetting)))
    return dict(lensfunpy_version=lensfunpy.__version__,lensfun_version='0.3.4',database_sha256=digest.hexdigest(),profiles=rows)

def validate_config(config):
    if config is None:return
    allowed={'profile_id','focal_override','aperture_override','crop_override','distance','distortion','vignetting'}
    if not isinstance(config,dict) or set(config)-allowed or not {'profile_id','distance','distortion','vignetting'}<=set(config):raise ValueError('镜头校正配置字段不完整或存在未知字段')
    if not isinstance(config['profile_id'],str) or len(config['profile_id'])!=64:raise ValueError('镜头配置标识无效')
    for name in ('distortion','vignetting'):
        if type(config[name]) is not bool:raise ValueError('镜头校正开关必须为布尔值')
    for name,lo,hi in (('focal_override',1,5000),('aperture_override',.5,128),('crop_override',.1,20),('distance',.01,1000000)):
        value=config.get(name)
        if value is None and name!='distance':continue
        if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise ValueError('镜头参数无效：'+name)

class CLens(ctypes.Structure):
    _fields_=[('maker',ctypes.c_char_p),('model',ctypes.c_char_p),('min_focal',ctypes.c_float),('max_focal',ctypes.c_float),
      ('min_aperture',ctypes.c_float),('max_aperture',ctypes.c_float),('mounts',ctypes.POINTER(ctypes.c_char_p)),
      ('center_x',ctypes.c_float),('center_y',ctypes.c_float),('crop_factor',ctypes.c_float),('aspect',ctypes.c_float),('type',ctypes.c_int)]

class Modifier:
    """Use the public 0.3.4 C ABI for bounded-memory strip operations."""
    def __init__(self,lens,crop,width,height,focal,aperture,distance,flags):
        self.lib=lib=ctypes.CDLL(str(Path(lensfunpy.__file__).parent/'.dylibs/liblensfun.0.3.4.dylib'))
        vp=ctypes.c_void_p;fp=ctypes.POINTER(ctypes.c_float)
        signatures={
          'lf_db_new':([],vp),'lf_db_load_directory':([vp,ctypes.c_char_p],ctypes.c_int),
          'lf_db_destroy':([vp],None),'lf_free':([vp],None),
          'lf_db_find_lenses_hd':([vp,vp,ctypes.c_char_p,ctypes.c_char_p,ctypes.c_int],ctypes.POINTER(vp)),
          'lf_modifier_new':([vp,ctypes.c_float,ctypes.c_int,ctypes.c_int],vp),
          'lf_modifier_destroy':([vp],None),
          'lf_modifier_initialize':([vp,vp,ctypes.c_int,ctypes.c_float,ctypes.c_float,ctypes.c_float,ctypes.c_float,ctypes.c_int,ctypes.c_int,ctypes.c_int],ctypes.c_int),
          'lf_modifier_apply_color_modification':([vp,vp,ctypes.c_float,ctypes.c_float,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int],ctypes.c_int),
          'lf_modifier_apply_geometry_distortion':([vp,ctypes.c_float,ctypes.c_float,ctypes.c_int,ctypes.c_int,fp],ctypes.c_int)}
        for name,(args,result) in signatures.items():fn=getattr(lib,name);fn.argtypes=args;fn.restype=result
        self.db=lib.lf_db_new();self.handle=None
        try:
            if not lib.lf_db_load_directory(self.db,str(DBDIR).encode()):raise ValueError('无法载入内置镜头数据库')
            found=lib.lf_db_find_lenses_hd(self.db,None,lens.maker.encode(),lens.model.encode(),0)
            pointer=None
            if found:
                try:
                    for i in range(10000):
                        if not found[i]:break
                        value=ctypes.cast(found[i],ctypes.POINTER(CLens)).contents
                        if value.maker.decode()==lens.maker and value.model.decode()==lens.model and abs(value.crop_factor-lens.crop_factor)<1e-5:
                            mounts=[];j=0
                            while value.mounts and value.mounts[j]:mounts.append(value.mounts[j].decode());j+=1
                            if sorted(mounts)==sorted(lens.mounts):pointer=found[i];break
                finally:lib.lf_free(found)
            if pointer is None:raise ValueError('镜头配置存在歧义或未找到')
            self.handle=lib.lf_modifier_new(pointer,crop,width,height)
            if not self.handle:raise MemoryError('镜头校正器初始化失败')
            self.enabled=lib.lf_modifier_initialize(self.handle,pointer,3,focal,aperture,distance,0 if flags&8 else 1,lens.type.value,flags,0)
        except Exception:self.close();raise
    def close(self):
        if self.handle:self.lib.lf_modifier_destroy(self.handle);self.handle=None
        if self.db:self.lib.lf_db_destroy(self.db);self.db=None
    def __enter__(self):return self
    def __exit__(self,*_):self.close()
    def vignette_strip(self,view,y):
        return bool(self.lib.lf_modifier_apply_color_modification(self.handle,view.ctypes.data,0,y,view.shape[1],view.shape[0],5,view.strides[0]))
    def coords(self,width,rows,y):
        result=np.empty((rows,width,2),np.float32)
        if not self.lib.lf_modifier_apply_geometry_distortion(self.handle,0,y,width,rows,result.ctypes.data_as(ctypes.POINTER(ctypes.c_float))):raise ValueError('无法生成镜头畸变坐标')
        return result


def apply_lens(pixels,metadata,parameters,structure,config,checkpoint=None):
    if config is None:return pixels,metadata,parameters,structure
    validate_config(config)
    if structure.get('lens_correction_already_applied'):raise ValueError('此文件已经应用toMONO镜头校正，请关闭额外镜头校正，避免重复处理')
    lens=next((l for l in database().lenses if profile_key(l)==config['profile_id']),None)
    if lens is None:raise ValueError('内置库中找不到已保存的镜头配置，请重新选择')
    capture=structure.get('lens_metadata',{})
    focal=config.get('focal_override') or capture.get('focal')
    aperture=config.get('aperture_override') or capture.get('aperture')
    crop=config.get('crop_override') or capture.get('crop_factor')
    if not focal or not crop:raise ValueError('缺少镜头焦距或画幅系数，请在镜头设置中手动填写')
    if not lens.min_focal-.01<=focal<=lens.max_focal+.01:raise ValueError('拍摄焦距超出所选镜头的范围，请核对镜头和焦距')
    if config['vignetting'] and not aperture:raise ValueError('暗角校正需要光圈，请手动填写拍摄光圈')
    aperture=aperture or lens.min_aperture or 5.6
    flags=(8|32 if config['distortion'] else 0)|(2 if config['vignetting'] else 0)
    if not flags:return pixels,metadata,parameters,structure
    x=int(structure['active_area'][1]+structure['crop_origin'][0]);y=int(structure['active_area'][0]+structure['crop_origin'][1]);w,h=map(int,structure['crop_size'])
    black=metadata['black_level_by_libraw_channel'][0]
    work=pixels[y:y+h,x:x+w].astype(np.float32)-black
    warnings=[]
    with Modifier(lens,crop,w,h,float(focal),float(aperture),float(config['distance']),flags) as modifier:
        if config['distortion'] and not modifier.enabled&8:raise ValueError('该镜头在此焦距没有可用的畸变标定数据')
        if config['vignetting'] and not modifier.enabled&2:raise ValueError('该镜头在当前焦距/光圈/距离没有可用的暗角标定数据')
        if modifier.enabled&2:
            for start in range(0,h,256):
                if checkpoint:checkpoint()
                if not modifier.vignette_strip(work[start:start+256],start):raise ValueError('镜头暗角校正未执行')
        if not np.all(np.isfinite(work)):raise ValueError('镜头标定产生无效增益，请核对镜头和拍摄参数')
        high=int(np.count_nonzero(work>65535-black));low=int(np.count_nonzero(work < -black))
        if high or low:warnings.append(f'镜头校正后有{high}个高端和{low}个低端数值超出16位容器，已限制到可存储范围')
        if modifier.enabled&8:
            output=np.empty((h,w),np.uint16)
            core=ctypes.CDLL(str(Path(__file__).parent/'build/native-macos/libtomono_core.dylib'));fp=ctypes.POINTER(ctypes.c_float);up=ctypes.POINTER(ctypes.c_uint16)
            fn=core.tomono_remap_gray_strip;fn.argtypes=[fp,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,fp,ctypes.c_size_t,up,ctypes.c_size_t,ctypes.c_int,ctypes.c_float];fn.restype=ctypes.c_int
            for start in range(0,h,256):
                if checkpoint:checkpoint()
                view=output[start:start+256];coords=modifier.coords(w,len(view),start)
                if fn(work.ctypes.data_as(fp),work.size,w,h,coords.ctypes.data_as(fp),coords.size,view.ctypes.data_as(up),view.size,len(view),black):raise RuntimeError('镜头重采样失败')
        else:output=np.clip(np.rint(work+black),0,65535).astype(np.uint16)
    report=dict(applied=True,mode='baked_linear_pixels',profile_id=config['profile_id'],maker=lens.maker,model=lens.model,
        database_sha256=catalog()['database_sha256'],lensfun_version='0.3.4',focal=float(focal),aperture=float(aperture),crop_factor=float(crop),distance=config['distance'],
        distortion=bool(modifier.enabled&8),vignetting=bool(modifier.enabled&2),tca_calibration_available=bool(lens.calib_tca),tca_applied=False,
        tca_reason='Single monochrome response plane; no separate colour planes to register after reconstruction',
        source_crop=[x,y,w,h],warnings=warnings,resampling='single bounded bicubic geometry pass; linear sensor units')
    parameters=dict(parameters,lens_correction=report)
    metadata=dict(metadata,shape=[h,w])
    structure=dict(structure,active_area=[0,0,h,w],crop_origin=[0,0],crop_size=[w,h],lens_correction=report)
    return output,metadata,parameters,structure

if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--catalog',type=Path,required=True);args=parser.parse_args()
    args.catalog.write_text(json.dumps(catalog(),ensure_ascii=False,indent=2)+'\n')
    print('Lensfun profiles:',len(catalog()['profiles']))
