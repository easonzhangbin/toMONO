"""Versioned, source-independent conversion recipes."""
from dataclasses import dataclass,asdict
import json,math
from pathlib import Path

@dataclass(frozen=True)
class Recipe:
    version:int=2
    detail_mode:str='spectral'
    algorithm:str='Bicubic'
    green_mode:str='auto'
    compensation:float=1.231
    focus_red:bool=True
    focus_blue:bool=False
    preview_gamma:float=2.2
    match_preview:bool=True
    preserve_capture:bool=True
    preserve_description:bool=True
    defect_profile:dict|None=None
    camera_identity:dict|None=None
    lens_correction:dict|None=None
    response_mode:str='green'
    response_red:float=0.25
    response_green:float=0.5
    response_blue:float=0.25
    response_exposure:float=0.0
    narrow_interpolation:str='cubic'

    @classmethod
    def from_dict(cls,data):
        if not isinstance(data,dict):raise ValueError('设置预设必须为JSON对象')
        if set(data)-set(cls.__dataclass_fields__):raise ValueError('设置预设包含未知字段：'+', '.join(sorted(set(data)-set(cls.__dataclass_fields__))))
        data=dict(data)
        version=data.get('version',1)
        if type(version) is not int or version not in (1,2):raise ValueError('不支持此设置预设版本')
        if 'detail_mode' not in data:data['detail_mode']='legacy' if version==1 else 'spectral'
        data['version']=2
        r=cls(**data)
        if r.detail_mode not in ('spectral','spectral_guard','directional','legacy'):raise ValueError('细节模式无效')
        if r.algorithm not in ('Bicubic','EdgeAware','Auto'):raise ValueError('算法必须为Bicubic、EdgeAware或Auto')
        if r.response_mode not in ('green','mix','narrow_red','narrow_green','narrow_blue'):raise ValueError('单色响应模式无效')
        if r.narrow_interpolation not in ('cubic','linear'):raise ValueError('纯通道插值必须为cubic或linear')
        for key in ('response_red','response_green','response_blue'):
            v=getattr(r,key)
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1:raise ValueError(key+'必须在0至1之间')
        if r.response_mode=='mix' and r.response_red+r.response_green+r.response_blue<=0:raise ValueError('RGB响应至少需要一个大于零的比例')
        if type(r.response_exposure) not in (int,float) or not math.isfinite(r.response_exposure) or not -6<=r.response_exposure<=6:raise ValueError('响应总曝光必须在-6至6EV之间')
        from defect_map import validate_profile
        validate_profile(r.defect_profile)
        if r.lens_correction is not None:
            from lens_correction import validate_config
            validate_config(r.lens_correction)
        if r.camera_identity is not None:
            ci=r.camera_identity
            if not isinstance(ci,dict) or set(ci)-{'make','model','serial'} or any(not isinstance(ci.get(k),str) or not ci[k].strip() for k in ('make','model')) or (ci.get('serial') is not None and (not isinstance(ci['serial'],str) or not ci['serial'].strip())):raise ValueError('设置预设的相机来源信息无效')
        if r.green_mode not in ('auto','manual','off'):raise ValueError('绿色校正模式必须为auto、manual或off')
        for k in ('focus_red','focus_blue','preserve_capture','preserve_description','match_preview'):
            if type(getattr(r,k)) is not bool:raise ValueError(k+'必须为布尔值')
        for k,lo,hi in [('compensation',0.0,1.255),('preview_gamma',1.0,3.0)]:
            v=getattr(r,k)
            if type(v) not in (float,int) or not math.isfinite(v) or not lo<=v<=hi:raise ValueError(k+f'必须在{lo}至{hi}之间')
        return r

    @classmethod
    def load(cls,path):return cls.from_dict(json.loads(Path(path).read_text(encoding='utf-8')))
    def to_dict(self):return asdict(self)
    def save(self,path):
        with Path(path).open('x',encoding='utf-8') as stream:json.dump(self.to_dict(),stream,ensure_ascii=False,indent=2)
