"""Experimental IPOL Zhang-Wu directional LMMSE for ordinary Bayer photos.

Reference: Lei Zhang and Xiaolin Wu, IEEE TIP 2005, doi:10.1109/TIP.2005.857260;
Pascal Getreuer, IPOL 2011, doi:10.5201/ipol.2011.g_zwld, official v1.1 code.
Vendor C files retain BSD-2-Clause notices. UseZhangCodeEst=0 and the original
normalized epsilon are fixed. LMMSE reads all CFA colours, so it is not a strict
independent narrowband channel method. Missing sites match the official code;
measured sites are explicitly restored before one final response quantization.
"""
from __future__ import annotations
import ctypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
import detail_reconstruction as _detail
HERE=Path(__file__).resolve().parent
METHODS=('lmmse',)
LMMSE_HALO=16
LMMSE_DIV_EPSILON=float(np.float32(.1)/np.float32(255*255))
TILE_SIZE=512
MAX_WORKERS=4
_LIB=None
_PATTERNS={'RGGB':((0,1),(1,2)),'BGGR':((2,1),(1,0)), 'GRBG':((1,0),(2,1)),'GBRG':((1,2),(0,1))}

def _pattern(pattern):
    if isinstance(pattern, str):
        try:
            return np.asarray(_PATTERNS[pattern.upper()], np.uint8)
        except KeyError as exc:
            raise ValueError('需要有效的 2×2 Bayer 排列') from exc
    p = np.asarray(pattern)
    if p.shape != (2, 2) or tuple(p.ravel()) not in tuple((tuple(np.asarray(v).ravel()) for v in _PATTERNS.values())):
        raise ValueError('需要有效的 2×2 Bayer 排列')
    return p.astype(np.uint8)

def _library():
    global _LIB
    if _LIB is None:
        lib = ctypes.CDLL(str(HERE / 'build/native-macos/libtomono_lmmse.dylib'))
        lib.tomono_lmmse_version.restype = ctypes.c_uint
        if lib.tomono_lmmse_version() != 256:
            raise RuntimeError('LMMSE 核心版本不匹配，请重新构建')
        ptr = ctypes.POINTER(ctypes.c_float)
        lib.tomono_lmmse_rgb.argtypes = [ptr, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ptr]
        lib.tomono_lmmse_rgb.restype = ctypes.c_int
        _LIB = lib
    return _LIB

def _validate_cfa(samples, pattern):
    a = np.asarray(samples)
    p = _pattern(pattern)
    if a.ndim != 2 or min(a.shape) < 8 or (not np.issubdtype(a.dtype, np.floating)):
        raise ValueError('LMMSE 需要至少 8×8 的浮点 CFA 采样')
    if not np.isfinite(a).all() or np.max(np.abs(a)) > 1000000.0:
        raise ValueError('LMMSE 使用所有颜色采样，采样数值必须有限')
    return (a, p)

def _restore_rgb(rgb, samples, p):
    for py in range(2):
        for px in range(2):
            rgb[py::2, px::2, p[py, px]] = samples[py::2, px::2]
    return rgb

def reconstruct_rgb(normalized_cfa, pattern):
    """Return HxWx3 float32 RGB, article-faithful except measured restoration.

    Negative/above-white finite observations are accepted without clipping.
    Four Bayer phases and odd shapes retain the official boundary treatment:
    whole-sample symmetric convolutions, truncated local-statistic sums with
    the vendor's fixed denominators, and symmetric colour-difference averages.
    The caller's data is never mutated. This is a whole-image reference call.
    """
    a, p = _validate_cfa(normalized_cfa, pattern)
    source = np.ascontiguousarray(a, np.float32)
    h, w = source.shape
    planar = np.empty((3, h, w), np.float32)
    ry, rx = map(int, np.argwhere(p == 0)[0])
    ptr = ctypes.POINTER(ctypes.c_float)
    code = _library().tomono_lmmse_rgb(source.ctypes.data_as(ptr), h, w, ry, rx, planar.ctypes.data_as(ptr))
    if code:
        raise RuntimeError('LMMSE 重建失败：' + str(code))
    rgb = np.ascontiguousarray(planar.transpose(1, 2, 0))
    return _restore_rgb(rgb, source, p)

def _execution(tile_size, workers):
    if type(tile_size) is not int or tile_size < 8 or tile_size % 2:
        raise ValueError('tile_size must be an even integer >=8')
    if type(workers) is not int or not 1 <= workers <= MAX_WORKERS:
        raise ValueError('workers must be 1..4')

