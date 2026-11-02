"""Integration contracts for the new detail modes and single quantization path."""
import copy
from contextlib import contextmanager,redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

import imagecodecs
import numpy as np

PORT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PORT))
from recipe import Recipe
from raw_input import SensorFrame
from conversion_service import compute_monochrome,convert_and_save,Cancelled
from dng_reader import read_linear_output
from dng_writer import make_preview,orient_preview
from detail_reconstruction import reconstruct_tiled

MODES=('spectral','spectral_guard','directional')


class DetailPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.folder=Path(self.temp.name)
        self.source=self.folder/'sensor.raw';self.source.write_bytes(b'synthetic decoder fixture; unchanged')
        self.raw=np.random.default_rng(892).integers(900,8000,(64,68),dtype=np.uint16)

    def tearDown(self):self.temp.cleanup()

    @contextmanager
    def source_context(self,raw=None,active=None,blacks=(100,200,300,400),whites=(10000,12000,14000,16000),pattern=None,linear=False):
        raw=self.raw if raw is None else raw
        p=np.array([[0,1],[1,2]] if pattern is None else pattern,np.uint8)
        channels=p.copy()
        greens=np.argwhere(p==1)
        if len(greens)>1:channels[tuple(greens[1])]=3
        active=[0,0,*raw.shape] if active is None else list(active)
        top,left,bottom,right=active
        metadata=dict(sensor_layout='libraw_linear_green' if linear else 'bayer' if p.shape==(2,2) else 'green_lattice',
            linear_reconstruction=linear,cfa_codes_full_origin=p.tolist(),cfa_libraw_channels_full_origin=channels.tolist(),
            black_level_by_libraw_channel=[0]*4 if linear else list(blacks),white_level=65535 if linear else 16383,
            white_level_by_libraw_channel=None if linear else list(whites),camera_whitebalance=[1,1,1,1],
            visible_area=dict(top=top,left=left,height=bottom-top,width=right-left),
            default_crop=dict(top=top,left=left,height=bottom-top,width=right-left),processing='test unpack')
        structure=dict(source_kind='RAW',Make='Test',Model='Camera',UniqueCameraModel='Test Camera',Orientation=1,
            active_area=active,crop_origin=[0,0],crop_size=[right-left,bottom-top],safe_render_tags=[],lens_metadata={},
            camera_identity=dict(make='Test',model='Camera',serial='same'))
        def decode(*args,**kwargs):return SensorFrame(raw.copy(),copy.deepcopy(metadata))
        with patch('conversion_service.decode_sensor',side_effect=decode),\
             patch('conversion_service.source_structure',side_effect=lambda *args:copy.deepcopy(structure)),\
             patch('pure_narrowband.decode_sensor',side_effect=decode),\
             patch('pure_narrowband.source_structure',side_effect=lambda *args:copy.deepcopy(structure)):
            yield

    def test_every_mode_restores_float64_phase_measurements_then_applies_EV_once(self):
        before=self.raw.copy();active=(1,1,61,65)
        for mode in MODES:
            for response,target in [('green',1),('narrow_red',0),('narrow_green',1),('narrow_blue',2)]:
                with self.source_context(active=active):
                    out,metadata,params,structure,_=compute_monochrome(self.source,Recipe(detail_mode=mode,response_mode=response,response_exposure=1.3,green_mode='off'))
                raw=self.raw[1:61,1:65];yy,xx=np.indices(raw.shape)
                full_channels=np.array([[0,1],[3,2]])[(yy+1)%2,(xx+1)%2]
                codes=np.array([[0,1],[1,2]])[(yy+1)%2,(xx+1)%2]
                b=np.array([100,200,300,400])[full_channels];w=np.array([10000,12000,14000,16000])[full_channels]
                black=metadata['black_level_by_libraw_channel'][0];white=metadata['white_level']
                expected=np.clip(np.rint(black+(raw.astype(np.float64)-b)/(w-b)*(white-black)*2**1.3),0,65535).astype(np.uint16)
                np.testing.assert_array_equal(out[codes==target],expected[codes==target])
                self.assertEqual(params['effective_detail_mode'],mode)
                self.assertTrue(params['detail_response_complete'])
                self.assertEqual(structure['active_area'],[0,0,60,64])
                self.assertEqual(params['response']['exposure_ev'],1.3)
        np.testing.assert_array_equal(self.raw,before)

    def test_mix_keeps_float_channels_until_one_final_round(self):
        p=np.array([[0,1],[1,2]],np.uint8);channels=np.array([[0,1],[3,2]])
        blacks=np.array([100,200,300,400])[channels];whites=np.array([10000,12000,14000,16000])[channels]
        normalized=np.empty(self.raw.shape,np.float64)
        for y in range(2):
            for x in range(2):normalized[y::2,x::2]=(self.raw[y::2,x::2].astype(np.float64)-blacks[y,x])/(whites[y,x]-blacks[y,x])
        weights=np.array([.17,.51,.32])
        for mode in MODES:
            mixed=np.zeros(self.raw.shape,np.float64)
            for target,weight in enumerate(weights):
                plane=reconstruct_tiled(normalized,p,target,mode).astype(np.float64)
                for y,x in np.argwhere(p==target):plane[y::2,x::2]=normalized[y::2,x::2]
                mixed+=weight*plane
            expected=np.clip(np.rint(200+mixed*(12000-200)*2**.7),0,65535).astype(np.uint16)
            with self.source_context():
                out,_,params,_,_=compute_monochrome(self.source,Recipe(detail_mode=mode,response_mode='mix',response_red=.17,response_green=.51,response_blue=.32,response_exposure=.7,green_mode='off'))
            np.testing.assert_array_equal(out,expected)
            self.assertIn('one final rint',params['response']['quantization'])

    def test_optional_G_correction_precedes_kernels_and_strict_narrowband_disables_it(self):
        raw=np.full(self.raw.shape,6000,np.uint16);raw[1::2,0::2]=8000
        for mode in MODES:
            settings=dict(detail_mode=mode,green_mode='manual',compensation=1.005,focus_red=False,focus_blue=False)
            with self.source_context(raw,blacks=(512,)*4,whites=(16383,)*4):
                ordinary,_,params,_,changed=compute_monochrome(self.source,Recipe(**settings))
                strict,_,strict_params,_,strict_changed=compute_monochrome(self.source,Recipe(response_mode='narrow_green',**settings))
            self.assertGreater(changed,0);self.assertEqual(ordinary[9,8],6000)
            self.assertEqual(strict[9,8],8000);self.assertEqual(strict_changed,0)
            self.assertEqual(strict_params['green_compensation'],0)
            self.assertIn('before kernels',params['green_correction_policy'])

    def test_mix_target_defect_repair_precedes_kernel_and_source_stays_unchanged(self):
        yy,xx=np.indices(self.raw.shape);codes=np.array([[0,1],[1,2]])[yy%2,xx%2]
        raw=np.choose(codes,[3000,6000,9000]).astype(np.uint16);raw[8,8]=0;raw[9,9]=0
        before=raw.copy()
        profile=dict(version=1,make='Test',model='Camera',sensor_size=list(raw.shape[::-1]),pixels=[[8,8],[9,9]])
        with self.source_context(raw,blacks=(512,)*4,whites=(16383,)*4):
            out,_,params,_,_=compute_monochrome(self.source,Recipe(response_mode='mix',response_red=.5,response_green=0,response_blue=.5,defect_profile=profile))
        np.testing.assert_array_equal(out,np.full(raw.shape,6000,np.uint16))
        self.assertEqual(params['defect_repair']['repaired'],2)
        self.assertEqual(params['green_compensation'],0)
        np.testing.assert_array_equal(raw,before)

    def test_linear_and_non_Bayer_fallback_are_declared(self):
        for linear,pattern in [(True,[[0,1],[1,2]]),(False,[[1]])]:
            for request in (Recipe(),Recipe(detail_mode='spectral'),Recipe(detail_mode='lmmse')):
                with self.source_context(raw=np.full((32,34),3000,np.uint16),pattern=pattern,linear=linear):
                    _,_,params,_,_=compute_monochrome(self.source,request)
                self.assertEqual(params['requested_detail_mode'],request.detail_mode)
                self.assertEqual(params['effective_detail_mode'],'legacy')
                self.assertTrue(params['detail_fallback_reason'])

    def test_cancel_during_tile_processing_creates_no_output(self):
        destination=self.folder/'cancelled.dng'
        def cancel(event):
            if event['phase']=='重建所选同色细节':raise Cancelled()
        with self.source_context(),patch('conversion_service.write_dng') as writer:
            with self.assertRaises(Cancelled):convert_and_save(self.source,destination,progress=cancel)
        writer.assert_not_called();self.assertFalse(destination.exists())
        self.assertEqual(list(self.folder.glob('.tomono-*')),[])

    def test_selected_lens_receives_unquantized_DN_and_rounds_only_at_the_end(self):
        config=dict(profile_id='0'*64,distance=1.,distortion=True,vignetting=False)
        received=[];factor=.637
        def lens(pixels,metadata,parameters,structure,config,checkpoint):
            self.assertEqual(pixels.dtype,np.float64)
            received.append(pixels.copy())
            black=metadata['black_level_by_libraw_channel'][0]
            output=np.clip(np.rint(black+(pixels-black)*factor),0,65535).astype(np.uint16)
            return output,metadata,dict(parameters,lens_correction=dict(applied=True)),structure
        yy,xx=np.indices(self.raw.shape);channels=np.array([[0,1],[3,2]])[yy%2,xx%2]
        green=(channels==1)|(channels==3)
        b=np.array([100,200,300,400])[channels];w=np.array([10000,12000,14000,16000])[channels]
        expected=np.clip(np.rint(200+(self.raw.astype(np.float64)-b)/(w-b)*(12000-200)*2**.3*factor),0,65535).astype(np.uint16)
        for mode in MODES:
            for response in ('green','narrow_green'):
                with self.source_context(),patch('lens_correction.apply_lens',side_effect=lens):
                    out,_,params,_,_=compute_monochrome(self.source,Recipe(detail_mode=mode,response_mode=response,green_mode='off',response_exposure=.3,lens_correction=config))
                np.testing.assert_array_equal(out[green],expected[green])
                self.assertTrue(params['response']['quantization_deferred_for_lens'])
        self.assertEqual(len(received),6)

    def test_no_op_lens_configuration_still_finalizes_uint16_once(self):
        config=dict(profile_id='0'*64,distance=1.,distortion=False,vignetting=False)
        def no_op(pixels,metadata,parameters,structure,*_):
            self.assertEqual(pixels.dtype,np.float64)
            return pixels,metadata,parameters,structure
        with self.source_context():expected,*_=compute_monochrome(self.source,Recipe(response_exposure=.3))
        with self.source_context(),patch('lens_correction.apply_lens',side_effect=no_op):
            actual,*_=compute_monochrome(self.source,Recipe(response_exposure=.3,lens_correction=config))
        self.assertEqual(actual.dtype,np.uint16)
        np.testing.assert_array_equal(actual,expected)

    def test_default_detail_preview_and_saved_DNG_have_same_pixels_and_parameters(self):
        import monochrome_preview
        # Capture tags are irrelevant to the injected sensor fixture. Imaging
        # settings, including the new default D10, remain the product defaults.
        recipe=Recipe(preserve_capture=False,preserve_description=False)
        recipe_path=self.folder/'recipe.json';recipe.save(recipe_path)
        png=self.folder/'preview.png';dng=self.folder/'saved.dng';previous=signal.getsignal(signal.SIGINT)
        stdout=io.StringIO()
        try:
            with self.source_context(),patch.object(sys,'argv',['preview',str(self.source),'-o',str(png),'--recipe',str(recipe_path),'--max-width','128','--log',str(self.folder/'preview.log')]),redirect_stdout(stdout):
                self.assertEqual(monochrome_preview.main(),0)
            preview=json.loads(stdout.getvalue())
            with self.source_context():saved=convert_and_save(self.source,dng,recipe)
        finally:signal.signal(signal.SIGINT,previous)
        pixels=read_linear_output(dng)
        self.assertEqual(preview['raw_sha256'],saved['raw_sha256'])
        self.assertEqual(saved['raw_sha256'],hashlib.sha256(memoryview(pixels)).hexdigest())
        self.assertEqual(preview['recipe'],saved['recipe'])
        for field in ('requested_detail_mode','effective_detail_mode','detail_method_code','response'):
            self.assertEqual(preview['resolved_parameters'][field],saved['resolved_parameters'][field])
        expected=make_preview(pixels,200,12000,dict(active_area=[0,0,*pixels.shape],crop_origin=[0,0],crop_size=list(pixels.shape[::-1]),Orientation=1),2.2,128)
        np.testing.assert_array_equal(imagecodecs.png_decode(png.read_bytes()),expected)


if __name__=='__main__':unittest.main()
