import copy
import ctypes
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock,patch

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conversion_service import compute_monochrome
from pure_narrowband import channel_strips,native_core
from raw_input import SensorFrame
from recipe import Recipe

PATTERNS=[np.array(p,np.uint8)for p in (
    [[0,1],[1,2]],[[2,1],[1,0]],[[1,0],[2,1]],[[1,2],[0,1]])]


def reconstruct(samples,pattern,target,method,blacks=None,whites=None,rows=256):
    b=np.full((2,2),512.)if blacks is None else blacks
    w=np.full((2,2),16383.)if whites is None else whites
    return np.concatenate([value for _,value in channel_strips(samples,pattern,b,w,target,method,rows)],axis=0)


class PureNativeTests(unittest.TestCase):
    def test_all_phases_odd_even_dimensions_borders_and_other_colour_independence(self):
        rng=np.random.default_rng(4390)
        for shape in ((8,8),(35,37),(36,38)):
            yy,xx=np.indices(shape)
            for p in PATTERNS:
                codes=p[yy%2,xx%2];raw=rng.integers(512,15000,shape,dtype=np.uint16)
                for target in range(3):
                    mask=codes==target;other=raw.copy()
                    other[~mask]=np.where((yy+xx*2)[~mask]%3,65535,0).astype(np.uint16)
                    for method in ('cubic','linear'):
                        out=reconstruct(raw,p,target,method);changed=reconstruct(other,p,target,method)
                        np.testing.assert_array_equal(out,changed)
                        np.testing.assert_array_equal(out[mask],(raw[mask].astype(float)-512)/(16383-512))
                        self.assertGreaterEqual(float(out.min()),float((raw[mask].min()-512)/(16383-512))-1e-12)
                        self.assertLessEqual(float(out.max()),float((raw[mask].max()-512)/(16383-512))+1e-12)

    def test_constant_affine_signal_and_step_bounds(self):
        yy,xx=np.indices((64,66));p=PATTERNS[0]
        for target in range(3):
            for method in ('linear','cubic'):
                for raw in (np.full(yy.shape,7000,np.uint16),(2000+7*xx+11*yy).astype(np.uint16)):
                    out=reconstruct(raw,p,target,method)
                    np.testing.assert_allclose(out[6:-6,6:-6],(raw[6:-6,6:-6].astype(float)-512)/(16383-512),atol=1e-15)
                raw=np.where(xx<32,1000,14000).astype(np.uint16);out=reconstruct(raw,p,target,method)
                self.assertGreaterEqual(float(out.min()),(1000-512)/(16383-512)-1e-15)
                self.assertLessEqual(float(out.max()),(14000-512)/(16383-512)+1e-15)

    def test_target_phase_normalization_and_parallel_strip_equivalence(self):
        rng=np.random.default_rng(336);raw=rng.integers(100,18000,(520,530),dtype=np.uint16)
        b=np.array([[500,510],[520,530]],float);w=np.array([[15000,15500],[16000,16500]],float)
        previous=os.environ.get('TOMONO_THREADS')
        try:
            for target in range(3):
                for method in ('cubic','linear'):
                    os.environ['TOMONO_THREADS']='1';one=reconstruct(raw,PATTERNS[0],target,method,b,w,520)
                    os.environ['TOMONO_THREADS']='4';strips=reconstruct(raw,PATTERNS[0],target,method,b,w,256)
                    np.testing.assert_array_equal(one,strips)
                    for y,x in np.argwhere(PATTERNS[0]==target):
                        np.testing.assert_array_equal(one[y::2,x::2],(raw[y::2,x::2].astype(float)-b[y,x])/(w[y,x]-b[y,x]))
        finally:
            if previous is None:os.environ.pop('TOMONO_THREADS',None)
            else:os.environ['TOMONO_THREADS']=previous

    def test_abi_gate_and_invalid_layout(self):
        old=MagicMock();old.tomono_core_version.return_value=0x401
        with patch('pure_narrowband.ctypes.CDLL',return_value=old):
            with self.assertRaisesRegex(RuntimeError,'核心版本'):native_core()
        lib=native_core();self.assertGreaterEqual(lib.tomono_core_version(),0x402)
        with self.assertRaisesRegex(ValueError,'Bayer'):
            reconstruct(np.zeros((8,8),np.uint16),np.ones((2,2),np.uint8),1,'cubic')


class PurePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.source=Path(self.temp.name)/'sensor.raw';self.source.write_bytes(b'decoder-injected-test')

    def tearDown(self):self.temp.cleanup()

    def run_pipeline(self,raw,p,recipe,active=(1,1,65,67),blacks=(500,510,520,530),whites=(15000,15500,16000,16500),linear=False,layout='bayer',structure_error=None):
        channels=p.copy();greens=np.argwhere(p==1)
        if len(greens)>1:channels[tuple(greens[1])]=3
        h,w=raw.shape;t,l,b,r=active
        metadata=dict(sensor_layout=layout,linear_reconstruction=linear,
            cfa_codes_full_origin=p.tolist(),cfa_libraw_channels_full_origin=channels.tolist(),
            black_level_by_libraw_channel=list(blacks),white_level=16383,white_level_by_libraw_channel=list(whites))
        structure=dict(source_kind='RAW',Make='Test',Model='Camera',Orientation=6,
            camera_identity=dict(make='Test',model='Camera',serial='same'),
            active_area=list(active),crop_origin=[2,3],crop_size=[r-l-4,b-t-6],safe_render_tags=[],lens_metadata={})
        with patch('pure_narrowband.decode_sensor',return_value=SensorFrame(raw,metadata))as decode,\
             patch('pure_narrowband.source_structure',side_effect=structure_error,return_value=structure),\
             patch('conversion_service._compute_sensor_monochrome',side_effect=AssertionError('legacy path must not run')):
            result=compute_monochrome(self.source,recipe,diagnostics=True)
            self.assertEqual(decode.call_count,1)
            return result

    def test_active_offsets_target_mapping_ev_and_ignored_cross_colour_green_options(self):
        rng=np.random.default_rng(810);raw=rng.integers(1500,7000,(72,76),dtype=np.uint16);before=raw.copy()
        for p in PATTERNS:
            yy,xx=np.indices(raw.shape);codes=p[yy%2,xx%2]
            channels=p.copy();channels[tuple(np.argwhere(p==1)[1])]=3
            full_channels=channels[yy%2,xx%2]
            for target,mode in enumerate(('narrow_red','narrow_green','narrow_blue')):
                altered=raw.copy();altered[codes!=target]=65535
                for method in ('cubic','linear'):
                    for ev in (-1.,0.,1.):
                        recipe=Recipe(response_mode=mode,narrow_interpolation=method,response_exposure=ev,
                            green_mode='manual',focus_red=True,focus_blue=True,compensation=1.005)
                        out,m,params,structure,changed=self.run_pipeline(raw,p,recipe)
                        other,*_=self.run_pipeline(altered,p,recipe)
                        np.testing.assert_array_equal(out,other)
                        mask=codes[1:65,1:67]==target;local=raw[1:65,1:67].astype(float);c=full_channels[1:65,1:67]
                        black=np.array([500,510,520,530])[c];white=np.array([15000,15500,16000,16500])[c]
                        expected=np.clip(np.rint(m['black_level_by_libraw_channel'][0]+(local-black)/(white-black)*(m['white_level']-m['black_level_by_libraw_channel'][0])*2**ev),0,65535).astype(np.uint16)
                        np.testing.assert_array_equal(out[mask],expected[mask])
                        self.assertEqual(out.shape,(64,66));self.assertEqual(structure['active_area'],[0,0,64,66])
                        self.assertEqual(structure['Orientation'],6);self.assertEqual(structure['crop_origin'],[2,3])
                        self.assertEqual(structure['crop_size'],[62,58]);self.assertEqual(changed,0)
                        self.assertEqual(params['green_compensation'],0);self.assertTrue(params['response']['digital_channel_isolation'])
        np.testing.assert_array_equal(raw,before)

    def test_target_aware_defect_repair_uses_real_interpolation_buffer(self):
        p=PATTERNS[0];yy,xx=np.indices((64,66));codes=p[yy%2,xx%2]
        for target,mode,point in ((0,'narrow_red',(8,8)),(1,'narrow_green',(9,8)),(2,'narrow_blue',(9,9))):
            raw=np.choose(codes,[3000,6000,9000]).astype(np.uint16);y,x=point;raw[y,x]=0
            profile=dict(version=1,make='Test',model='Camera',sensor_size=[66,64],pixels=[[x,y]])
            recipe=Recipe(response_mode=mode,defect_profile=profile)
            out,m,params,s,_=self.run_pipeline(raw,p,recipe,active=(0,0,64,66),blacks=(512,)*4,whites=(16383,)*4)
            self.assertEqual(out[y,x],(3000,6000,9000)[target]);self.assertEqual(params['defect_repair']['repaired'],1)
            self.assertEqual(raw[y,x],0)

    def test_strict_fallback_monochrome_and_unverified_dng_are_rejected(self):
        raw=np.full((72,76),5000,np.uint16)
        for kwargs in (dict(linear=True),dict(layout='green_lattice')):
            with self.assertRaisesRegex(ValueError,'直接读取'):
                self.run_pipeline(raw,PATTERNS[0],Recipe(response_mode='narrow_red'),**kwargs)
        with self.assertRaisesRegex(ValueError,'严格纯通道无法安全处理'):
            self.run_pipeline(raw,PATTERNS[0],Recipe(response_mode='narrow_blue'),structure_error=ValueError('unverified opcodes'))

    def test_old_recipe_compatibility_and_interpolation_validation(self):
        self.assertEqual(Recipe.from_dict({'version':1}).narrow_interpolation,'cubic')
        self.assertEqual(Recipe.from_dict(Recipe(narrow_interpolation='linear').to_dict()).narrow_interpolation,'linear')
        with self.assertRaises(ValueError):Recipe.from_dict({'narrow_interpolation':'RGB-guided'})


if __name__=='__main__':unittest.main()
