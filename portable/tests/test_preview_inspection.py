"""Suggested inspection geometry and strict source independence constraints."""
import json
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from preview_inspection import inspection_regions, _orient_rect
from dng_writer import orient_preview


PATTERNS = ['RGGB', 'BGGR', 'GRBG', 'GBRG']
P = {'RGGB':[[0,1],[1,2]],'BGGR':[[2,1],[1,0]],'GRBG':[[1,0],[2,1]],'GBRG':[[1,2],[0,1]]}


class PreviewInspectionTests(unittest.TestCase):
    def test_oriented_rect_matches_independent_raster_all_eight(self):
        for h,w in [(23,31),(24,30)]:
            a=np.zeros((h,w),np.uint8);rect=[3,5,11,7];x,y,rw,rh=rect;a[y:y+rh,x:x+rw]=1
            for orientation in range(1,9):
                yy,xx=np.nonzero(orient_preview(a,orientation))
                expected=[int(xx.min()),int(yy.min()),int(xx.max()-xx.min()+1),int(yy.max()-yy.min()+1)]
                self.assertEqual(_orient_rect(rect,w,h,orientation),expected)

    def test_other_colours_cannot_change_selection_or_require_valid_calibration(self):
        rng=np.random.default_rng(110112);a=rng.uniform(.05,.85,(193,297))
        yy,xx=np.indices(a.shape)
        for pname in PATTERNS:
            p=np.array(P[pname]);
            for target in range(3):
                measured=p[yy%2,xx%2]==target;other=a.copy();other[~measured]=np.nan
                b=np.zeros((2,2));white=np.ones((2,2));poison_b=b.copy();poison_w=white.copy();poison_b[p!=target]=np.nan;poison_w[p!=target]=np.nan
                args=dict(crop=(5,7,281,179),orientation=6,target=target)
                expected=inspection_regions(a,p,b,white,**args)
                actual=inspection_regions(other,p,poison_b,poison_w,**args)
                self.assertEqual(actual,expected)
                self.assertTrue(np.isnan(other[~measured]).all())

    def test_normalized_constant_phases_return_explicit_centre(self):
        p=np.array(P['RGGB']);b=np.array([[5,11],[22,33]],float);white=b+np.array([[100,200],[300,400]],float)
        a=np.empty((203,307),float)
        for py in range(2):
            for px in range(2):a[py::2,px::2]=b[py,px]+.2*(white[py,px]-b[py,px])
        before=a.copy();a.flags.writeable=False
        for orientation in range(1,9):
            result=inspection_regions(a,p,b,white,crop=(5,7,281,179),orientation=orientation)
            self.assertEqual(result['regions'][0]['reason'],'画面中心')
            self.assertEqual(result['regions'][0]['score'],0)
            self.assertEqual(result['native_size'],[179,281] if orientation>=5 else [281,179])
            np.testing.assert_array_equal(a,before)

    def test_high_contrast_regions_avoid_flat_dark_noise_and_saturation(self):
        rng=np.random.default_rng(12);a=np.full((768,768),.2)
        a[:220,:220]=rng.uniform(0,.002,(220,220));a[:220,500:]=1.
        a[500:,:]=np.where(np.arange(768)[None,:]<384,.08,.8)
        result=inspection_regions(a,'RGGB',np.zeros((2,2)),np.ones((2,2)))
        # An edge bordering a partly saturated area is also a useful place to
        # inspect, so it need not rank below the completely unsaturated edge.
        # The flat saturated/noisy interiors themselves must not be proposed.
        self.assertTrue(any(v['rect'][1]+v['rect'][3]/2>450 and abs(v['rect'][0]+v['rect'][2]/2-384)<192 for v in result['regions']))
        for v in result['regions']:
            x,y,w,h=v['rect'];cx,cy=x+w/2,y+h/2
            self.assertFalse(cx<172 and cy<172)
            self.assertFalse(cx>548 and cy<172)
            self.assertEqual(v['reason'],'高反差边缘')

    def test_green_phase_difference_is_a_suggestion_not_a_repair(self):
        a=np.full((257,399),.2)
        a[1::2,::2]=.28
        before=a.copy()
        result=inspection_regions(a,'RGGB',np.zeros((2,2)),np.ones((2,2)))
        self.assertEqual(result['regions'][0]['reason'],'采样变化')
        self.assertGreater(result['regions'][0]['phase_difference'],.07)
        np.testing.assert_array_equal(a,before)

    def test_bounded_sampling_deterministic_json_and_disjoint_rectangles(self):
        # Broadcast view represents a large sensor without allocating a frame.
        row=np.where((np.arange(12000)//73)%2,.15,.8)[None,:]
        a=np.broadcast_to(row,(8000,12000));before=row.copy()
        result=inspection_regions(a,'GRBG',np.zeros((2,2)),np.ones((2,2)),crop=(11,13,11971,7973))
        self.assertLessEqual(result['analyzed_patches'],144)
        self.assertLessEqual(result['selected_samples'],2_000_000)
        self.assertEqual(result,inspection_regions(a,'GRBG',np.zeros((2,2)),np.ones((2,2)),crop=(11,13,11971,7973)))
        self.assertEqual(json.loads(json.dumps(result)),result)
        np.testing.assert_array_equal(row,before)
        self.assertLessEqual(len(result['regions']),3)
        for v in result['regions']:
            x,y,w,h=v['rect'];self.assertTrue(0<=x<=11971-w and 0<=y<=7973-h)
            self.assertLessEqual(max(w,h),192)

    def test_odd_crop_geometry_and_tiny_fallback(self):
        a=np.full((21,31),.5)
        for crop in [(5,7,17,11),(3,5,1,1),(1,1,2,3)]:
            for orientation in range(1,9):
                r=inspection_regions(a,'BGGR',np.zeros((2,2)),np.ones((2,2)),crop=crop,orientation=orientation)
                width,height=r['native_size'];x,y,w,h=r['regions'][0]['rect']
                self.assertTrue(0<=x<=width-w and 0<=y<=height-h)
                self.assertEqual(r['regions'][0]['reason'],'画面中心')

    def test_invalid_inputs_are_rejected(self):
        a=np.ones((20,30));b=np.zeros((2,2));w=np.ones((2,2))
        for args in [dict(crop=(-1,0,10,10)),dict(crop=(0,0,31,10)),dict(crop=(0,0,5.5,5)),dict(orientation=9),dict(target=True),dict(region_size=0),dict(max_regions=0)]:
            with self.assertRaises(ValueError):inspection_regions(a,'RGGB',b,w,**args)


if __name__=='__main__':unittest.main()
