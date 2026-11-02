"""Fast suggested loupe locations from original same-colour CFA observations.

This is a bounded structure heuristic, not an artifact detector, camera
calibration, or reconstruction algorithm. It does not read other CFA colours,
does not inspect a reconstruction's output, and never changes source samples.
The same RAW/settings-independent locations can therefore be kept while users
compare detail modes. Coordinates are native pixels relative to the oriented
default crop, matching the preview raster geometry.
"""
from __future__ import annotations

import numpy as np

_PATTERNS = {
    'RGGB': ((0, 1), (1, 2)), 'BGGR': ((2, 1), (1, 0)),
    'GRBG': ((1, 0), (2, 1)), 'GBRG': ((1, 2), (0, 1)),
}
_PATCH = 96
_GRID = 12
_POLICY = 'bounded_same_colour_structure_v1'


def _orient_rect(rect, width, height, orientation):
    x, y, w, h = rect
    if orientation == 2: return [width-x-w, y, w, h]
    if orientation == 3: return [width-x-w, height-y-h, w, h]
    if orientation == 4: return [x, height-y-h, w, h]
    if orientation == 5: return [y, x, h, w]
    if orientation == 6: return [height-y-h, x, h, w]
    if orientation == 7: return [height-y-h, width-x-w, h, w]
    if orientation == 8: return [y, width-x-w, h, w]
    return list(rect)


