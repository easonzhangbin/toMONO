"""Scheduling changes must not change a single exported sample."""
import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from detail_reconstruction import reconstruct_response

class DetailParallelTests(unittest.TestCase):
    def test_workers_preserve_pixels_counts_phase_and_deferred_values(self):
        rng=np.random.default_rng(1031)
        raw=rng.integers(128,16200,(269,301),dtype=np.uint16)
        original=raw.copy()
        b=np.array([[128,256],[192,128]],float);w=np.full((2,2),16383.)
        for pattern in ('RGGB','GRBG'):
            for method in ('spectral','spectral_guard','directional'):
                for weights,defer in (([0,1,0],False),([.2,.5,.3],True)):
                    kwargs=dict(method=method,black=256,white=16383,exposure_ev=.25,tile_size=128,defer_quantization=defer)
                    a,sa,ca=reconstruct_response(raw,pattern,b,w,weights,workers=1,**kwargs)
                    z,sz,cz=reconstruct_response(raw,pattern,b,w,weights,workers=3,**kwargs)
                    np.testing.assert_array_equal(a,z)
                    self.assertEqual(ca,cz)
                    sa.pop('cpu_workers');sz.pop('cpu_workers');self.assertEqual(sa,sz)
        np.testing.assert_array_equal(raw,original)

    def test_cancellation_propagates_and_invalid_workers_rejected(self):
        raw=np.arange(512*512,dtype=np.uint16).reshape(512,512)
        b=np.zeros((2,2));w=np.full((2,2),65535.)
        def stop(event):
            if event['phase']=='重建所选同色细节':raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            reconstruct_response(raw,'RGGB',b,w,[0,1,0],'spectral',0,65535,workers=3,progress=stop)
        for workers in (0,9,True,1.5):
            with self.assertRaises(ValueError):
                reconstruct_response(raw,'RGGB',b,w,[0,1,0],'spectral',0,65535,workers=workers)
