"""Exercise a built app's private backend using only a generated Bayer DNG."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import numpy as np
import rawpy
import tifffile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    args = parser.parse_args()
    resources = args.app.resolve() / 'Contents/Resources'
    with tempfile.TemporaryDirectory(prefix='tomono-public-smoke-') as directory:
        work = Path(directory)
        source, output = work / 'synthetic.dng', work / 'monochrome.dng'
        yy, xx = np.mgrid[:128, :128]
        plane = (2000 + 12 * xx + 5 * yy).astype(np.uint16)
        green = (yy + xx) % 2 == 1
        mosaic = plane.copy()
        mosaic[::2, ::2] = 1200
        mosaic[1::2, 1::2] = 7000
        tags = [(50706, 'B', 4, (1, 4, 0, 0), False),
                (50707, 'B', 4, (1, 1, 0, 0), False),
                (50708, 's', 0, 'toMONO Synthetic Camera', False),
                (271, 's', 0, 'toMONO Test', False),
                (272, 's', 0, 'Synthetic Camera', False),
                (33421, 'H', 2, (2, 2), False),
                (33422, 'B', 4, (0, 1, 1, 2), False),
                (50710, 'B', 3, (0, 1, 2), False),
                (50711, 'H', 1, 1, False),
                (50714, 'I', 1, 512, False),
                (50717, 'I', 1, 16383, False),
                (50721, '2i', 9, tuple(z for v in (1, 0, 0, 0, 1, 0, 0, 0, 1) for z in (v, 1)), False),
                (50728, '2I', 3, (1, 1, 1, 1, 1, 1), False),
                (50778, 'H', 1, 21, False),
                (50829, 'I', 4, (0, 0, 128, 128), False)]
        tifffile.imwrite(source, mosaic, photometric=32803, metadata=None, extratags=tags)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        env = dict(os.environ, PYTHONHOME=str(resources / 'python'),
                   PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1',
                   TOMONO_EXIFTOOL=str(resources / 'exiftool/exiftool'))
        env.pop('PYTHONPATH', None)
        process = subprocess.run([str(resources / 'python/bin/python3'), '-s',
                    str(resources / 'backend/tomono_cli.py'), str(source), '-o', str(output),
                    '--json', '--log', str(work / 'events.jsonl')],
                    cwd=resources / 'backend', env=env, capture_output=True, text=True)
        if process.returncode:
            raise RuntimeError(process.stdout + process.stderr)
        result = json.loads(process.stdout.strip().splitlines()[-1])
        assert result['dng_saved'], result
        with rawpy.imread(str(output)) as decoded:
            actual = decoded.raw_image.copy()
        assert actual.shape == plane.shape
        np.testing.assert_array_equal(actual[green], plane[green])
        assert hashlib.sha256(source.read_bytes()).hexdigest() == before
        with tifffile.TiffFile(output) as document:
            assert document.pages[0].tags['Software'].value == 'toMONO 1.1.0 (build 15)'
        print(json.dumps({'private_runtime_export': True, 'independent_libraw_readback': True,
                          'measured_green_exact': True, 'source_unchanged': True,
                          'shape': list(actual.shape), 'software': 'toMONO 1.1.0 (build 15)'}))


if __name__ == '__main__':
    main()
