/* Research-only C ABI around the byte-identical BSD-2-Clause IPOL source.
 * The official algorithm's planar output and normalized epsilon are unchanged.
 */
#include <stddef.h>
#include <limits.h>
#include "lmmse/dmzhangwu.h"

unsigned tomono_lmmse_version(void) { return 0x100u; }

int tomono_lmmse_rgb(const float *input, int height, int width,
                     int red_y, int red_x, float *planar_output)
{
    if (!input || !planar_output || height < 8 || width < 8 ||
        red_y < 0 || red_y > 1 || red_x < 0 || red_x > 1 ||
        (size_t)height * (size_t)width > (size_t)INT_MAX)
        return -1;
    return ZhangWuDemosaic(planar_output, input, width, height,
                           red_x, red_y, 0) ? 0 : -2;
}
