import ctypes,os,sys,tempfile,unittest
from unittest.mock import patch,MagicMock
from pathlib import Path
import numpy as np,tifffile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recipe import Recipe
from conversion_service import compute_monochrome
from channel_response import response_weights,apply_response,native_core
from raw_input import SensorFrame

PORT=Path(__file__).resolve().parents[1]
class ChannelCoreTests(unittest.TestCase):
    def test_incompatible_native_channel_abi_is_rejected_before_calling(self):
        old=MagicMock();old.tomono_core_version.return_value=0x400
        with patch('channel_response.ctypes.CDLL',return_value=old):
            with self.assertRaisesRegex(RuntimeError,'版本不匹配'):native_core()
    def strip(self,a,pattern,target,rows=256,black=0,white=16383):
        lib=ctypes.CDLL(str(PORT/'build/native-macos/libtomono_core.dylib'));f=lib.tomono_channel_strip
        u16=ctypes.POINTER(ctypes.c_uint16);u8=ctypes.POINTER(ctypes.c_uint8);f64=ctypes.POINTER(ctypes.c_double)
        f.argtypes=[u16,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,u8,ctypes.c_int,ctypes.c_int,ctypes.c_int,f64,f64,ctypes.c_int,ctypes.c_int,f64,ctypes.c_size_t]
        p=np.array(pattern,np.uint8);g=np.full(p.shape,black,np.float64);b=np.full(p.shape,white,np.float64)
        out=np.empty(a.shape,np.float64)
        for start in range(0,a.shape[0],rows):
            block=out[start:start+rows]
            self.assertEqual(f(a.ctypes.data_as(u16),a.size,a.shape[1],a.shape[0],p.ctypes.data_as(u8),p.shape[0],p.shape[1],target,g.ctypes.data_as(f64),b.ctypes.data_as(f64),start,block.shape[0],block.ctypes.data_as(f64),block.size),0)
        return out
    def test_measured_half_rounding_with_different_channel_white_points(self):
        a=np.tile(np.arange(300,300+400,dtype=np.uint16),(32,1))
        normalized=self.strip(a,[[0,1],[1,2]],0,black=511,white=16383)
        actual=np.rint(normalized[0::2,0::2]*15808+511)
        expected=np.rint((a[0::2,0::2].astype(np.float64)-511)/(16383-511)*15808+511)
        np.testing.assert_array_equal(actual,expected)
    def test_all_bayer_orders_preserve_measured_sites_and_constant_response(self):
        for p in ([[0,1],[1,2]],[[2,1],[1,0]],[[1,0],[2,1]],[[1,2],[0,1]]):
            for target in (0,2):
                a=np.full((34,36),500,np.uint16);mask=np.tile(np.array(p)==target,(17,18));a[mask]=7000
                out=self.strip(a,p,target);np.testing.assert_allclose(out,7000/16383,rtol=1e-7)
                a=np.random.default_rng(41).integers(0,16384,a.shape,dtype=np.uint16);out=self.strip(a,p,target)
                np.testing.assert_allclose(out[mask],a[mask]/16383,atol=6e-8)
                self.assertGreaterEqual(out.min(),a[mask].min()/16383-1e-7);self.assertLessEqual(out.max(),a[mask].max()/16383+1e-7)
    def test_linear_ramp_and_no_cubic_step_ringing(self):
        y,x=np.mgrid[:64,:66];ramp=(2000+7*x+11*y).astype(np.uint16)
        for target in (0,2):
            out=self.strip(ramp,[[0,1],[1,2]],target)
            np.testing.assert_allclose(out[6:-6,6:-6]*16383,ramp[6:-6,6:-6],atol=.001)
            step=np.where(x<32,1000,14000).astype(np.uint16);out=self.strip(step,[[0,1],[1,2]],target)
            self.assertGreaterEqual(out.min(),1000/16383-1e-7);self.assertLessEqual(out.max(),14000/16383+1e-7)
    def test_strips_and_multicore_are_bit_exact(self):
        a=np.random.default_rng(18).integers(0,16384,(520,530),dtype=np.uint16);old=os.environ.get('TOMONO_THREADS')
        try:
            os.environ['TOMONO_THREADS']='1';serial=self.strip(a,[[0,1],[1,2]],2,520)
            os.environ['TOMONO_THREADS']='4';parallel=self.strip(a,[[0,1],[1,2]],2,256)
            np.testing.assert_array_equal(serial,parallel)
        finally:
            if old is None:os.environ.pop('TOMONO_THREADS',None)
            else:os.environ['TOMONO_THREADS']=old
    def test_non_bayer_same_color_lattice(self):
        p=np.array([[1,0,1,1,2,1],[2,1,2,0,1,0],[1,0,1,1,2,1],[1,2,1,1,0,1],[0,1,0,2,1,2],[1,2,1,1,0,1]],np.uint8)
        for target in (0,2):
            a=np.full((36,42),500,np.uint16);a[np.tile(p==target,(6,7))]=12000
            np.testing.assert_allclose(self.strip(a,p,target),12000/16383,atol=1e-7)

class ResponsePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'camera.dng'
        a=np.full((200,300),3000,np.uint16);a[0::2,0::2]=1500;a[1::2,1::2]=6000
        identity=tuple(x for value in [1,0,0,0,1,0,0,0,1] for x in (value,1))
        tifffile.imwrite(self.path,a,photometric=32803,metadata=None,extratags=[(271,'s',0,'Synthetic',False),(272,'s',0,'RGB Test',False),(50708,'s',0,'Synthetic RGB Test',False),(50706,'B',4,(1,4,0,0),False),(50707,'B',4,(1,3,0,0),False),(33421,'H',2,(2,2),False),(33422,'B',4,(0,1,1,2),False),(50721,'2i',9,identity,False),(50728,'2I',3,(1,4,1,1,1,2),False),(50714,'2I',1,(64,1),False),(50717,'I',1,16383,False),(50778,'H',1,21,False)])
    def tearDown(self):self.tmp.cleanup()
    def compute(self,**kw):return compute_monochrome(self.path,Recipe(**kw),diagnostics=True)
    def test_narrowband_reads_real_red_blue_without_wb_gain(self):
        for mode,value in (('narrow_red',1500),('narrow_green',3000),('narrow_blue',6000)):
            out,*_=self.compute(response_mode=mode);np.testing.assert_array_equal(out,np.full_like(out,value))
    def test_normalized_mixing_and_separate_exposure(self):
        a,*_=self.compute(response_mode='mix',response_red=.25,response_green=.5,response_blue=.25)
        np.testing.assert_array_equal(a,np.full_like(a,3375))
        b,*_=self.compute(response_mode='mix',response_red=.5,response_green=1,response_blue=.5)
        np.testing.assert_array_equal(a,b)
        a,*_=self.compute(response_exposure=1);np.testing.assert_array_equal(a,np.full_like(a,5936))
    def test_pure_green_is_legacy_exact_and_raw_rgb_counts_precede_processing(self):
        a,*_=self.compute(detail_mode='legacy');b,m,p,s,n=self.compute(detail_mode='legacy',response_mode='mix',response_red=0,response_green=1,response_blue=0)
        np.testing.assert_array_equal(a,b);self.assertTrue(p['response']['reference_exact'])
        hist=p['raw_histogram'];self.assertEqual(hist['scope'],'sensor_cfa')
        self.assertEqual([c['sample_count'] for c in hist['channels']],[15000,30000,15000])
        for c,value in zip(hist['channels'],(1500,3000,6000)):
            self.assertEqual(sum(c['bins']),c['sample_count']);self.assertAlmostEqual(c['mean_signal'],(value-64)/(16383-64))
    def test_new_fields_validate_and_old_recipe_remains_green(self):
        self.assertEqual(Recipe.from_dict({'version':1}).response_mode,'green')
        for kw in ({'response_mode':'bad'},{'response_red':float('nan')},{'response_blue':True},{'response_exposure':7},{'response_mode':'mix','response_red':0,'response_green':0,'response_blue':0}):
            with self.assertRaises(ValueError):Recipe.from_dict(kw)
    def test_linear_fallback_retains_real_channels(self):
        g=np.full((20,24),30000,np.uint16);rgb=np.stack([g//3,g,g+20000],axis=-1)
        frame=SensorFrame(g,{'linear_reconstruction':True},rgb)
        metadata={'black_level_by_libraw_channel':[0]*4,'white_level':65535};p={}
        out=apply_response(g,metadata,p,{},frame,Recipe(response_mode='narrow_blue'))
        np.testing.assert_array_equal(out,np.full_like(g,50000))
    def test_container_overflow_is_reported(self):
        out,m,p,s,n=self.compute(response_mode='narrow_blue',response_exposure=6)
        self.assertTrue(np.all(out==65535));self.assertEqual(p['response']['container_clipped_high'],out.size);self.assertTrue(p['response']['warnings'])