def _roi(cx, cy, width, height, size):
    w, h = min(size, width), min(size, height)
    return [min(max(0, int(cx)-w//2), width-w),
            min(max(0, int(cy)-h//2), height-h), w, h]


def _starts(first, stop, patch):
    # Full-origin even boundaries preserve the same 2x2 cell geometry even
    # when the default crop starts at an odd pixel.
    first += first % 2
    last = stop - patch
    last -= last % 2
    if last < first: return []
    # Overlap nearby windows; otherwise an edge exactly on a patch boundary
    # could be absent from every scored patch on modest-size photographs.
    count = min(_GRID, (last-first)//max(2, patch//2) + 1)
    return np.unique(np.rint(np.linspace(first, last, max(1, count))/2).astype(int)*2).tolist()


def _features(planes):
    proxy = np.mean(planes, axis=0)
    finite = np.isfinite(proxy)
    if not finite.all(): return None
    clipped = float(np.mean(proxy >= .995))
    dark = float(np.mean(proxy <= .005))
    lo, hi = np.percentile(proxy, (5, 95))
    contrast = float(hi-lo)
    phase = float(np.percentile(abs(planes[0]-planes[1]), 80)) if len(planes)==2 else 0.
    if hi < .015 or (contrast < .012 and phase < .024) or clipped > .6 or dark > .8:
        return None
    # Gentle spatial smoothing suppresses isolated sampling noise in the
    # structure score. No full-resolution image or image derivative is made.
    smooth = (proxy[:-2, :-2]+2*proxy[:-2, 1:-1]+proxy[:-2, 2:]
              +2*proxy[1:-1, :-2]+4*proxy[1:-1, 1:-1]+2*proxy[1:-1, 2:]
              +proxy[2:, :-2]+2*proxy[2:, 1:-1]+proxy[2:, 2:])/16
    gx = smooth[1:, 1:]-smooth[1:, :-1]
    gy = smooth[1:, 1:]-smooth[:-1, 1:]
    edge = float(np.percentile(np.hypot(gx, gy), 99))
    texture = float(np.percentile(abs(proxy[1:-1, 1:-1]-smooth), 80))
    # Two green phases can differ because of real texture, edges, noise or
    # sensor response. This term only suggests where to look, never a repair.
    fine = max(texture, phase*.25)
    score = (contrast*.35+edge*1.5+fine*.6)*(1-min(.75, clipped))
    if edge < .003 and fine < .004: return None
    reason = ('采样变化' if contrast < .012 and phase >= .024 else
              ('高反差边缘' if edge >= fine*1.4 else '细密纹理'))
    return dict(score=score, reason=reason, contrast=contrast,
                edge=edge, texture=fine, phase_difference=phase,
                clipped_fraction=clipped)


def inspection_regions(samples, pattern, blacks, whites, crop=None,
                       orientation=1, target=1, *, region_size=192, max_regions=3):
    """Return a small JSON-safe location report without altering the RAW.

    ``pattern``, ``blacks`` and ``whites`` are full-origin 2x2 arrays. ``crop``
    is an absolute sensor ``(x,y,width,height)`` rectangle. Only selected target
    phases are read/normalized; non-target samples and calibration entries may
    even contain NaNs. A maximum 12x12 grid of <=96x96 patches is examined.
    Flat, clipped and very dark patches do not get an artifact label: if no
    useful structure is found, an explicit ``画面中心`` location is returned.

    ``score`` is a ranking value, not an artifact probability. This helper has
    no dependency on the selected interpolation/detail mode.
    """
    a = np.asarray(samples)
    if a.ndim != 2 or min(a.shape) < 2 or not (np.issubdtype(a.dtype, np.integer) or np.issubdtype(a.dtype, np.floating)):
        raise ValueError('Inspection needs a numeric two-dimensional CFA >=2x2')
    if isinstance(pattern, str):
        try: pattern = _PATTERNS[pattern.upper()]
        except KeyError as exc: raise ValueError('Expected a 2x2 RGB Bayer CFA') from exc
    p = np.asarray(pattern)
    if p.shape != (2, 2) or tuple(p.ravel()) not in tuple(tuple(np.asarray(v).ravel()) for v in _PATTERNS.values()):
        raise ValueError('Expected a valid 2x2 RGB Bayer CFA')
    if isinstance(target, str): target = {'R':0, 'G':1, 'B':2}.get(target.upper(), -1)
    if isinstance(target, (bool, np.bool_)) or not isinstance(target, (int, np.integer)) or target not in (0, 1, 2):
        raise ValueError('Target must be R/G/B or 0/1/2')
    if type(orientation) is not int or orientation not in range(1, 9):
        raise ValueError('EXIF orientation must be 1..8')
    if type(region_size) is not int or not 8 <= region_size <= 512:
        raise ValueError('Inspection region size must be 8..512 pixels')
    if type(max_regions) is not int or not 1 <= max_regions <= 8:
        raise ValueError('Expected 1..8 suggested regions')
    h, w = a.shape
    crop = (0, 0, w, h) if crop is None else crop
    if (len(crop) != 4 or any(isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)) for v in crop)):
        raise ValueError('Crop must contain four integer pixel coordinates')
    x, y, cw, ch = map(int, crop)
    if min(x, y) < 0 or min(cw, ch) < 1 or x+cw > w or y+ch > h:
        raise ValueError('Inspection crop is outside the sensor')
    b, white = np.asarray(blacks), np.asarray(whites)
    if b.shape != (2, 2) or white.shape != (2, 2):
        raise ValueError('Per-phase black/white levels must be 2x2')
    phases = [tuple(map(int, phase)) for phase in np.argwhere(p==target)]
    for py, px in phases:
        if not np.isfinite(b[py, px]) or not np.isfinite(white[py, px]) or white[py, px] <= b[py, px]:
            raise ValueError('Selected target black/white levels are invalid')
    report = dict(version=1, selection_policy=_POLICY, source='original_cfa',
                  target_channel=('R','G','B')[int(target)],
                  native_size=[ch, cw] if orientation >= 5 else [cw, ch],
                  analyzed_patches=0, selected_samples=0, regions=[])
    # A full 2x2 cell must fit inside the default crop; tiny crops use centre.
    pw = min(_PATCH, max(0, (cw-1)//2*2))
    ph = min(_PATCH, max(0, (ch-1)//2*2))
    candidates = []
    if min(pw, ph) >= 8:
        for sy in _starts(y, y+ch, ph):
            for sx in _starts(x, x+cw, pw):
                report['analyzed_patches'] += 1
                planes = []
                for py, px in phases:
                    observed = a[sy+py:sy+ph:2, sx+px:sx+pw:2].astype(np.float64)
                    report['selected_samples'] += observed.size
                    planes.append((observed-float(b[py, px]))/float(white[py, px]-b[py, px]))
                features = _features(planes)
                if features is not None:
                    features['rect'] = _roi(sx-x+pw//2, sy-y+ph//2, cw, ch, region_size)
                    candidates.append(features)
    # Stable sort and deterministic spatial separation prevent all suggestions
    # from pointing at neighbouring windows of one large edge.
    candidates.sort(key=lambda v: (-v['score'], v['rect'][1], v['rect'][0]))
    chosen = []
    for candidate in candidates:
        rect = candidate['rect'];cx, cy = rect[0]+rect[2]/2, rect[1]+rect[3]/2
        if any(np.hypot(cx-(v['rect'][0]+v['rect'][2]/2), cy-(v['rect'][1]+v['rect'][3]/2)) < region_size*1.5 for v in chosen):
            continue
        chosen.append(candidate)
        if len(chosen) == max_regions: break
    if not chosen:
        chosen = [dict(rect=_roi(cw//2, ch//2, cw, ch, region_size), reason='画面中心', score=0.)]
    for v in chosen:
        v['rect'] = _orient_rect(v['rect'], cw, ch, orientation)
        # Round diagnostics only, never coordinates or the original samples.
        report['regions'].append({k: round(float(value), 6) if isinstance(value, (float, np.floating)) else value for k, value in v.items()})
    return report
