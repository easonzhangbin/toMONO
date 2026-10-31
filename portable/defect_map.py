"""Explicit sensor-coordinate defect maps. Never infer defect locations from texture."""
import hashlib,json
import numpy as np


def validate_profile(profile):
    if profile is None:return None
    if not isinstance(profile,dict) or set(profile)!={'version','make','model','sensor_size','pixels'}:raise ValueError('缺陷图需要 version、make、model、sensor_size、pixels 字段')
    if type(profile['version']) is not int or profile['version']!=1:raise ValueError('缺陷图版本不受支持')
    if any(not isinstance(profile[k],str) or not profile[k].strip() for k in ('make','model')):raise ValueError('缺陷图必须注明相机厂商和型号')
    size=profile['sensor_size']
    if not isinstance(size,list) or len(size)!=2 or any(type(v) is not int or not 8<=v<=100000 for v in size):raise ValueError('缺陷图 sensor_size 应为完整传感器的 [宽,高]')
    points=profile['pixels']
    if not isinstance(points,list) or not 1<=len(points)<=1000000:raise ValueError('缺陷图需有1至1000000个像素坐标')
    seen=set()
    for point in points:
        if not isinstance(point,list) or len(point)!=2 or any(type(v) is not int for v in point):raise ValueError('缺陷图坐标必须为整数 [x,y]')
        x,y=point
        if not(0<=x<size[0] and 0<=y<size[1]) or (x,y) in seen:raise ValueError('缺陷图坐标越界或重复')
        seen.add((x,y))
    return profile


def repair_sensor_map(mosaic,pattern,profile,structure,source_shape,active,target=1):
    if target not in (0,1,2):raise ValueError('缺陷图目标通道无效')
    profile=validate_profile(profile)
    if profile is None:return {'mode':'off','repaired':0}
    for field in ('make','model'):
        if profile[field].strip().casefold()!=str(structure.get(field.title(),'')).strip().casefold():raise ValueError('缺陷图相机'+field+'与当前文件不匹配，未执行修复')
    if profile['sensor_size']!=list(reversed(source_shape)):raise ValueError('缺陷图完整传感器尺寸不匹配，未执行修复')
    top,left,_,_=active;h,w=mosaic.shape;pr,pc=len(pattern),len(pattern[0])
    points={(y-top,x-left) for x,y in profile['pixels'] if top<=y<top+h and left<=x<left+w}
    # Read the unchanged input for every estimate; neighboring mapped pixels are excluded.
    estimates=[];ignored=0
    for y,x in sorted(points):
        if pattern[y%pr][x%pc]!=target:ignored+=1;continue
        candidates=[]
        for radius in range(1,9):
            for dy,dx in ((-radius*pr,0),(radius*pr,0),(0,-radius*pc),(0,radius*pc)):
                yy,xx=y+dy,x+dx
                if 0<=yy<h and 0<=xx<w and (yy,xx) not in points:
                    candidates.append((float(mosaic[yy,xx]),1.0/(dx*dx+dy*dy)))
            if len(candidates)>=4:break
        if len(candidates)<2:raise ValueError('缺陷图过密，无法用同类'+('红色','绿色','蓝色')[target]+'采样可靠修复')
        values=np.array([v for v,_ in candidates]);weights=np.array([v for _,v in candidates])
        # Weighted mean is bounded by the measured neighbors, without invented detail.
        estimates.append((y,x,int(np.rint(np.dot(values,weights)/weights.sum()))))
    for y,x,value in estimates:mosaic[y,x]=value
    digest=hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return {'mode':'explicit_sensor_map','profile_sha256':digest,'mapped_pixels':len(profile['pixels']),
        'repaired':len(estimates),('ignored_non_green'if target==1 else'ignored_non_target'):ignored,'outside_active':len(profile['pixels'])-len(points),
        'coordinate_system':'unrotated full sensor, zero-based [x,y]','positions_inferred':False}
