"""Integration checks on actual supplied samples; invoke from portable/."""
import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import rawpy
from raw_input import decode_sensor
from dng_reader import read_linear_output

SAMPLES = Path(os.environ['TOMONO_SAMPLE_DIR']) if os.environ.get('TOMONO_SAMPLE_DIR') else None


@unittest.skipUnless(SAMPLES and (SAMPLES / 'L1009263.DNG').exists(), 'Set TOMONO_SAMPLE_DIR for private M11 integration samples')
class SampleDecodeTests(unittest.TestCase):
    def test_full_sensor_coordinates_and_unprocessed_values(self):
        frame = decode_sensor(SAMPLES / 'L1009263.DNG')
        self.assertEqual(frame.samples.shape, (6336, 9536))
        self.assertEqual(frame.samples.dtype, np.dtype('uint16'))
        self.assertEqual(frame.metadata['white_level'], 16383)
        self.assertEqual(frame.metadata['black_level_by_libraw_channel'], [1023]*4)
        with rawpy.imread(str(SAMPLES / 'L1009263.DNG')) as raw:
            for y, x in ((0, 0), (1, 1), (100, 101), (6335, 9535)):
                self.assertEqual(frame.samples[y, x], raw.raw_value(y, x))
                code = frame.metadata['cfa_codes_full_origin'][y % 2][x % 2]
                self.assertEqual('RGB'[code], raw.color_desc[raw.raw_color(y, x):raw.raw_color(y, x)+1].decode())

    def test_raw_subifd_selected_instead_of_rgb_preview(self):
        output = read_linear_output(SAMPLES / 'L1009263r.dng')
        self.assertEqual(output.shape, (6336, 9536))
        self.assertEqual(output.dtype, np.dtype('uint16'))
        source = decode_sensor(SAMPLES / 'L1009263.DNG').samples
        # Independent sampled observation, not a promise for every setting/file.
        np.testing.assert_array_equal(source[3000:3100:2, 4000:4100:2], output[3000:3100:2, 4000:4100:2])


if __name__ == '__main__':
    unittest.main()
