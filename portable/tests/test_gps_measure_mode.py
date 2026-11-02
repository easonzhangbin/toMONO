"""Undefined GPS measurement modes must not prevent otherwise valid DNG export."""
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import tifffile

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dng_writer import write_dng
from recipe import Recipe
from dng_reader import read_linear_output


@unittest.skipUnless(shutil.which('exiftool'),'ExifTool required for metadata integration check')
class GPSMeasureMode(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.pixels=np.arange(256,dtype=np.uint16).reshape(16,16)+512
        self.structure=dict(Make='Test',Model='GPS',UniqueCameraModel='GPS',Orientation=1,
            crop_origin=[0,0],crop_size=[16,16],active_area=[0,0,16,16],safe_render_tags=[],
            lens_metadata={'aperture':2.8,'focal':50})

    def source(self,mode,status='A'):
        path=self.root/f'source_{mode}_{status}.tif'
        tifffile.imwrite(path,self.pixels,metadata=None)
        tags=['-GPSLatitude=12.5','-GPSLatitudeRef=N','-GPSLongitude=45.25','-GPSLongitudeRef=E',
              f'-GPSStatus={status}','-ExposureTime=0.008','-ISO=400','-FNumber=2.8','-FocalLength=50',
              '-DateTimeOriginal=2020:01:02 03:04:05','-LensModel=Test Lens','-Artist=Test Author']
        if mode is not None:tags.append(f'-GPSMeasureMode={mode}')
        subprocess.run(['exiftool','-overwrite_original','-n',*tags,str(path)],check=True,capture_output=True)
        return path

    def read_tags(self,path):
        return json.loads(subprocess.check_output(['exiftool','-j','-n','-GPS:all','-ExposureTime','-ISO',
            '-FNumber','-FocalLength','-DateTimeOriginal','-LensModel','-Artist',str(path)]))[0]

    def test_only_undefined_measurement_mode_is_omitted(self):
        for mode in ('0','1','2','3',None):
            with self.subTest(mode=mode):
                source=self.source(mode);output=self.root/f'out_{mode}.dng'
                before=hashlib.sha256(source.read_bytes()).hexdigest()
                result=write_dng(source,output,self.pixels,512,16383,self.structure,Recipe())
                self.assertEqual(result['metadata_validation']['Validate'],'OK')
                np.testing.assert_array_equal(read_linear_output(output),self.pixels)
                tags=self.read_tags(output)
                for field,value in [('GPSLatitude',12.5),('GPSLongitude',45.25),('ExposureTime',.008),
                                    ('FNumber',2.8),('FocalLength',50),('ISO',400)]:
                    self.assertAlmostEqual(tags[field],value)
                self.assertEqual(tags['DateTimeOriginal'],'2020:01:02 03:04:05')
                self.assertEqual(tags['LensModel'],'Test Lens')
                self.assertEqual(tags['Artist'],'Test Author')
                self.assertEqual(tags['GPSStatus'],'A')
                if mode in ('0','1'):
                    self.assertNotIn('GPSMeasureMode',tags)
                    self.assertEqual(result['omitted_undefined_capture_fields'],['GPS:GPSMeasureMode'])
                else:
                    self.assertEqual(str(tags.get('GPSMeasureMode')) if mode is not None else tags.get('GPSMeasureMode'),mode)
                    self.assertEqual(result['omitted_undefined_capture_fields'],[])
                self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),before)

    def test_capture_metadata_opt_out_still_omits_gps_and_capture_fields(self):
        source=self.source('0');output=self.root/'private.dng'
        result=write_dng(source,output,self.pixels,512,16383,self.structure,Recipe(preserve_capture=False))
        self.assertEqual(result['metadata_validation']['Validate'],'OK')
        tags=self.read_tags(output)
        self.assertNotIn('GPSMeasureMode',tags)
        self.assertNotIn('GPSLatitude',tags)
        self.assertNotIn('ExposureTime',tags)
        self.assertEqual(tags['Artist'],'Test Author')
        self.assertEqual(result['omitted_undefined_capture_fields'],[])
        np.testing.assert_array_equal(read_linear_output(output),self.pixels)

    def test_unrelated_minor_warning_is_still_rejected(self):
        source=self.source('3',status='X');output=self.root/'invalid.dng'
        with self.assertRaisesRegex(RuntimeError,'GPSStatus'):
            write_dng(source,output,self.pixels,512,16383,self.structure,Recipe())


if __name__=='__main__':unittest.main()
