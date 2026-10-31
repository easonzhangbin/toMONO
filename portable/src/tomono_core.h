#ifndef TOMONO_CORE_H
#define TOMONO_CORE_H
#include <stdint.h>
#include <stddef.h>
#if defined(_WIN32) && defined(TOMONO_BUILD_DLL)
#define TOMONO_API __declspec(dllexport)
#elif defined(__GNUC__)
#define TOMONO_API __attribute__((visibility("default")))
#else
#define TOMONO_API
#endif
#ifdef __cplusplus
extern "C" {
#endif
/* Reconstructed experimental core, NOT the original application's ABI. */
TOMONO_API unsigned tomono_core_version(void);
TOMONO_API unsigned tomono_worker_count(void);
/* Locally adaptive, nonnegative green-only Bayer estimates; preserves measured
   green. TOMONO_THREADS=1 selects the deterministic serial reference execution. */
TOMONO_API int tomono_edge_green_plane(const uint16_t *,size_t,uint16_t *,size_t,
    int,int,const uint8_t [4],unsigned);
/* Pattern row-major: 0=red, 1=green, 2=blue. Returns -1 for invalid input. */
TOMONO_API int tomono_cfa_color(const uint8_t pattern[4], int row, int col,
                           int row_offset, int col_offset);
/* Reconstructed CheckBorderFour mapping; length >= 8, delta in [-4,4]. */
TOMONO_API int tomono_neighbor(int pos, int delta, int length);
/* A 7x7 row-major signed-int patch, center at [3][3]. Original scalar
   instruction order and float32 arithmetic; valid sensor samples 0..65535. */
TOMONO_API float tomono_bicubic_green_patch(const int32_t patch[49]);
typedef struct ToMONOGreenParams {
    float compensation, red_white, blue_white;
    int focus_red, focus_blue;
} ToMONOGreenParams;
/* Legacy five-sample median compatibility rule. Parameters must be finite,
   with positive white coefficients. Neighbors are NW, NE, SW, SE. */
TOMONO_API uint16_t tomono_correct_green_pixel(uint16_t center,
    uint16_t nw, uint16_t ne, uint16_t sw, uint16_t se,
    uint16_t red_neighbor, uint16_t blue_neighbor,
    const ToMONOGreenParams *params);
/* In-place preprocessing for RGGB with zero CFA offsets only. Modifies G2
   (odd row, even column); original loop excludes final two rows/columns.
   Does not read original application's output or process. */
TOMONO_API int tomono_correct_green_rggb(uint16_t *pixels, size_t count,
    int width, int height, const ToMONOGreenParams *params, size_t *changed);
/* No allocation: input/output must be separate buffers with width*height
   samples and stride=width; dimensions >= 8. Original green-pass loop skips
   row zero. This reproduces that loop, NOT the entire application pipeline.
   No green imbalance correction, linearization, filters, HR or DNG I/O.
   Returns 0 or -1. Counts are capacities in samples. */
TOMONO_API int tomono_bicubic_green_plane(const uint16_t *input, size_t input_count,
    uint16_t *output, size_t output_count, int width, int height,
    const uint8_t pattern[4], int row_offset, int col_offset);
/* General Bayer path: configurable integer ceiling, with row zero included.
   The legacy entry point above retains its original 14-bit/row-one behavior. */
TOMONO_API int tomono_bicubic_green_plane_range(const uint16_t *input, size_t input_count,
    uint16_t *output, size_t output_count, int width, int height,
    const uint8_t pattern[4], int row_offset, int col_offset, unsigned ceiling);
/* Automatic green-sample reconstruction for arbitrary repeating CFA lattices
   up to 16x16 (including 6x6 X-Trans). Code 1 denotes measured green. */
TOMONO_API int tomono_green_lattice_plane(const uint16_t *input, size_t input_count,
    uint16_t *output, size_t output_count, int width, int height,
    const uint8_t *pattern, int pattern_rows, int pattern_cols, unsigned ceiling);
TOMONO_API int tomono_remap_gray_strip(const float *,size_t,int,int,const float *,size_t,
    uint16_t *,size_t,int,float);
/* Normalized camera-channel samples, with measured sites unchanged. Bayer
   R/B use bounded separable cubic interpolation; other CFA grids use IDW.
   Per-phase black/white levels normalize the measured samples.
   Output is one row strip of double signals; no WB, tone curve or sharpening. */
TOMONO_API int tomono_channel_strip(const uint16_t *,size_t,int,int,
    const uint8_t *,int,int,int,const double *,const double *,
    int,int,double *,size_t);
/* Strict2x2 RGB Bayer target-only reconstruction, including every border.
   target0=R,1=G,2=B; interpolation0=bounded cubic,1=linear. No correction,
   cross-colour guidance, gain or quantization. Measured normalized values are
   returned unchanged. R/B use their rectangular same-colour lattice; G uses
   the rotated green lattice. Cubic estimates stay within nearest target
   neighbors. Requires core ABI0x402; existing entry points remain unchanged. */
TOMONO_API int tomono_pure_channel_strip(const uint16_t *,size_t,int,int,
    const uint8_t [4],int,int,const double [4],const double [4],
    int,int,double *,size_t);
#ifdef __cplusplus
}
#endif
#endif
