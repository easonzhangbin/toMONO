#include "tomono_core.h"
#include <stdio.h>

int main(void) {
    int32_t patch[49];
    for(int i=0;i<49;i++) patch[i]=1000;
    if(tomono_bicubic_green_patch(patch)!=1000.0f) return 1;
    patch[3*7+2]+=256;
    if(tomono_bicubic_green_patch(patch)!=1081.0f) return 2;
    uint8_t rggb[4]={0,1,1,2};
    if(tomono_cfa_color(rggb,0,0,0,0)!=0) return 3;
    if(tomono_cfa_color(rggb,1,1,0,0)!=2) return 4;
    uint16_t input[16*16],output[16*16];
    for(int i=0;i<16*16;i++) input[i]=1234;
    if(tomono_bicubic_green_plane(input,256,output,256,16,16,rggb,0,0)) return 5;
    for(int i=0;i<256;i++) if(output[i]!=1234) return 6;
    if(tomono_bicubic_green_plane(input,256,input,256,16,16,rggb,0,0)!=-1) return 7;
    if(tomono_bicubic_green_plane(input,255,output,256,16,16,rggb,0,0)!=-1) return 8;
    ToMONOGreenParams gp={1.231f,0.257286012172699f,0.675462007522583f,1,0};
    for(int i=0;i<256;i++) input[i]=1000;
    input[3*16+4]=6000;input[2*16+4]=2000;
    input[15*16+4]=6000;
    size_t changed=0;
    if(tomono_correct_green_rggb(input,256,16,16,&gp,&changed) || changed!=1) return 9;
    if(input[3*16+4]!=1000 || input[15*16+4]!=6000) return 10;
    puts("PASS: CFA, cubic coefficients, constant plane, bounds, alias, green correction and excluded edge");
    return 0;
}
