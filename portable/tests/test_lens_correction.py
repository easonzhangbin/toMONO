import ctypes,sys,unittest
from pathlib import Path
import numpy as np,lensfunpy
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from lens_correction import catalog,database,profile_key,Modifier,apply_lens,validate_config
from recipe import Recipe

class LensTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.lens=next(l for l in database().lenses if l.calib_distortion and l.calib_vignetting)
    def config(self,**changes):
        lens=self.lens
        return dict(dict(profile_id=profile_key(lens),focal_override=lens.min_focal,aperture_override=lens.min_aperture,crop_override=lens.crop_factor,distance=10,distortion=True,vignetting=True),**changes)
    def test_offline_catalog_has_unique_profiles_and_calibration_capabilities(self):
        rows=catalog()['profiles'];self.assertGreater(len(rows),1000);self.assertEqual(len(rows),len(set(r['id'] for r in rows)))
        self.assertTrue(any(r['maker']=='Sony' and r['distortion'] for r in rows));self.assertEqual(len(catalog()['database_sha256']),64)
    def test_strip_gain_and_coordinates_match_library_reference(self):
        lens=self.lens
        with Modifier(lens,lens.crop_factor,300,200,lens.min_focal,lens.min_aperture,10,8|32|2) as modifier:
            work=np.ones((200,300),np.float32)
            modifier.vignette_strip(work[:100],0);modifier.vignette_strip(work[100:],100)
            reference=lensfunpy.Modifier(lens,lens.crop_factor,300,200)
            reference.initialize(lens.min_focal,lens.min_aperture,10,scale=0,pixel_format=np.float32,flags=8|32|2,targeom=lens.type)
            rgb=np.ones((200,300,3),np.float32);reference.apply_color_modification(rgb)
            # Lensfun float-coordinate accumulation restarts at tile boundaries.
            np.testing.assert_allclose(work,rgb[:,:,1],rtol=4e-6)
            np.testing.assert_allclose(modifier.coords(300,80,40),reference.apply_geometry_distortion(yu=40,width=300,height=80),atol=1e-4)
    def test_correction_is_explicit_preserves_source_and_blocks_repeat(self):
        a=np.full((200,300),1000,np.uint16);before=a.copy();meta={'black_level_by_libraw_channel':[64]*4}
        structure={'active_area':[0,0,200,300],'crop_origin':[0,0],'crop_size':[300,200]}
        self.assertIs(apply_lens(a,meta,{},structure,None)[0],a)
        corrected,m,p,s=apply_lens(a,meta,{},structure,self.config())
        self.assertGreater(corrected[10,10],corrected[100,150]);self.assertTrue(p['lens_correction']['applied'])
        self.assertFalse(p['lens_correction']['tca_applied']);np.testing.assert_array_equal(a,before)
        with self.assertRaisesRegex(ValueError,'已经应用'):apply_lens(a,meta,{},dict(structure,lens_correction_already_applied=True),self.config())
    def test_missing_capture_parameters_are_not_invented(self):
        config=self.config();config.pop('focal_override');config.pop('crop_override');config.pop('aperture_override')
        validate_config(config)
        with self.assertRaisesRegex(ValueError,'缺少镜头焦距或画幅系数'):
            apply_lens(np.full((20,30),1000,np.uint16),{'black_level_by_libraw_channel':[64]*4},{},{'active_area':[0,0,20,30],'crop_origin':[0,0],'crop_size':[30,20]},config)
    def test_recipe_roundtrip_and_invalid_parameters(self):
        config=self.config();self.assertEqual(Recipe.from_dict(Recipe(lens_correction=config).to_dict()).lens_correction,config)
        for change in ({'distance':0},{'focal_override':float('nan')},{'distortion':1},{'unknown':0}):
            with self.assertRaises(ValueError):validate_config(dict(config,**change))
    def test_native_remap_identity_and_affine_linear_units(self):
        lib=ctypes.CDLL(str(Path(__file__).resolve().parents[1]/'build/native-macos/libtomono_core.dylib'))
        fp=ctypes.POINTER(ctypes.c_float);up=ctypes.POINTER(ctypes.c_uint16);fn=lib.tomono_remap_gray_strip
        fn.argtypes=[fp,ctypes.c_size_t,ctypes.c_int,ctypes.c_int,fp,ctypes.c_size_t,up,ctypes.c_size_t,ctypes.c_int,ctypes.c_float]
        y,x=np.mgrid[:32,:40];a=(1000+x*10+y*5).astype(np.float32);coords=np.stack([x,y],axis=2).astype(np.float32);output=np.empty(a.shape,np.uint16)
        def execute():self.assertEqual(fn(a.ctypes.data_as(fp),a.size,40,32,coords.ctypes.data_as(fp),coords.size,output.ctypes.data_as(up),output.size,32,64),0)
        execute();np.testing.assert_array_equal(output,a+64)
        coords[:,:,0]+=.2;coords[:,:,1]+=.4;execute()
        np.testing.assert_array_equal(output[3:-3,3:-3],(a+68)[3:-3,3:-3])