def _tiles(shape, tile_size, halo):
    h, w = shape
    for y in range(0, h, tile_size):
        for x in range(0, w, tile_size):
            sy, sx = (min(tile_size, h - y), min(tile_size, w - x))
            y0, y1 = (max(0, y - halo), min(h, y + sy + halo))
            x0, x1 = (max(0, x - halo), min(w, x + sx + halo))
            yield (y, x, sy, sx, y0, y1, x0, x1)

def _local_pattern(p, y0, x0):
    return p[(np.arange(2) + y0)[:, None] % 2, (np.arange(2) + x0)[None, :] % 2]

def _bounded_results(function, tasks, workers):
    """At most four live tasks; do not enqueue the full frame's tile copies."""
    if workers == 1:
        for task in tasks:
            yield function(task)
        return
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = []
        for task in tasks:
            pending.append(pool.submit(function, task))
            if len(pending) == workers:
                yield pending.pop(0).result()
        for future in pending:
            yield future.result()

def _notify(progress, phase, fraction):
    if progress:
        progress({'type': 'progress', 'phase': phase, 'progress': float(fraction)})

def reconstruct_rgb_tiled(normalized_cfa, pattern, tile_size=512, workers=4, progress=None, halo=LMMSE_HALO):
    """Bounded four-worker RGB execution; halo16 is exact to official float32."""
    a, p = _validate_cfa(normalized_cfa, pattern)
    _execution(tile_size, workers)
    if type(halo) is not int or halo < LMMSE_HALO or halo % 2:
        raise ValueError('LMMSE halo must be even and >=16')
    _library()
    output = np.empty((*a.shape, 3), np.float32)
    count = (a.shape[0] + tile_size - 1) // tile_size * ((a.shape[1] + tile_size - 1) // tile_size)

    def work(tile):
        y, x, sy, sx, y0, y1, x0, x1 = tile
        rgb = reconstruct_rgb(a[y0:y1, x0:x1], _local_pattern(p, y0, x0))
        return (tile, rgb[y - y0:y - y0 + sy, x - x0:x - x0 + sx].copy())
    _notify(progress, 'IPOL LMMSE RGB reconstruction', 0.0)
    for i, (tile, block) in enumerate(_bounded_results(work, _tiles(a.shape, tile_size, halo), workers)):
        y, x, sy, sx, *_ = tile
        output[y:y + sy, x:x + sx] = block
        _notify(progress, 'IPOL LMMSE RGB reconstruction', (i + 1) / count)
    return output

