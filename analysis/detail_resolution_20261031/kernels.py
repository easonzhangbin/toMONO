"""Three independent, same-colour, hard-measurement research interpolators.

All units remain scene-linear. Inputs must already use the correct per-phase
black/white normalization. Only target-colour samples are read, including during
validation, padding, covariance estimation, and direction selection. No WB,
exposure, tone curve, cross-colour guide, learned model, or deconvolution enters.

These are inspired_not_reproduction implementations. NEDI supplies the idea of
low/high-resolution covariance duality; WENO supplies competing polynomial
stencils and smoothness weights. The spectral candidate follows the reciprocal
lattices directly: G's quincunx diamond versus R/B's rectangular bandwidth.
None can identify scene frequencies aliased before or at CFA sampling.
"""
from __future__ import annotations

import ctypes
import functools
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

import numpy as np

HERE = Path(__file__).resolve().parent
METHODS = ('quincunx_spectral', 'nedi_covariance', 'weno_directional')
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
    source = HERE / 'detail_native.c'
    suffix = '.dylib' if platform.system() == 'Darwin' else '.so'
    # Source hash prevents a stale, differently parameterized native binary.
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    binary = HERE / ('detail_native_' + digest + suffix)
    if not binary.exists():
        temp = binary.with_name('.build-' + str(os.getpid()) + suffix)
        command = ['clang', '-std=c11', '-O3', '-Wall', '-Wextra', '-Werror',
                   '-ffp-contract=off', '-fno-fast-math']
        command += ['-dynamiclib'] if platform.system() == 'Darwin' else ['-shared', '-fPIC']
        try:
            subprocess.run(command + [str(source), '-o', str(temp), '-lm'],
                           check=True, capture_output=True, text=True)
            temp.replace(binary)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Prototype C build failed: ' + exc.stderr) from exc
        finally:
            temp.unlink(missing_ok=True)
    lib = ctypes.CDLL(str(binary))
    ptr = ctypes.POINTER(ctypes.c_float)
    lib.detail_reconstruct.argtypes = [ptr, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_double, ptr]
    lib.detail_reconstruct.restype = ctypes.c_int
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
    # SciPy keeps float32/64 FFTs efficient; NumPy is a functional fallback.
    try:
        from scipy.signal import fftconvolve
    except ImportError:
        shape = tuple(a+b-1 for a, b in zip(data.shape, kernel.shape))
        shape = tuple(1 << (n-1).bit_length() for n in shape)
        full = np.fft.irfft2(np.fft.rfft2(data, s=shape) *
                            np.fft.rfft2(kernel, s=shape), s=shape)
        sy, sx = kernel.shape[0]-1, kernel.shape[1]-1
        return full[sy:data.shape[0], sx:data.shape[1]]
    return fftconvolve(data, kernel, mode='valid')


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
    ``noise_sigma`` is a caller-supplied normalized standard deviation; the
    frozen comparison uses zero for every clean and noisy scene. It changes
    only missing-site adaptation; real measurements always remain unchanged.
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
    if method == 'quincunx_spectral':
        output = _spectral(sparse, py, px, target == 1)
    else:
        output = np.empty_like(sparse)
        ptr = ctypes.POINTER(ctypes.c_float)
        code = _library().detail_reconstruct(
            sparse.ctypes.data_as(ptr), a.shape[0], a.shape[1], py, px,
            int(target == 1), int(method == 'nedi_covariance'), sigma,
            output.ctypes.data_as(ptr))
        if code:
            raise RuntimeError('Prototype native error ' + str(code))
    for py, px in phases:
        output[py::2, px::2] = sparse[py::2, px::2]
    return output


def reconstruct_tiled(samples, pattern, target, method, noise_sigma=0, tile_size=512):
    """Memory-bounded same-colour wrapper with 48-pixel, parity-aware halos.

    Every candidate has finite support <=48 pixels, including both R/B passes.
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
            x0, x1 = max(0, x-halo), min(w, x+tile_size+halo)
            local_pattern = p[(np.arange(2)+y0)[:, None] % 2,
                              (np.arange(2)+x0)[None, :] % 2]
            local = reconstruct(a[y0:y1, x0:x1], local_pattern,
                                target, method, noise_sigma)
            sy, sx = min(tile_size, h-y), min(tile_size, w-x)
            output[y:y+sy, x:x+sx] = local[y-y0:y-y0+sy, x-x0:x-x0+sx]
    return output


def manifest():
    """Read the frozen pre-benchmark parameters and file hashes."""
    return json.loads((HERE / 'kernel_manifest.json').read_text())
