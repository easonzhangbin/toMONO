"""Production ports of the frozen C01, D11 and D10 same-colour algorithms.

All units remain scene-linear. Inputs must already use the correct per-phase
black/white normalization. Only target-colour samples are read, including during
validation, padding, covariance estimation, and direction selection. No WB,
exposure, tone curve, cross-colour guide, learned model, or deconvolution enters.

These are inspired_not_reproduction implementations. The D10 G model learns a
single convex H/V polynomial direction mixture at coarse scale and transfers it
to fine scale, with a stabilized leave-row-out PRESS reliability surrogate.
Its overlapping, data-dependent stencils are not independent held-out tests.
D10 uses sigma0 and never estimates noise. R/B use its common bounded cubic
fallback: no new R/B AR method is claimed. C01 evaluates the compact
diamond/rectangle spectral filter; D11 adds its frozen measured local-range
limiter. Product response processing restores measurements in float64 and uses
one final quantization, after optional selected preprocessing, mixing and EV.
No method can identify frequencies already aliased at CFA sampling.
"""
from __future__ import annotations

import ctypes
import functools
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
METHODS = ('spectral', 'spectral_guard', 'directional')
METHOD_CODES = {'spectral': 'C01', 'spectral_guard': 'D11', 'directional': 'D10'}
_PATTERNS = {
    'RGGB': ((0, 1), (1, 2)), 'BGGR': ((2, 1), (1, 0)),
    'GRBG': ((1, 0), (2, 1)), 'GBRG': ((1, 2), (0, 1)),
}
SPECTRAL_RADIUS = 48
SPECTRAL_TILE = 512
_LIB = None


def _pattern(pattern):
    if isinstance(pattern, str):
        try:
            return np.asarray(_PATTERNS[pattern.upper()], np.uint8)
        except KeyError as exc:
            raise ValueError('Expected RGGB/BGGR/GRBG/GBRG') from exc
    p = np.asarray(pattern)
    if p.shape != (2, 2) or tuple(p.ravel()) not in (
        (0, 1, 1, 2), (2, 1, 1, 0), (1, 0, 2, 1), (1, 2, 0, 1)
    ):
        raise ValueError('Expected a valid RGB Bayer 2x2 pattern')
    return p.astype(np.uint8)


def _library():
    global _LIB
    if _LIB is not None:
        return _LIB
    binary = HERE / 'build/native-macos/libtomono_detail.dylib'
    try:
        lib = ctypes.CDLL(str(binary))
    except OSError as exc:
        raise RuntimeError('细节重建核心缺失，请重新安装完整的toMONO软件') from exc
    lib.tomono_detail_version.restype = ctypes.c_uint
    if lib.tomono_detail_version() != 0x100:
        raise RuntimeError('细节重建核心版本不匹配，请重新安装完整的toMONO软件')
    ptr = ctypes.POINTER(ctypes.c_float)
    lib.tomono_detail_reconstruct.argtypes = [ptr, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_double, ptr, ptr]
    lib.tomono_detail_reconstruct.restype = ctypes.c_int
    _LIB = lib
    return lib


def _transition(q, center, half_width):
    t = np.clip((q - (center - half_width)) / (2 * half_width), 0, 1)
    return 1 + np.cos(np.pi * t)


