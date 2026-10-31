"""Recovered 3-channel DNG white-point path; identity calibrations only."""
import json,math,struct
from pathlib import Path
import numpy as np
import tifffile
from dng_layout import select_raw_ifd
DATA=json.loads((Path(__file__).parent/'robertson_table.json').read_text())
D50=(0.3457,0.3585)
def f32(x):return struct.unpack('<f',struct.pack('<f',x))[0]
def sdk_round(x,scale):
    v=x*scale
    return math.trunc(v+(0.5 if v>0 else -0.5))*(1.0/scale)
def temperature(xy):
    x,y=xy;den=1.5-x+6.0*y
    if den==0:raise ValueError('白点坐标无效')
    u=2.0*x/den;v=3.0*y/den;last=0.0;rows=DATA['rows']
    for i in range(1,31):
        r,ui,vi,slope=rows[i];norm=math.sqrt(1.0+slope*slope)
        dt=(v-vi)*(1.0/norm)-(u-ui)*(slope/norm)
        if dt<=0.0 or i==30:
            dt=min(0.0,dt);weight=0.0 if i==1 else -dt/(last-dt)
            reciprocal=rows[i-1][0]*weight+r*(1.0-weight)
            if reciprocal<=0:raise ValueError('白点色温超出当前支持范围')
            return 1000000.0/reciprocal
        last=dt
    raise ValueError('无法计算白点色温')
def xyz_from_xy(xy):
    x,y=[min(0.999999,max(0.000001,float(v))) for v in xy]
    if x+y>0.999999:
        k=0.999999/(x+y);x*=k;y*=k
    return np.array([x/y,1.0,((1.0-x)-y)/y])
def dot(m,v):
    return np.array([(float(r[0])*v[0]+float(r[1])*v[1])+float(r[2])*v[2] for r in m])
def normalize_matrix(matrix):
    m=np.asarray(matrix,dtype=np.float64).reshape(3,3).copy()
    maximum=max(dot(m,xyz_from_xy(D50)))
    if maximum>0 and not 0.99<=maximum<=1.01:m*=1.0/maximum
    return np.array([sdk_round(float(x),10000.0) for x in m.flat]).reshape(3,3)
def camera_white(neutral,matrices,temperatures,white_xy=None):
    if len(matrices) not in (1,2) or len(temperatures)!=len(matrices):raise ValueError('需要一套或两套颜色矩阵和校准光源')
    ms=[normalize_matrix(m) for m in matrices];ts=list(temperatures)
    if len(ms)==1:ms=ms*2;ts=[5000.0,5000.0]
    if ts[0]>ts[1]:ts.reverse();ms.reverse()
    def matrix(xy):
        t=temperature(xy)
        if t<=ts[0]:return ms[0]
        if t>=ts[1]:return ms[1]
        weight=(1.0/t-1.0/ts[1])/(1.0/ts[0]-1.0/ts[1])
        return ms[0]*weight+ms[1]*(1.0-weight)
    rounded=None;iterations=0
    if white_xy is not None:
        if len(white_xy)!=2 or not np.isfinite(white_xy).all() or min(white_xy)<=0 or sum(white_xy)>=1:
            raise ValueError('AsShotWhiteXY坐标无效')
        xy=tuple(white_xy)
    else:
        v=np.asarray(neutral,dtype=np.float64)
        if v.shape!=(3,) or not np.isfinite(v).all() or min(v)<=0:raise ValueError('AsShotNeutral必须是三个有限正数')
        scale=1.0/max(v);rounded=np.array([sdk_round(float(c*scale),1000000.0) for c in v]);xy=D50
        for i in range(30):
            xyz=np.linalg.solve(matrix(xy),rounded);total=(xyz[0]+xyz[1])+xyz[2]
            new=(float(xyz[0]/total),float(xyz[1]/total)) if total>0 else D50;iterations=i+1
            if abs(new[0]-xy[0])+abs(new[1]-xy[1])<1e-7:xy=new;break
            if i==29:xy=((xy[0]+new[0])*0.5,(xy[1]+new[1])*0.5)
            else:xy=new
    white=dot(matrix(xy),xyz_from_xy(xy));scale=1.0/max(white)
    white=[f32(max(0.001,min(1.0,float(c*scale)))) for c in white]
    return {'camera_white':white,'white_xy':list(xy),'rounded_camera_neutral':None if rounded is None else rounded.tolist(),'iterations':iterations}
