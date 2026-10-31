"""Regression for RAWs from manual lenses with undefined EXIF lens values."""
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
import numpy as np
import tifffile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dng_writer import write_dng
from recipe import Recipe
from dng_reader import read_linear_output

@unittest.skipUnless(shutil.which('exiftool'),'ExifTool required for metadata integration check')
class UndefinedCaptureFields(unittest.TestCase):
    def test_unknown_manual_lens_values_are_omitted_without_changing_pixels(self):
        pixels=np.arange(256,dtype=np.uint16).reshape(16,16)+512
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for aperture,focal in ((0,0),(2.8,70)):
                with self.subTest(aperture=aperture,focal=focal):
                    source=root/f'source_{aperture}.tif';output=root/f'out_{aperture}.dng'
                    tifffile.imwrite(source,pixels,metadata=None)
                    subprocess.run(['exiftool','-overwrite_original',f'-FNumber={aperture}',f'-FocalLength={focal}',str(source)],check=True,capture_output=True)
                    structure=dict(Make='Test',Model='Manual lens',UniqueCameraModel='Manual lens',Orientation=1,
                        crop_origin=[0,0],crop_size=[16,16],active_area=[0,0,16,16],safe_render_tags=[],
                        lens_metadata={'aperture':aperture,'focal':focal})
                    result=write_dng(source,output,pixels,512,16383,structure,Recipe())
                    self.assertEqual(result['metadata_validation']['Validate'],'OK')
                    np.testing.assert_array_equal(read_linear_output(output),pixels)
                    tags=json.loads(subprocess.check_output(['exiftool','-j','-n','-FNumber','-FocalLength',str(output)]))[0]
                    if aperture==0:
                        self.assertNotIn('FNumber',tags);self.assertNotIn('FocalLength',tags)
                        self.assertEqual(set(result['omitted_undefined_capture_fields']),{'ExifIFD:FNumber','ExifIFD:FocalLength'})
                    else:
                        self.assertAlmostEqual(tags['FNumber'],aperture);self.assertAlmostEqual(tags['FocalLength'],focal)
                        self.assertEqual(result['omitted_undefined_capture_fields'],[])

if __name__=='__main__':unittest.main()