@functools.lru_cache(maxsize=2)
def _spectral_kernel(green):
    """A compact FIR derived from the correct lattice's anti-alias region.

    The transition is symmetric about the lattice Nyquist boundary. Before
    spatial tapering its reciprocal alias translates sum to the lattice index
    (2 for G, 4 for R/B). The finite 97x97 support permits exact halo tiling;
    per-phase DC normalization removes truncation-induced CFA phase bias.
    """
    design = 512
    f = np.abs(np.fft.fftfreq(design))
    if green:
        transfer = _transition(f[:, None] + f[None, :], .5, .04)
    else:
        a = _transition(f, .25, .02)
        transfer = a[:, None] * a[None, :]
    spatial = np.fft.fftshift(np.fft.ifft2(transfer).real)
    r = SPECTRAL_RADIUS
    k = spatial[design // 2-r:design // 2+r+1,
                design // 2-r:design // 2+r+1].copy()
    distance = np.abs(np.arange(-r, r + 1, dtype=np.float64))
    # Flat until radius 32, cosine taper to zero at radius 48.
    window = .5 + .5*np.cos(np.pi*np.clip((distance-32)/16, 0, 1))
    k *= window[:, None] * window[None, :]
    # Cardinal measured sublattice. Enforce analytic zeros against FFT roundoff.
    yy, xx = np.indices(k.shape)
    measured_offsets = ((yy + xx) % 2 == 0) if green else ((yy % 2 == 0) & (xx % 2 == 0))
    k[measured_offsets] = 0
    k[r, r] = 1
    phase_dc = np.zeros((2, 2), np.float64)
    for y in range(2):
        for x in range(2):
            if green:
                phase_dc[y, x] = k[(yy + xx) % 2 == (y + x) % 2].sum()
            else:
                phase_dc[y, x] = k[y::2, x::2].sum()
    k.setflags(write=False)
    phase_dc.setflags(write=False)
    return k, phase_dc


def _fft_convolve_valid(data, kernel):
    # The distributable worker requires only NumPy. These FFTs evaluate the
    # frozen compact FIR; no whole-frame transform or runtime compiler is used.
    shape = tuple(a+b-1 for a, b in zip(data.shape, kernel.shape))
    shape = tuple(1 << (n-1).bit_length() for n in shape)
    full = np.fft.irfft2(np.fft.rfft2(data, s=shape) *
                        np.fft.rfft2(kernel, s=shape), s=shape)
    sy, sx = kernel.shape[0]-1, kernel.shape[1]-1
    return full[sy:data.shape[0], sx:data.shape[1]]


def _spectral(sparse, phase_y, phase_x, green):
    kernel, dc = _spectral_kernel(green)
    r = SPECTRAL_RADIUS
    # Reflect uses the true image origin. Its parity-preserving map never
    # introduces other-colour observations, including for odd image dimensions.
    padded = np.pad(sparse, ((r, r), (r, r)), mode='reflect')
    h, w = sparse.shape
    output = np.empty((h, w), np.float32)
    for y in range(0, h, SPECTRAL_TILE):
        sy = min(SPECTRAL_TILE, h-y)
        for x in range(0, w, SPECTRAL_TILE):
            sx = min(SPECTRAL_TILE, w-x)
            tile = padded[y:y+sy+2*r, x:x+sx+2*r]
            out = _fft_convolve_valid(tile, kernel)
            for oy in range(2):
                for ox in range(2):
                    denominator = dc[(y+oy-phase_y) % 2, (x+ox-phase_x) % 2]
                    out[oy::2, ox::2] /= denominator
            output[y:y+sy, x:x+sx] = out
    return output


def reconstruct(samples, pattern, target, method, noise_sigma=0):
    """Return a full float32 linear plane, preserving target measurements.

    ``samples`` is a floating 2D normalized CFA, >=8x8. Other-colour locations
    may even contain NaNs: they are neither read nor validated. ``target`` is
    0/1/2 or R/G/B. Pattern may be a Bayer name or RGB-coded 2x2 array.
    ``noise_sigma`` is a declared normalized calibration standard deviation,
    never a truth-conditioned per-pixel oracle. Zero means no external noise
    variance, not an instruction to estimate noise from texture. No automatic
    noise estimator is used. The reliable AR ignores positive sigma; the
    noise-aware AR and spectral guard use it only at missing sites. The main
    new benchmark uses a fixed reference-18%-gray calibrated sigma for each
    noisy acquisition setting and sigma0 for clean/old-regression/ablation.
    """
    a = np.asarray(samples)
    if a.ndim != 2 or min(a.shape) < 8 or not np.issubdtype(a.dtype, np.floating):
        raise ValueError('Need a floating normalized CFA >=8x8')
    p = _pattern(pattern)
    if isinstance(target, str):
        try:
            target = {'R': 0, 'G': 1, 'B': 2}[target.upper()]
        except KeyError as exc:
            raise ValueError('Target must be R/G/B or 0/1/2') from exc
    if isinstance(target, (bool, np.bool_)) or target not in (0, 1, 2):
        raise ValueError('Target must be R/G/B or 0/1/2')
    if method not in METHODS:
        raise ValueError('Unknown prototype: ' + str(method))
    sigma = float(noise_sigma)
    if not np.isfinite(sigma) or sigma < 0 or sigma > 1e3:
        raise ValueError('Invalid normalized noise sigma')
    sparse = np.zeros(a.shape, np.float32)
    phases = np.argwhere(p == target)
    minimum, maximum = np.inf, -np.inf
    for py, px in phases:
        v = a[py::2, px::2]
        if not np.isfinite(v).all() or np.max(np.abs(v)) > 1e6:
            raise ValueError('Nonfinite or unreasonable target-colour samples')
        sparse[py::2, px::2] = v
        minimum = min(minimum, float(v.min()))
        maximum = max(maximum, float(v.max()))
    if minimum == maximum:
        return np.full(a.shape, minimum, np.float32)
    py, px = map(int, phases[0])
    spectral = _spectral(sparse, py, px, target == 1) if method in ('spectral','spectral_guard') else None
    if method == 'spectral':
        output = spectral
    else:
        output = np.empty_like(sparse)
        ptr = ctypes.POINTER(ctypes.c_float)
        code = _library().tomono_detail_reconstruct(
            sparse.ctypes.data_as(ptr), a.shape[0], a.shape[1], py, px,
            int(target == 1), 2 if method == 'spectral_guard' else 0, sigma,
            spectral.ctypes.data_as(ptr) if spectral is not None else None,
            output.ctypes.data_as(ptr))
        if code:
            raise RuntimeError('细节重建失败：' + str(code))
    for py, px in phases:
        output[py::2, px::2] = sparse[py::2, px::2]
    return output


def reconstruct_tiled(samples, pattern, target, method, noise_sigma=0, tile_size=512, progress=None):
    """Memory-bounded same-colour wrapper with 48-pixel, parity-aware halos.

    Every candidate has finite support <=48 pixels, including AR training.
    Consequently core pixels agree with untiled evaluation to floating FFT
    roundoff; no overlapping estimates or seam blending changes measurements.
    Tile size changes execution only, and is not a reconstruction parameter.
    """
    a = np.asarray(samples)
    if a.ndim != 2 or min(a.shape) < 8:
        raise ValueError('Need a normalized CFA >=8x8')
    if isinstance(tile_size, bool) or int(tile_size) != tile_size or tile_size < 8 or tile_size % 2:
        raise ValueError('Tile size must be an even integer >=8')
    p = _pattern(pattern)
    h, w = a.shape
    output = np.empty(a.shape, np.float32)
    halo = SPECTRAL_RADIUS
    for y in range(0, h, tile_size):
        y0, y1 = max(0, y-halo), min(h, y+tile_size+halo)
        for x in range(0, w, tile_size):
            if progress:
                progress({'type':'progress','phase':'同色细节重建','progress':.47+.11*(y*w+x)/(h*w)})
            x0, x1 = max(0, x-halo), min(w, x+tile_size+halo)
            local_pattern = p[(np.arange(2)+y0)[:, None] % 2,
                              (np.arange(2)+x0)[None, :] % 2]
            local = reconstruct(a[y0:y1, x0:x1], local_pattern,
                                target, method, noise_sigma)
            sy, sx = min(tile_size, h-y), min(tile_size, w-x)
            output[y:y+sy, x:x+sx] = local[y-y0:y-y0+sy, x-x0:x-x0+sx]
    return output


def method_info(method, target=None):
    if method not in METHODS:
        raise ValueError('细节模式无效')
    return {'mode':method,'code':METHOD_CODES[method],
            'implementation_kind':'inspired_not_reproduction',
            'same_colour_only':True,'automatic_noise_estimation':False,
            'noise_sigma':0.,'tile_core':512,'tile_halo':48,
            'RB_directional_fallback':bool(method=='directional' and target in (0,2)),
            'measurement_policy':'hard restoration before explicit exposure and final quantization',
            'limitation':'Selected-colour Nyquist aliases cannot be uniquely recovered; spectral may ring; local range guards can suppress unsampled extrema.'}


def _notify(progress, phase, fraction):
    if progress:
        progress({'type':'progress','phase':phase,'progress':fraction})


def _correct_green_normalized(values, black, white, settings, progress=None):
    """Selected legacy G-difference policy, before detail kernels, in float64.

    Its optional R/B eligibility gate is explicit preprocessing. The detail
    kernels themselves only access their target colour. Strict narrowband never
    calls this function. A median selects an existing normalized G observation;
    no integer normalization or intermediate quantization is performed.
    """
    compensation=float(settings.get('green_compensation',0))
    if not compensation:
        return 0
    h,w=values.shape;span=white-black
    columns=np.arange(0,w-2,2);left=np.maximum(columns-1,1);right=columns+1
    changed=0
    for start in range(1,h-2,256):
        rows=np.arange(start,min(h-2,start+256),2)
        if not len(rows):continue
        _notify(progress,'应用绿色差异校正',.41+.02*start/h)
        yy=rows[:,None];xx=columns[None,:]
        center=black+values[yy,xx]*span
        nearby=[black+values[yy-1,left[None,:]]*span,
                black+values[yy-1,right[None,:]]*span,
                black+values[yy+1,left[None,:]]*span,
                black+values[yy+1,right[None,:]]*span]
        focus_red=bool(settings.get('focus_red',False));focus_blue=bool(settings.get('focus_blue',False))
        eligible=np.ones(center.shape,bool) if not(focus_red or focus_blue) else np.zeros(center.shape,bool)
        camera_white=settings.get('camera_white',[1,1,1])
        if focus_red:
            eligible|=center<=(black+values[yy-1,xx]*span)/float(camera_white[0])
        if focus_blue:
            eligible|=center<=(black+values[yy,right[None,:]]*span)/float(camera_white[2])
        threshold=(compensation*center+nearby[0]+nearby[1]+nearby[2]+nearby[3])/5
        replacement=np.partition(np.stack([center,*nearby]),2,axis=0)[2]
        selected=eligible&(center>threshold)&(replacement!=center)
        current=values[yy,xx]
        current[selected]=(replacement[selected]-black)/span
        values[yy,xx]=current
        changed+=int(np.count_nonzero(selected))
    return changed


def reconstruct_response(samples, pattern, blacks, whites, weights, method,
                         black, white, exposure_ev=0., progress=None,
                         green_correction=None, tile_size=512, defer_quantization=False):
    """Prepare selected CFA phases, reconstruct/mix in float, round exactly once.

    ``samples`` is a private uint16 sensor buffer after explicitly selected
    defect repair. Selected G correction is applied to normalized observations
    here, before every channel kernel. The original input buffer is untouched.
    Observations are restored from float64 normalization before mixing and EV.
    """
    samples=np.asarray(samples);p=_pattern(pattern)
    if samples.dtype!=np.uint16 or samples.ndim!=2 or min(samples.shape)<8:
        raise ValueError('细节重建需要至少8×8的16位原始Bayer采样')
    if method not in METHODS:
        raise ValueError('细节模式无效')
    if type(tile_size) is not int or tile_size<8 or tile_size%2:
        raise ValueError('细节分块尺寸必须为至少8的偶数')
    b=np.asarray(blacks,np.float64);w=np.asarray(whites,np.float64)
    weights=np.asarray(weights,np.float64)
    if b.shape!=(2,2) or w.shape!=(2,2) or not np.isfinite(b).all() or not np.isfinite(w).all() or np.any(w<=b) or np.any(b<0) or np.any(w>65535):
        raise ValueError('原始分相位黑白电平无效')
    if weights.shape!=(3,) or not np.isfinite(weights).all() or np.any(weights<0) or not np.isclose(weights.sum(),1):
        raise ValueError('单色通道权重无效')
    if not 0<=black<white<=65535 or not np.isfinite(exposure_ev) or not -6<=exposure_ev<=6:
        raise ValueError('输出黑白电平或曝光无效')
    settings=green_correction or {}
    correct=bool(settings.get('green_compensation',0) and weights[1])
    if correct and not np.array_equal(p,np.array([[0,1],[1,2]],np.uint8)):
        raise ValueError('绿色差异校正目前需要RGGB排列，请关闭绿色差异校正')
    h,width=samples.shape
    normalized=np.zeros(samples.shape,np.float64)
    targets=[int(t) for t in np.flatnonzero(weights)]
    normalization_targets=set(targets)
    if correct and settings.get('focus_red',False):normalization_targets.add(0)
    if correct and settings.get('focus_blue',False):normalization_targets.add(2)
    for y in range(0,h,256):
        _notify(progress,'归一化所选同色采样',.35+.06*y/h)
        for py in range(2):
            for px in range(2):
                if p[py,px] not in normalization_targets:continue
                sy=(py-y)%2
                normalized[y+sy:y+256:2,px::2]=(samples[y+sy:y+256:2,px::2].astype(np.float64)-b[py,px])/(w[py,px]-b[py,px])
    green_changed=_correct_green_normalized(normalized,black,white,settings,progress) if correct else 0
    pixels=np.empty(samples.shape,np.float64 if defer_quantization else np.uint16)
    stats=dict(container_clipped_low=0,container_clipped_high=0,at_or_above_white=0,
               below_recorded_black=0,kernel_measured_max_float32_error=0.,
               float64_restored_measured_max_error=0.,output_samples=int(samples.size),
               quantization_deferred_for_lens=bool(defer_quantization),
               pre_lens_out_of_container_low=0,pre_lens_out_of_container_high=0)
    tiles=((h+tile_size-1)//tile_size)*((width+tile_size-1)//tile_size)
    completed=0;gain=2.**float(exposure_ev);span=white-black;halo=SPECTRAL_RADIUS
    for y in range(0,h,tile_size):
        sy=min(tile_size,h-y);y0=max(0,y-halo);y1=min(h,y+sy+halo)
        for x in range(0,width,tile_size):
            sx=min(tile_size,width-x);x0=max(0,x-halo);x1=min(width,x+sx+halo)
            local_pattern=p[(np.arange(2)+y0)[:,None]%2,(np.arange(2)+x0)[None,:]%2]
            mixed=np.zeros((sy,sx),np.float64)
            for index,target in enumerate(targets):
                _notify(progress,'重建所选同色细节',.43+.15*(completed+index/len(targets))/tiles)
                signal=reconstruct(normalized[y0:y1,x0:x1],local_pattern,target,method,noise_sigma=0.)
                block=signal[y-y0:y-y0+sy,x-x0:x-x0+sx].astype(np.float64)
                for py,px in np.argwhere(p==target):
                    oy=(int(py)-y)%2;ox=(int(px)-x)%2
                    measured=normalized[y+oy:y+sy:2,x+ox:x+sx:2]
                    delta=np.abs(block[oy::2,ox::2]-measured)
                    stats['kernel_measured_max_float32_error']=max(stats['kernel_measured_max_float32_error'],float(delta.max(initial=0)))
                    block[oy::2,ox::2]=measured
                mixed+=weights[target]*block
            mapped=black+mixed*(span*gain)
            if defer_quantization:
                stats['pre_lens_out_of_container_low']+=int(np.count_nonzero(mapped<0))
                stats['pre_lens_out_of_container_high']+=int(np.count_nonzero(mapped>65535))
            else:
                mapped=np.rint(mapped)
                stats['container_clipped_low']+=int(np.count_nonzero(mapped<0))
                stats['container_clipped_high']+=int(np.count_nonzero(mapped>65535))
            stats['at_or_above_white']+=int(np.count_nonzero(mapped>=white))
            stats['below_recorded_black']+=int(np.count_nonzero(mapped<black))
            pixels[y:y+sy,x:x+sx]=mapped if defer_quantization else np.clip(mapped,0,65535).astype(np.uint16)
            completed+=1
    _notify(progress,'同色细节重建完成',.58)
    return pixels,stats,green_changed
