import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from dng_writer import make_preview,make_detail_preview,make_histogram,orient_preview

class PreviewTests(unittest.TestCase):
    def test_histogram_counts_native_crop_and_display_values_without_changing_raw(self):
        image=np.array([[0,0,0,0,0,0],[0,10,20,60,110,0],[0,5,30,90,130,0],[0,0,0,0,0,0]],dtype=np.uint16)
        original=image.copy();structure={'active_area':[0,0,4,6],'crop_origin':[1,1],'crop_size':[4,2]}
        for gamma in (1.8,2.2):
            h=make_histogram(image,10,110,structure,gamma)
            self.assertEqual(h['sample_count'],8);self.assertEqual(sum(h['linear_bins']),8);self.assertEqual(sum(h['display_bins']),8)
            self.assertEqual(h['black_clipped'],2);self.assertEqual(h['white_clipped'],2)
            expected=np.bincount(make_detail_preview(image,10,110,structure,gamma).ravel(),minlength=256)
            np.testing.assert_array_equal(h['display_bins'],expected)
        np.testing.assert_array_equal(original,image)
    def test_histogram_checks_cancellation_between_strips(self):
        def cancel():raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):make_histogram(np.zeros((300,8),np.uint16),0,100,{'active_area':[0,0,300,8],'crop_origin':[0,0],'crop_size':[8,300]},2.2,cancel)
    def test_crop_grayscale_and_gamma_do_not_change_raw(self):
        pixels=np.arange(96,dtype=np.uint16).reshape(8,12);before=pixels.copy()
        structure={'active_area':[0,0,8,12],'crop_origin':[2,1],'crop_size':[6,4]}
        a=make_preview(pixels,0,100,structure,2.2)
        b=make_preview(pixels,0,100,structure,1.8)
        self.assertEqual(a.shape,(4,6,3));self.assertEqual(a.dtype,np.uint8)
        np.testing.assert_array_equal(a[:,:,0],a[:,:,1]);np.testing.assert_array_equal(a[:,:,1],a[:,:,2])
        self.assertFalse(np.array_equal(a,b));np.testing.assert_array_equal(pixels,before)
        self.assertLess(a[0,0,0],a[-1,-1,0])
    def test_all_exif_orientations_place_known_samples_correctly(self):
        image=np.repeat(np.array([[1,2,3],[4,5,6]],dtype=np.uint8)[:,:,None],3,axis=2)
        expected={1:[[1,2,3],[4,5,6]],2:[[3,2,1],[6,5,4]],3:[[6,5,4],[3,2,1]],
          4:[[4,5,6],[1,2,3]],5:[[1,4],[2,5],[3,6]],6:[[4,1],[5,2],[6,3]],
          7:[[6,3],[5,2],[4,1]],8:[[3,6],[2,5],[1,4]]}
        for code,values in expected.items():
            with self.subTest(orientation=code):np.testing.assert_array_equal(orient_preview(image,code)[:,:,0],values)