def reconstruct_response(samples, pattern, blacks, whites, weights, method, black, white, exposure_ev=0.0, progress=None, green_correction=None, tile_size=512, defer_quantization=False, workers=4):
    """Experimental ordinary-photo response; explicit cross-colour LMMSE.

    uint16 source is never mutated. All four CFA phases use independent
    float64 (DN-black)/(white-black), including unselected colours because
    LMMSE's colour-difference model requires them. Optional legacy RGGB G
    correction precedes both candidates. Float64 measured values are restored
    for each channel before float64 mixing, EV, and one final np.rint.
    """
    a = np.asarray(samples)
    p = _pattern(pattern)
    _execution(tile_size, workers)
    if a.ndim != 2 or min(a.shape) < 8 or a.dtype != np.uint16:
        raise ValueError('LMMSE 需要至少 8×8 的 16 位原始采样')
    if method not in METHODS:
        raise ValueError('细节模式无效')
    b, w = (np.asarray(blacks, np.float64), np.asarray(whites, np.float64))
    weights = np.asarray(weights, np.float64)
    if b.shape != (2, 2) or w.shape != (2, 2) or (not np.isfinite(b).all()) or (not np.isfinite(w).all()) or np.any(w <= b) or np.any(b < 0) or np.any(w > 65535):
        raise ValueError('原始分相位黑白电平无效')
    if weights.shape != (3,) or not np.isfinite(weights).all() or np.any(weights < 0) or (not np.isclose(weights.sum(), 1)):
        raise ValueError('单色通道比重无效')
    if not 0 <= black < white <= 65535 or not np.isfinite(exposure_ev) or (not -6 <= exposure_ev <= 6):
        raise ValueError('输出电平或曝光无效')
    _notify(progress, '归一化 LMMSE 所需的 RGB 采样', 0.35)
    normalized = np.empty(a.shape, np.float64)
    for py in range(2):
        for px in range(2):
            normalized[py::2, px::2] = (a[py::2, px::2].astype(np.float64) - b[py, px]) / (w[py, px] - b[py, px])
    settings = green_correction or {}
    correct = bool(settings.get('green_compensation', 0) and weights[1])
    if correct and (not np.array_equal(p, _pattern('RGGB'))):
        raise ValueError('当前绿色差异校正需要 RGGB 排列，请关闭该校正')
    changed = _detail._correct_green_normalized(normalized, black, white, settings, progress) if correct else 0
    _library()
    h, width = a.shape
    output = np.empty(a.shape, np.float64 if defer_quantization else np.uint16)
    targets = [int(t) for t in np.flatnonzero(weights)]
    stats = dict(container_clipped_low=0, container_clipped_high=0, at_or_above_white=0, below_recorded_black=0, kernel_measured_max_float32_error=0.0, float64_restored_measured_max_error=0.0, output_samples=int(a.size), quantization_deferred_for_lens=bool(defer_quantization), pre_lens_out_of_container_low=0, pre_lens_out_of_container_high=0, cross_colour_guidance=True, official_use_zhang_code_est=0, official_div_epsilon=LMMSE_DIV_EPSILON, cpu_workers=workers, tile_halo=LMMSE_HALO)
    count = (h + tile_size - 1) // tile_size * ((width + tile_size - 1) // tile_size)
    gain = 2.0 ** float(exposure_ev)

    def work(tile):
        y, x, sy, sx, y0, y1, x0, x1 = tile
        local = normalized[y0:y1, x0:x1]
        lp = _local_pattern(p, y0, x0)
        rgb = reconstruct_rgb(local, lp)
        mixed = np.zeros((sy, sx), np.float64)
        error = 0.0
        for target in targets:
            signal = rgb[..., target]
            block = signal[y - y0:y - y0 + sy, x - x0:x - x0 + sx].astype(np.float64)
            for py, px in np.argwhere(p == target):
                oy, ox = ((int(py) - y) % 2, (int(px) - x) % 2)
                measured = normalized[y + oy:y + sy:2, x + ox:x + sx:2]
                error = max(error, float(np.abs(block[oy::2, ox::2] - measured).max(initial=0)))
                block[oy::2, ox::2] = measured
            mixed += weights[target] * block
        mapped = black + mixed * ((white - black) * gain)
        if not defer_quantization:
            mapped = np.rint(mapped)
        return (tile, mapped, error)
    workers=min(workers,count)
    stats['cpu_workers']=workers
    halo = stats['tile_halo']
    _notify(progress, 'LMMSE 统计重建', 0.43)
    for i, (tile, mapped, error) in enumerate(_bounded_results(work, _tiles(a.shape, tile_size, halo), workers)):
        y, x, sy, sx, *_ = tile
        stats['kernel_measured_max_float32_error'] = max(stats['kernel_measured_max_float32_error'], error)
        low, high = (int(np.count_nonzero(mapped < 0)), int(np.count_nonzero(mapped > 65535)))
        if defer_quantization:
            stats['pre_lens_out_of_container_low'] += low
            stats['pre_lens_out_of_container_high'] += high
        else:
            stats['container_clipped_low'] += low
            stats['container_clipped_high'] += high
        stats['at_or_above_white'] += int(np.count_nonzero(mapped >= white))
        stats['below_recorded_black'] += int(np.count_nonzero(mapped < black))
        output[y:y + sy, x:x + sx] = mapped if defer_quantization else np.clip(mapped, 0, 65535).astype(np.uint16)
        _notify(progress, 'LMMSE 统计重建', 0.43 + 0.15 * (i + 1) / count)
    return (output, stats, changed)

def method_info(method='lmmse',target=None):
    if method!='lmmse':raise ValueError('细节模式无效')
    return dict(mode='lmmse',code='LMMSE',implementation_kind='official_IPOL_v1.1_with_measured_restoration',
        same_colour_only=False,all_cfa_colours_used=True,experimental=True,use_zhang_code_est=0,
        normalized_div_epsilon=LMMSE_DIV_EPSILON,tile_core=512,tile_halo=16,
        automatic_noise_estimation=False,internal_residual_statistics=True,
        source_references=['https://doi.org/10.1109/TIP.2005.857260','https://doi.org/10.5201/ipol.2011.g_zwld'],
        measurement_policy='Measured observations restored before explicit exposure and final quantization',
        limitation='Cross-colour assumptions can transfer chromatic texture and produce overshoot; not suitable for strict independent narrowband.')
