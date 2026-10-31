import ctypes,os,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dng_writer import make_preview,make_detail_preview,orient_preview
from recipe import Recipe
from defect_map import validate_profile,repair_sensor_map

LIB=ctypes.CDLL(str(Path(__file__).resolve().parents[1]/'build/native-macos/libtomono_core.dylib'))
PTR=ctypes.POINTER(ctypes.c_uint16)
PATTERNS=[[[0,1],[1,2]],[[1,0],[2,1]],[[2,1],[1,0]],[[1,2],[0,1]]]

def reconstruct(samples,pattern,method='edge',threads=1):
    before=os.environ.get('TOMONO_THREADS');os.environ['TOMONO_THREADS']=str(threads)
    try:
        samples=np.ascontiguousarray(samples,np.uint16);out=np.empty_like(samples)
        pr,pc=len(pattern),len(pattern[0]);cfa=(ctypes.c_uint8*(pr*pc))(*sum(pattern,[]))
        args=[samples.ctypes.data_as(PTR),samples.size,out.ctypes.data_as(PTR),out.size,samples.shape[1],samples.shape[0],cfa]
        types=[PTR,ctypes.c_size_t,PTR,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,ctypes.POINTER(ctypes.c_uint8)]
        if method=='edge':fn=LIB.tomono_edge_green_plane;args+=[65535];types+=[ctypes.c_uint]
        elif method=='lattice':fn=LIB.tomono_green_lattice_plane;args+=[pr,pc,65535];types+=[ctypes.c_int,ctypes.c_int,ctypes.c_uint]
        else:
            fn=LIB.tomono_bicubic_green_plane if method=='legacy' else LIB.tomono_bicubic_green_plane_range
            args+=[0,0];types+=[ctypes.c_int,ctypes.c_int]
            if method!='legacy':args+=[65535];types+=[ctypes.c_uint]
        fn.argtypes=types;fn.restype=ctypes.c_int
        if fn(*args):raise AssertionError('core failed')
        return out
    finally:
        if before is None:os.environ.pop('TOMONO_THREADS',None)
        else:os.environ['TOMONO_THREADS']=before

class AdaptiveTests(unittest.TestCase):
    def test_measured_green_unchanged_and_red_blue_do_not_leak(self):
        rng=np.random.default_rng(762);a=rng.integers(0,65536,(320,322),dtype=np.uint16)
        for p in PATTERNS:
            green=np.tile(np.array(p)==1,(160,161));b=a.copy();b[~green]=65535-a[~green]
            out=reconstruct(a,p)
            np.testing.assert_array_equal(out[green],a[green]);np.testing.assert_array_equal(out,reconstruct(b,p))
    def test_constants_ramps_and_boundaries(self):
        for p in PATTERNS:
            np.testing.assert_array_equal(reconstruct(np.full((32,34),60000,np.uint16),p),60000)
        y,x=np.mgrid[:64,:66];ramp=(1000+7*x+11*y).astype(np.uint16)
        out=reconstruct(ramp,PATTERNS[0]);np.testing.assert_array_equal(out[3:-3,3:-3],ramp[3:-3,3:-3])
    def test_axis_edge_reduces_cubic_ringing(self):
        y,x=np.mgrid[:128,:128];truth=np.where(x<64,1000,14000).astype(np.uint16)
        adaptive=reconstruct(truth,PATTERNS[0]);cubic=reconstruct(truth,PATTERNS[0],'bicubic')
        region=np.s_[4:-4,4:-4]
        adaptive_mse=np.mean((adaptive[region].astype(float)-truth[region])**2)
        cubic_mse=np.mean((cubic[region].astype(float)-truth[region])**2)
        self.assertLess(adaptive_mse,cubic_mse)
        self.assertGreaterEqual(adaptive.min(),truth.min());self.assertLessEqual(adaptive.max(),truth.max())
    def test_parallel_is_bit_exact_for_all_core_paths(self):
        a=np.random.default_rng(481).integers(0,16384,(512,514),dtype=np.uint16)
        for method in ('edge','bicubic','legacy','lattice'):
            with self.subTest(method=method):np.testing.assert_array_equal(reconstruct(a,PATTERNS[0],method,1),reconstruct(a,PATTERNS[0],method,4))
    def test_old_recipe_and_new_algorithms_validate(self):
        self.assertIsNone(Recipe.from_dict({'version':1}).defect_profile)
        for mode in ('Bicubic','Auto','EdgeAware'):self.assertEqual(Recipe.from_dict({'algorithm':mode}).algorithm,mode)
        with self.assertRaises(ValueError):Recipe.from_dict({'algorithm':'AI'})
    def test_full_resolution_display_matches_existing_gamma_and_orientation(self):
        a=np.random.default_rng(143).integers(0,16384,(20,24),dtype=np.uint16)
        structure={'active_area':[0,0,20,24],'crop_origin':[2,3],'crop_size':[18,16]}
        for gamma in (1.8,2.2):
            detail=make_detail_preview(a,512,16383,structure,gamma)
            small=make_preview(a,512,16383,structure,gamma,2000)
            for orientation in range(1,9):np.testing.assert_array_equal(orient_preview(detail,orientation),orient_preview(small,orientation)[:,:,0])

class DefectMapTests(unittest.TestCase):
    def profile(self):return dict(version=1,make='Test',model='Synthetic',sensor_size=[40,36],pixels=[[12,11],[14,11],[13,11]])
    def test_sensor_coordinates_crop_origin_and_untargeted_samples(self):
        p=self.profile();a=np.full((32,32),1000,np.uint16);before=a.copy();a[9,8]=0;a[9,10]=16000;a[9,9]=18000
        result=repair_sensor_map(a,PATTERNS[0],p,{'Make':'Test','Model':'Synthetic'},[36,40],[2,4,34,36])
        self.assertEqual(result['repaired'],2);self.assertEqual(result['ignored_non_green'],1)
        self.assertEqual(a[9,8],1000);self.assertEqual(a[9,10],1000);self.assertEqual(a[9,9],18000)
        before[9,9]=18000;np.testing.assert_array_equal(a,before)
    def test_wrong_model_or_geometry_is_rejected_before_any_change(self):
        a=np.full((32,32),1234,np.uint16)
        for structure,shape in (({'Make':'Test','Model':'Other'},[36,40]),({'Make':'Test','Model':'Synthetic'},[36,42])):
            with self.assertRaises(ValueError):repair_sensor_map(a,PATTERNS[0],self.profile(),structure,shape,[2,4,34,36])
        np.testing.assert_array_equal(a,1234)
    def test_duplicate_out_of_range_and_unknown_fields_rejected(self):
        for change in ({'pixels':[[1,1],[1,1]]},{'pixels':[[40,0]]},{'unexpected':0}):
            with self.assertRaises(ValueError):validate_profile(dict(self.profile(),**change))
    def test_no_map_does_not_change_data(self):
        a=np.full((10,10),1000,np.uint16);self.assertEqual(repair_sensor_map(a,PATTERNS[0],None,{},[10,10],[0,0,10,10])['repaired'],0)
        np.testing.assert_array_equal(a,1000)