def values(page,name,default=None):
    if name not in page.tags:return default
    tag=page.tags[name];v=tag.value
    if int(tag.dtype) in (5,10):
        seq=list(v) if isinstance(v,tuple) else [v]
        if len(seq)%2:raise ValueError('无效的DNG有理数标签：'+name)
        return [seq[i]/seq[i+1] for i in range(0,len(seq),2)]
    if isinstance(v,(tuple,list,bytes)):return list(v)
    return [v]
def parameters_from_dng(path):
    with tifffile.TiffFile(path) as t:
        p=select_raw_ifd(t)
        if 'LinearizationTable' in p.tags:raise ValueError('尚未接入LinearizationTable处理')
        pattern=values(p,'CFAPattern')
        if pattern not in ([0,1,1,2],[2,1,1,0],[1,0,2,1],[1,2,0,1]):raise ValueError('当前重建需要2×2 RGB Bayer采样排列')
        model=p.tags['UniqueCameraModel'].value if 'UniqueCameraModel' in p.tags else (p.tags['Model'].value if 'Model' in p.tags else 'Generic RAW Camera')
        if model!='LEICA M11':
            neutral=values(p,'AsShotNeutral',[1,1,1])
            if len(neutral)!=3 or min(neutral)<=0 or not np.isfinite(neutral).all():raise ValueError('原图白平衡中性值无效')
            white=[float(x/max(neutral)) for x in neutral]
            return dict(model=model,camera_white=white,green_compensation=0.0,focus_red=False,focus_blue=False,
                pattern=pattern,row_offset=0,col_offset=0,raw_ifd=p.ifd_path,preset='generic_bayer',
                provenance='DNG neutral metadata; generic Bayer reconstruction; no camera-specific green preset',
                scope='Generic Bayer path; no Windows-output equivalence claim')
        for name in ('CameraCalibration1','CameraCalibration2'):
            v=values(p,name)
            if v is not None and (len(v)!=9 or not np.array_equal(np.array(v).reshape(3,3),np.eye(3))):raise ValueError('尚未实现非单位相机校准矩阵：'+name)
        if values(p,'AnalogBalance',[1,1,1])!=[1,1,1]:raise ValueError('尚未实现非单位AnalogBalance')
        matrices=[];temps=[]
        for k in (1,2):
            m=values(p,f'ColorMatrix{k}')
            if m is None:continue
            if len(m)!=9 or not np.isfinite(m).all():raise ValueError('仅支持有限数值的3×3颜色矩阵')
            illuminant=values(p,f'CalibrationIlluminant{k}',[0])[0];temp=DATA['illuminant_temperatures'].get(str(illuminant),0)
            if temp<=0:raise ValueError('尚未实现此校准光源：'+str(illuminant))
            matrices.append(m);temps.append(temp)
        if not matrices:raise ValueError('DNG缺少受支持的ColorMatrix')
        result=camera_white(values(p,'AsShotNeutral'),matrices,temps,values(p,'AsShotWhiteXY'))
        result.update(model=model,green_compensation=f32(1.231),focus_red=True,focus_blue=False,
            pattern=pattern,row_offset=0,col_offset=0,raw_ifd=p.ifd_path,preset='reference_bicubic',
            provenance='DNG metadata + recovered SDK profile/neutral path; legacy default parameters; no capture calibration JSON',
            scope='3-channel identity-calibration DNG branch; Windows parity only validated on captured M11')
        return result
