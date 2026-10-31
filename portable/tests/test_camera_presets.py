import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from recipe import Recipe
from conversion_service import compute_monochrome

class CameraPresetTests(unittest.TestCase):
    def test_identity_roundtrip_and_invalid_values(self):
        identity=dict(make='Test',model='Camera',serial='001234')
        self.assertEqual(Recipe.from_dict(Recipe(camera_identity=identity).to_dict()).camera_identity,identity)
        for value in (dict(identity,serial=1234),dict(identity,extra=True),dict(identity,model='')):
            with self.assertRaises(ValueError):Recipe.from_dict({'camera_identity':value})
    def compute(self,recipe):
        samples=np.full((16,16),1000,np.uint16)
        metadata=dict(sensor_layout='bayer',linear_reconstruction=False,cfa_codes_full_origin=[[0,1],[1,2]],cfa_libraw_channels_full_origin=[[0,1],[3,2]],black_level_by_libraw_channel=[64]*4,white_level=16383,white_level_by_libraw_channel=None,camera_whitebalance=[1]*4)
        structure=dict(Make='Test',Model='Camera',camera_identity=dict(make='Test',model='Camera',serial='current'),source_kind='RAW',active_area=[0,0,16,16],crop_origin=[0,0],crop_size=[16,16])
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'synthetic.RAW';source.write_bytes(b'synthetic fixture')
            with patch('conversion_service.decode_sensor',return_value=SimpleNamespace(samples=samples,metadata=metadata)),patch('conversion_service.source_structure',return_value=structure):
                return compute_monochrome(source,recipe)
    def test_regular_parameters_can_cross_camera_without_whitelist(self):
        params=self.compute(Recipe(camera_identity=dict(make='Other',model='Different',serial='old')))[2]
        self.assertFalse(params['preset_camera_matches']);self.assertEqual(params['camera_identity']['serial'],'current')
    def test_mismatched_body_defect_preset_is_rejected(self):
        profile=dict(version=1,make='Test',model='Camera',sensor_size=[16,16],pixels=[[4,5]])
        with self.assertRaisesRegex(ValueError,'另一相机或机身编号'):
            self.compute(Recipe(camera_identity=dict(make='Test',model='Camera',serial='other'),defect_profile=profile))
    def test_matching_body_defect_preset_remains_usable(self):
        profile=dict(version=1,make='Test',model='Camera',sensor_size=[16,16],pixels=[[4,5]])
        params=self.compute(Recipe(camera_identity=dict(make='Test',model='Camera',serial='current'),defect_profile=profile))[2]
        self.assertTrue(params['preset_camera_matches']);self.assertEqual(params['defect_repair']['repaired'],1)
