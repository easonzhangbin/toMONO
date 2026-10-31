"""Independent product-kernel equivalence against immutable research kernels.

Requires the local research checkout and its already-built reference libraries.
No research source/binary is built or changed by these tests. The product is
tested with SciPy imports and subprocess execution forbidden as well.
"""
import builtins
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

PORTABLE=Path(__file__).resolve().parents[1]
ROOT=PORTABLE.parent
sys.path.insert(0,str(PORTABLE))
import detail_reconstruction as product

PATTERNS={
    'RGGB':np.array([[0,1],[1,2]],np.uint8),
    'BGGR':np.array([[2,1],[1,0]],np.uint8),
    'GRBG':np.array([[1,0],[2,1]],np.uint8),
    'GBRG':np.array([[1,2],[0,1]],np.uint8),
}
REFERENCE={
    'spectral':('v1','quincunx_spectral'),
    'spectral_guard':('v2','spectral_local_guard'),
    'directional':('v2','g_ar_reliable'),
}
TOLERANCE=5e-7


def load_reference(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sample_mask(pattern,target,shape):
    yy,xx=np.indices(shape)
    return pattern[yy%2,xx%2]==target


class DetailFrozenReferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        paths={
            'v1':ROOT/'analysis/detail_resolution_20261031',
            'v2':ROOT/'analysis/detail_resolution_v2_20261031',
        }
        if not all((p/'kernel_manifest.json').is_file() for p in paths.values()):
            raise unittest.SkipTest('Frozen research checkout is not present')
        cls.reference={}
        cls.frozen_hashes={}
        for name,directory in paths.items():
            manifest=json.loads((directory/'kernel_manifest.json').read_text())
            for filename in ('kernels.py','detail_native.c'):
                path=directory/filename
                actual=hashlib.sha256(path.read_bytes()).hexdigest()
                if actual!=manifest['file_sha256'][filename]:
                    raise AssertionError(f'Frozen reference changed: {path}')
                cls.frozen_hashes[str(path)]=actual
            # Avoid the reference helper's optional runtime compilation path.
            source_hash=hashlib.sha256((directory/'detail_native.c').read_bytes()).hexdigest()[:16]
            suffix='.dylib' if sys.platform=='darwin' else '.so'
            binary=directory/('detail_native_'+source_hash+suffix)
            if not binary.is_file():
                raise unittest.SkipTest('Already-built frozen reference library is required')
            cls.frozen_hashes[str(binary)]=hashlib.sha256(binary.read_bytes()).hexdigest()
            cls.reference[name]=load_reference('_frozen_detail_reference_'+name,directory/'kernels.py')
            with patch('subprocess.run',side_effect=AssertionError('Reference test may not compile code')):
                cls.reference[name]._library()
        cls.maximum_errors={mode:0. for mode in REFERENCE}
        cls.tile_maximum_errors={mode:0. for mode in REFERENCE}
        cls.comparisons=0

    @classmethod
    def tearDownClass(cls):
        for path,expected in cls.frozen_hashes.items():
            actual=hashlib.sha256(Path(path).read_bytes()).hexdigest()
            if actual!=expected:
                raise AssertionError(f'Equivalence tests changed frozen evidence: {path}')
        print(json.dumps(dict(detail_frozen_reference=dict(
            comparisons=cls.comparisons,absolute_tolerance=TOLERANCE,
            maximum_absolute_errors=cls.maximum_errors,
            whole_vs_tiled_maximum_errors=cls.tile_maximum_errors,
            frozen_reference_files_unchanged=True)),sort_keys=True))

    def reference_output(self,values,pattern,target,mode,sigma=0.):
        version,name=REFERENCE[mode]
        return self.reference[version].reconstruct(values,pattern,target,name,noise_sigma=sigma)

    def assert_reference(self,actual,expected,mode):
        error=float(np.max(np.abs(actual.astype(float)-expected.astype(float))))
        self.maximum_errors[mode]=max(self.maximum_errors[mode],error)
        type(self).comparisons+=1
        self.assertLessEqual(error,TOLERANCE,f'{mode}: research equivalence exceeded')

    def test_four_patterns_odd_even_dimensions_isolation_and_exact_measurements(self):
        rng=np.random.default_rng(110731)
        for shape in ((9,11),(68,70),(129,133)):
            values=rng.uniform(-.04,1.1,shape)
            for pname,pattern in PATTERNS.items():
                for target in range(3):
                    mask=sample_mask(pattern,target,shape)
                    poison=values.copy();poison[~mask]=np.nan
                    before=poison.copy()
                    for mode in REFERENCE:
                        with self.subTest(shape=shape,pattern=pname,target=target,mode=mode):
                            expected=self.reference_output(poison,pattern,target,mode)
                            actual=product.reconstruct(poison,pattern,target,mode)
                            self.assert_reference(actual,expected,mode)
                            self.assertEqual(actual.dtype,np.float32)
                            self.assertEqual(actual.shape,shape)
                            self.assertTrue(np.isfinite(actual).all())
                            np.testing.assert_array_equal(actual[mask],values.astype(np.float32)[mask])
                            # Arbitrary other-colour numbers must equal the poisoned run.
                            other=product.reconstruct(values,pattern,target,mode)
                            np.testing.assert_array_equal(actual,other)
                            np.testing.assert_array_equal(poison,before)

    def test_parity_aware_halo_tiles_equal_whole_and_frozen_reference(self):
        rng=np.random.default_rng(110732)
        values=rng.uniform(-.01,1.02,(129,133))
        for pname,pattern in PATTERNS.items():
            for target in range(3):
                mask=sample_mask(pattern,target,values.shape)
                only=values.copy();only[~mask]=np.nan
                for mode in REFERENCE:
                    with self.subTest(pattern=pname,target=target,mode=mode):
                        whole=product.reconstruct(only,pattern,target,mode)
                        tiled=product.reconstruct_tiled(only,pattern,target,mode,tile_size=32)
                        reference=self.reference_output(only,pattern,target,mode)
                        self.assert_reference(tiled,reference,mode)
                        maximum=float(abs(tiled.astype(float)-whole.astype(float)).max())
                        self.tile_maximum_errors[mode]=max(self.tile_maximum_errors[mode],maximum)
                        self.assertLessEqual(maximum,TOLERANCE)
                        np.testing.assert_array_equal(tiled[mask],values.astype(np.float32)[mask])

    def test_known_sigma_guard_and_directional_sigma_policy_match_reference(self):
        rng=np.random.default_rng(110733)
        values=.04+rng.normal(0,.012,(65,67))
        for pname,pattern in PATTERNS.items():
            for target in range(3):
                mask=sample_mask(pattern,target,values.shape)
                only=values.copy();only[~mask]=np.nan
                for mode in ('spectral_guard','directional'):
                    with self.subTest(pattern=pname,target=target,mode=mode):
                        actual=product.reconstruct(only,pattern,target,mode,noise_sigma=.008)
                        expected=self.reference_output(only,pattern,target,mode,sigma=.008)
                        self.assert_reference(actual,expected,mode)
                        np.testing.assert_array_equal(actual[mask],values.astype(np.float32)[mask])
                        tiled=product.reconstruct_tiled(only,pattern,target,mode,noise_sigma=.008,tile_size=32)
                        self.assert_reference(tiled,expected,mode)
                        if mode=='directional':
                            zero=product.reconstruct(only,pattern,target,mode,noise_sigma=0.)
                            np.testing.assert_array_equal(actual,zero)

    def test_directional_red_blue_common_cubic_fallback_is_exact_frozen_behavior(self):
        yy,xx=np.indices((64,66));pattern=PATTERNS['RGGB']
        values=.2+.08*np.cos(.57*xx)+.07*np.sin(.41*yy)+.03*((xx>32)&(yy>29))
        # Both R/B are separate actual CFA subsets, not the new G-only AR.
        for target in (0,2):
            mask=sample_mask(pattern,target,values.shape)
            only=values.copy();only[~mask]=np.nan
            actual=product.reconstruct(only,pattern,target,'directional',noise_sigma=0.)
            expected=self.reference_output(only,pattern,target,'directional')
            np.testing.assert_array_equal(actual,expected)
            self.assert_reference(actual,expected,'directional')
            info=product.method_info('directional',target)
            self.assertTrue(info['RB_directional_fallback'])

    def test_flat_normalized_values_preserve_negative_and_above_white_levels(self):
        shape=(33,35)
        for pattern in PATTERNS.values():
            for target in range(3):
                mask=sample_mask(pattern,target,shape)
                for level in (-.025,.18,1.075):
                    only=np.full(shape,np.nan);only[mask]=level
                    for mode in REFERENCE:
                        actual=product.reconstruct(only,pattern,target,mode)
                        np.testing.assert_array_equal(actual,np.full(shape,level,np.float32))

    def test_runtime_requires_neither_scipy_nor_a_compiler(self):
        binary=PORTABLE/'build/native-macos/libtomono_detail.dylib'
        self.assertTrue(binary.is_file(),'Product detail library must be built during packaging')
        values=np.random.default_rng(110734).uniform(.01,.9,(47,49))
        original_import=builtins.__import__
        def guarded_import(name,*args,**kwargs):
            if name=='scipy' or name.startswith('scipy.'):
                raise AssertionError('Distributable detail kernels must not import SciPy')
            return original_import(name,*args,**kwargs)
        # Fresh module proves import and first native load use only shipped code.
        with patch('builtins.__import__',side_effect=guarded_import),\
             patch('subprocess.run',side_effect=AssertionError('Runtime compilation/process launch is forbidden')):
            isolated=load_reference('_product_detail_dependency_policy',PORTABLE/'detail_reconstruction.py')
            for target in range(3):
                for mode in REFERENCE:
                    result=isolated.reconstruct(values,PATTERNS['RGGB'],target,mode)
                    self.assertTrue(np.isfinite(result).all())
            self.assertEqual(isolated._library().tomono_detail_version(),0x100)


if __name__=='__main__':unittest.main()
