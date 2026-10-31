import io,sys,tempfile,unittest,xml.etree.ElementTree as ET
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np,tifffile
from PIL import Image,ImageCms
from recipe import Recipe
from display_render import preview_icc,encode_preview_png,adobe_reference_xmp,reference_points,output_camera_model
from dng_writer import write_dng

class ColorManagedPreviewTests(unittest.TestCase):
    def test_overview_and_detail_decode_to_the_same_display_gray(self):
        gray=np.tile(np.arange(256,dtype=np.uint8),(4,1))
        rgb=np.repeat(gray[:,:,None],3,axis=2)
        converted=[]
        for image in (gray,rgb):
            decoded=Image.open(io.BytesIO(encode_preview_png(image)))
            profile=ImageCms.ImageCmsProfile(io.BytesIO(decoded.info['icc_profile']))
            converted.append(np.asarray(ImageCms.profileToProfile(decoded,profile,ImageCms.createProfile('sRGB'),outputMode='RGB')))
        self.assertLessEqual(np.abs(converted[0].astype(int)-converted[1]).max(),1)

    def test_curve_is_valid_monotone_and_gamma_changes_only_the_appearance(self):
        self.assertTrue(Recipe.from_dict({}).match_preview)
        with self.assertRaises(ValueError):Recipe.from_dict({'match_preview':1})
        for gamma in (1,1.8,2.2,3):
            points=reference_points(gamma)
            self.assertEqual(len(points),16);self.assertEqual(points[0],(0,0));self.assertEqual(points[-1],(255,255))
            self.assertTrue(all(b[0]>a[0] and b[1]>=a[1] for a,b in zip(points,points[1:])))
            root=ET.fromstring(adobe_reference_xmp(gamma))
            items=root.findall('.//{http://ns.adobe.com/camera-raw-settings/1.0/}ToneCurvePV2012/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Seq/{http://www.w3.org/1999/02/22-rdf-syntax-ns#}li')
            self.assertEqual(len(items),16)
        self.assertNotEqual(reference_points(1.8),reference_points(2.2))

class ReferenceDNGTests(unittest.TestCase):
    def test_derived_model_suffix_and_long_names_preserve_source_name(self):
        self.assertEqual(output_camera_model('ILCE-7CR'),'ILCE-7CR MONOCHROME')
        long='Camera With A Very Long Model Description'
        self.assertEqual(output_camera_model(long),long+' toMONO')
        self.assertEqual(output_camera_model('Camera MONOCHROME'),'Camera MONOCHROME')

    def test_matching_is_reversible_metadata_and_never_changes_linear_samples(self):
        pixels=np.arange(512,dtype=np.uint16).reshape(16,32)*127
        before=pixels.copy()
        structure={'Make':'toMONO','Model':'Test','UniqueCameraModel':'toMONO Test','Orientation':1,
            'active_area':[0,0,16,32],'crop_origin':[0,0],'crop_size':[32,16],
            'safe_render_tags':[(50730,10,1,(1,2),False)]}
        with tempfile.TemporaryDirectory() as d:
            source=Path(d)/'original.dng';source.write_bytes(b'original remains untouched')
            digests=[]
            for enabled in (True,False):
                output=Path(d)/f'{enabled}.dng'
                result=write_dng(source,output,pixels,0,65535,structure,Recipe(match_preview=enabled,preserve_capture=False,preserve_description=False))
                self.assertEqual(result['metadata_validation']['Validate'],'OK')
                digests.append(result['raw_md5'])
                with tifffile.TiffFile(output) as t:
                    np.testing.assert_array_equal(t.pages[0].pages[0].asarray(),before)
                    packet=ET.fromstring(t.pages[0].tags[700].value)
                    description=packet.find('.//{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description')
                    self.assertEqual(description.get('{http://ns.adobe.com/camera-raw-settings/1.0/}HasSettings')=='True',enabled)
                    self.assertEqual(description.get('{urn:tomono:metadata:1.0}SourceModel'),'Test')
                    self.assertEqual(t.pages[0].tags['Model'].value,'Test MONOCHROME')
                    self.assertEqual(t.pages[0].tags['UniqueCameraModel'].value,'toMONO Test MONOCHROME')
                    self.assertEqual(t.pages[0].tags[50730].value,(0,1) if enabled else (1,2))
                    self.assertEqual(t.pages[0].tags[34675].value,preview_icc(rgb=True))
            self.assertEqual(digests[0],digests[1])
            self.assertEqual(source.read_bytes(),b'original remains untouched')
        np.testing.assert_array_equal(pixels,before)
