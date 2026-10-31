"""Tests for real tag interpretation and supported-branch rejection."""
import os,sys,unittest,tempfile
from pathlib import Path
import numpy as np,tifffile
PORT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(PORT))
from metadata_params import parameters_from_dng,camera_white
SOURCE=Path(os.environ['TOMONO_SAMPLE_DIR'])/'L1009696.DNG' if os.environ.get('TOMONO_SAMPLE_DIR') else None
class MetadataTests(unittest.TestCase):
    @unittest.skipUnless(SOURCE and SOURCE.exists(),'Set TOMONO_SAMPLE_DIR for private metadata sample')
    def test_captured_parameters_computed_from_source_tags(self):
        p=parameters_from_dng(SOURCE)
        self.assertEqual(p['camera_white'],[0.257286012172699,1.0,0.675462007522583])
        self.assertEqual(p['green_compensation'],1.2309999465942383)
    def test_invalid_neutral_rejected(self):
        for neutral in ([0,1,1],[float('nan'),1,1],[-1,1,1]):
            with self.assertRaises(ValueError):camera_white(neutral,[np.eye(3)],[5000])
    def test_non_identity_camera_calibration_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'unsupported.dng'
            tifffile.imwrite(file,np.zeros((8,8),dtype=np.uint16),photometric=32803,metadata=None,
                extratags=[(50708,'s',0,'LEICA M11',False),(33422,'B',4,(0,1,1,2),False),(50723,'2i',9,tuple(x for v in (2,0,0,0,1,0,0,0,1) for x in (v,1)),False)])
            with self.assertRaisesRegex(ValueError,'非单位'):parameters_from_dng(file)
if __name__=='__main__':unittest.main()
