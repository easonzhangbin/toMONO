"""Product integration preserves the frozen reference and ordinary-only scope."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

PORT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PORT))
import lmmse_reconstruction as product
from recipe import Recipe
from conversion_service import compute_monochrome
import test_detail_pipeline as fixtures


class LMMSEProductTests(unittest.TestCase):
    setUp=fixtures.DetailPipelineTests.setUp
    tearDown=fixtures.DetailPipelineTests.tearDown
    source_context=fixtures.DetailPipelineTests.source_context
    def test_lmmse_exposes_cross_colour_provenance_and_restores_measurements(self):
        before=self.raw.copy()
        with self.source_context(blacks=(512,)*4,whites=(16383,)*4):
            pixels,_,parameters,_,_=compute_monochrome(self.source,Recipe(detail_mode='lmmse',green_mode='off'))
        self.assertEqual(parameters['detail_method_code'],'LMMSE')
        self.assertFalse(parameters['response']['selected_kernel_same_colour'])
        self.assertFalse(parameters['response']['digital_channel_isolation'])
        self.assertTrue(parameters['detail_reconstruction']['experimental'])
        np.testing.assert_array_equal(pixels[0::2,1::2],self.raw[0::2,1::2])
        np.testing.assert_array_equal(pixels[1::2,0::2],self.raw[1::2,0::2])
        np.testing.assert_array_equal(self.raw,before)

    def test_lmmse_preview_and_export_numerics_are_identical(self):
        with self.source_context():
            a,*_=compute_monochrome(self.source,Recipe(detail_mode='lmmse',green_mode='off'))
            b,_,parameters,_,_=compute_monochrome(self.source,Recipe(detail_mode='lmmse',green_mode='off'),diagnostics=True)
        np.testing.assert_array_equal(a,b)
        region=parameters['inspection_regions']['regions'][0]['rect']
        self.assertEqual(len(region),4)

    def test_strict_narrowband_rejected_before_sensor_decode(self):
        for channel in ('red','green','blue'):
            with patch('conversion_service.decode_sensor') as decoder:
                with self.assertRaisesRegex(ValueError,'窄带|纯通道'):
                    compute_monochrome(self.source,Recipe(detail_mode='lmmse',response_mode='narrow_'+channel))
                decoder.assert_not_called()

    def test_product_port_is_exact_to_frozen_research_lmmse(self):
        path=PORT.parent/'analysis/lmmse_research_20261101/prototype/lmmse_reconstruction.py'
        if not path.exists():self.skipTest('Private frozen research checkout unavailable')
        manifest=json.loads((path.parent/'kernel_manifest.json').read_text())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),manifest['source_sha256'][path.name])
        spec=importlib.util.spec_from_file_location('_frozen_lmmse_test',path)
        frozen=importlib.util.module_from_spec(spec);spec.loader.exec_module(frozen)
        rng=np.random.default_rng(10011)
        for name,p in product._PATTERNS.items():
            source=rng.uniform(-.01,1.01,(65,69))
            np.testing.assert_array_equal(product.reconstruct_rgb(source,name),frozen.reconstruct_rgb(source,name))
            raw=rng.integers(0,16384,(67,71),dtype=np.uint16);before=raw.copy()
            for weights in ([0,1,0],[.2,.5,.3]):
                args=(raw,p,[[64,64],[64,64]],[[16383,16383],[16383,16383]],weights,'lmmse',64,16383,.7)
                actual=product.reconstruct_response(*args,workers=3)[0]
                expected=frozen.reconstruct_response(*args,workers=3)[0]
                np.testing.assert_array_equal(actual,expected)
                np.testing.assert_array_equal(raw,before)

    def test_lmmse_reads_other_colours_and_declares_that_constraint(self):
        y,x=np.indices((64,68));p=np.array([[0,1],[1,2]]);codes=p[y%2,x%2]
        a=np.full(codes.shape,.2);b=a.copy()
        b[codes==0]=(.5+.4*np.sin(x*.2*2*np.pi))[codes==0]
        b[codes==2]=(.5+.4*np.cos(x*.2*2*np.pi))[codes==2]
        aa=product.reconstruct_rgb(a,p)[:,:,1];bb=product.reconstruct_rgb(b,p)[:,:,1]
        self.assertGreater(float(abs(aa-bb).max()),.01)
        np.testing.assert_array_equal(aa[codes==1],bb[codes==1])


if __name__=='__main__':unittest.main()
