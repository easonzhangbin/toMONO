"""Numerical anti-aliasing, geometry and RAW-integrity preview constraints."""
import hashlib
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dng_writer import make_preview,make_detail_preview,orient_preview


def structure(shape,origin=(0,0),size=None,orientation=1,active=(0,0)):
    h,w=shape
    return dict(active_area=[active[1],active[0],h,w],crop_origin=list(origin),
                crop_size=list(size or (w,h)),Orientation=orientation)


def brute_area(image,height,width):
    """Independent slow pixel-cell overlap integration for small test images."""
    h,w=image.shape;result=np.zeros((height,width),np.float64)
    for oy in range(height):
        y0=oy*h/height;y1=(oy+1)*h/height
        for ox in range(width):
            x0=ox*w/width;x1=(ox+1)*w/width
            for y in range(int(np.floor(y0)),int(np.ceil(y1))):
                for x in range(int(np.floor(x0)),int(np.ceil(x1))):
                    result[oy,ox]+=image[y,x]*max(0,min(y+1,y1)-max(y,y0))*max(0,min(x+1,x1)-max(x,x0))
            result[oy,ox]/=(y1-y0)*(x1-x0)
    return result


def display(image,black,white,gamma):
    return (np.clip((image.astype(np.float32)-black)/(white-black),0,1)**(1/gamma)*255).astype(np.uint8)


class PreviewAreaTests(unittest.TestCase):
    def test_two_by_two_phase_pattern_is_averaged_before_gamma_at_all_crop_parities(self):
        image=np.tile(np.array([[0,1000],[2000,3000]],np.uint16),(34,36))
        image.flags.writeable=False
        for x in (0,1):
            for y in (0,1):
                s=structure(image.shape,(x,y),(64,64))
                for gamma in (1,1.8,2.2):
                    result=make_preview(image,0,3000,s,gamma,16)
                    expected=int(display(np.array([[1500.]]),0,3000,gamma)[0,0])
                    self.assertEqual(result.shape,(16,16,3))
                    self.assertTrue(np.all(result==expected))
        # Gamma-domain averaging would instead encode the four phases first.
        encoded_mean=float(display(np.array([[0,1000],[2000,3000]]),0,3000,2.2).mean())
        self.assertGreater(abs(expected-encoded_mean),10)

    def test_fractional_area_matches_independent_overlap_reference_and_mean(self):
        image=np.random.default_rng(763).integers(0,65536,(11,17),dtype=np.uint16)
        result=make_preview(image,0,65535,structure(image.shape),1,7)
        expected_linear=brute_area(image,5,7)
        np.testing.assert_array_equal(result[:,:,0],display(expected_linear,0,65535,1))
        # Quantized display can lose less than one code; its mean must still
        # represent the complete crop rather than a subset of sensor phases.
        self.assertLess(abs(float(result[:,:,0].mean())-float(image.mean())/65535*255),1)
        self.assertAlmostEqual(float(expected_linear.mean()),float(image.mean()),places=8)

    def test_crop_origin_active_offset_edge_cells_and_noncontiguous_source(self):
        image=np.full((28,60),65000,np.uint16)[:,::2]
        image[5:18,7:26]=np.arange(13*19,dtype=np.uint16).reshape(13,19)*257
        before=hashlib.sha256(image.tobytes()).hexdigest()
        s=structure(image.shape,(4,3),(19,13),active=(3,2))
        result=make_preview(image,0,65535,s,2.2,7)
        expected=display(brute_area(image[5:18,7:26],5,7),0,65535,2.2)
        np.testing.assert_array_equal(result[:,:,0],expected)
        self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(),before)

    def test_constant_native_resolution_and_crop_width_do_not_use_sensor_width(self):
        image=np.full((44,1000),12345,np.uint16)
        s=structure(image.shape,(11,7),(30,20))
        for gamma in (1.8,2.2):
            result=make_preview(image,512,16383,s,gamma,40)
            self.assertEqual(result.shape,(20,30,3))
            np.testing.assert_array_equal(result[:,:,0],make_detail_preview(image,512,16383,s,gamma))
            small=make_preview(image,512,16383,s,gamma,7)
            self.assertTrue(np.all(small==result[0,0,0]))

    def test_vertical_integrals_cross_row_strips_at_exact_and_fractional_edges(self):
        rng=np.random.default_rng(901)
        for h,w,width in ((256,24,12),(513,21,9)):
            image=rng.integers(0,65536,(h,w),dtype=np.uint16)
            result=make_preview(image,0,65535,structure(image.shape),1,width)
            expected=display(brute_area(image,result.shape[0],width),0,65535,1)
            np.testing.assert_array_equal(result[:,:,0],expected)

    def test_display_width_and_unrotated_return_for_all_transposed_orientations(self):
        image=np.arange(30*16,dtype=np.uint16).reshape(30,16)*100
        for orientation in range(1,9):
            s=structure(image.shape,(3,5),(9,21),orientation)
            result=make_preview(image,0,65535,s,2.2,7)
            visible=orient_preview(result,orientation)
            self.assertEqual(visible.shape[1],7)
            if orientation in (5,6,7,8):
                self.assertEqual(result.shape,(7,3,3))
                expected=display(brute_area(image[5:26,3:12],7,3),0,65535,2.2)
            else:
                self.assertEqual(result.shape,(16,7,3))
                expected=display(brute_area(image[5:26,3:12],16,7),0,65535,2.2)
            np.testing.assert_array_equal(result[:,:,0],expected)
            native=make_preview(image,0,65535,s,2.2,100)
            np.testing.assert_array_equal(orient_preview(native,orientation)[:,:,0],
                                          orient_preview(make_detail_preview(image,0,65535,s,2.2),orientation))

    def test_average_precedes_black_clipping_and_invalid_sizes_are_rejected(self):
        image=np.tile(np.array([[0,200],[0,200]],np.uint16),(2,2))
        self.assertTrue(np.all(make_preview(image,100,200,structure(image.shape),2.2,1)==0))
        for width in (0,-1,True,2.5):
            with self.assertRaises(ValueError):make_preview(image,0,200,structure(image.shape),2.2,width)
        with self.assertRaises(ValueError):make_preview(image,0,200,structure(image.shape,(3,0),(4,4)),2.2,1)


if __name__=='__main__':unittest.main()
