#include "tomono_core.h"
#include <stdlib.h>
#include <string.h>
#include <math.h>
#ifdef __APPLE__
#include <dispatch/dispatch.h>
#include <unistd.h>
#endif

typedef void (*RowFunction)(void *, int);
typedef struct { void *data; RowFunction row; int height, workers; } RowJob;
unsigned tomono_worker_count(void) {
#ifdef __APPLE__
    long count=sysconf(_SC_NPROCESSORS_ONLN);
    const char *setting=getenv("TOMONO_THREADS");
    if (setting && *setting) { char *end; long value=strtol(setting,&end,10); if (!*end && value>=1 && value<=32) count=value; }
    return (unsigned)(count<1 ? 1 : count>8 ? 8 : count);
#else
    return 1;
#endif
}
#ifdef __APPLE__
static void row_chunk(void *context, size_t worker) {
    RowJob *job=context;
    int start=(int)((size_t)job->height*worker/(size_t)job->workers);
    int end=(int)((size_t)job->height*(worker+1)/(size_t)job->workers);
    for (int row=start;row<end;row++) job->row(job->data,row);
}
#endif
static void run_rows(void *data, RowFunction row, int height) {
#ifdef __APPLE__
    RowJob job={data,row,height,height<256 ? 1 : (int)tomono_worker_count()};
    dispatch_apply_f((size_t)job.workers,dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),&job,row_chunk);
#else
    for (int y=0;y<height;y++) row(data,y);
#endif
}

unsigned tomono_core_version(void) { return 0x00000402u; }

int tomono_cfa_color(const uint8_t pattern[4], int row, int col,
                   int row_offset, int col_offset) {
    int64_t r=(int64_t)row+row_offset, c=(int64_t)col+col_offset;
    if (!pattern || r<0 || c<0) return -1;
    unsigned k=(unsigned)(r%2)*2+(unsigned)(c%2);
    uint8_t code=pattern[k];
    return code==0 ? 0 : (code==2 ? 2 : 1);
}

int tomono_neighbor(int pos, int delta, int length) {
    if (length<8 || pos<0 || pos>=length || delta < -4 || delta > 4) return -1;
    int64_t n=(int64_t)pos+delta;
    if (n>=0 && n<length) return (int)n;
    if (delta==-1) return 1;
    if (delta==1) return length-2;
    return pos;
}

uint16_t tomono_correct_green_pixel(uint16_t center,
    uint16_t nw, uint16_t ne, uint16_t sw, uint16_t se,
    uint16_t red_neighbor, uint16_t blue_neighbor,
    const ToMONOGreenParams *params) {
    if (!params || params->compensation==0.0f) return center;
    int eligible=(!params->focus_red && !params->focus_blue);
    if (params->focus_red && (float)center <= (float)red_neighbor/params->red_white) eligible=1;
    if (params->focus_blue && (float)center <= (float)blue_neighbor/params->blue_white) eligible=1;
    if (!eligible) return center;
    float sum=(float)nw+(float)ne;
    sum=sum+(float)sw;
    sum=sum+(float)se;
    float threshold=(params->compensation*(float)center+sum)/5.0f;
    if ((float)center<=threshold) return center;
    uint16_t values[5]={center,nw,ne,sw,se};
    for (int i=0;i<4;i++) {
        for (int j=i+1;j<5;j++) {
            if (values[j]<values[i]) {
                uint16_t tmp=values[j];values[j]=values[i];values[i]=tmp;
            }
        }
    }
    return values[2];
}

int tomono_correct_green_rggb(uint16_t *pixels, size_t count,
    int width, int height, const ToMONOGreenParams *params, size_t *changed) {
    if (changed) *changed=0;
    if (!pixels || !params || width<8 || height<8) return -1;
    if ((size_t)height>SIZE_MAX/(size_t)width || count<(size_t)width*height) return -1;
    if (!(params->compensation>=0.0f && params->compensation<=1.255f) ||
        !(params->red_white>0.0f && params->red_white<=1.0e10f) ||
        !(params->blue_white>0.0f && params->blue_white<=1.0e10f)) return -1;
    if (params->compensation==0.0f) return 0;
    size_t replacements=0;
    for (int row=1;row<height-2;row+=2) {
        for (int col=0;col<width-2;col+=2) {
            int up=row-1,down=row+1,left=(col==0 ? 1 : col-1),right=col+1;
            size_t index=(size_t)row*width+col;
            uint16_t center=pixels[index];
            uint16_t v=tomono_correct_green_pixel(center,
                pixels[(size_t)up*width+left],pixels[(size_t)up*width+right],
                pixels[(size_t)down*width+left],pixels[(size_t)down*width+right],
                pixels[(size_t)up*width+col],pixels[(size_t)row*width+right],params);
            pixels[index]=v;
            replacements+=(v!=center);
        }
    }
    if (changed) *changed=replacements;
    return 0;
}

/* Legacy compatibility arithmetic. Keep float32 rounding after each
   addition. Coefficients are the rotated cubic kernel: 81, -9, 1 / 256. */
float tomono_bicubic_green_patch(const int32_t p[49]) {
#define P(r,c) p[((r)+3)*7+(c)+3]
    float v=(float)P(-3,0);
    v=(float)P(0,-3)+v;
    v=(float)P(0,3)+v;
    v=(float)P(3,0)+v;
    v=(float)(-9*P(-1,-2))+v;
    v=(float)(-9*P(-2,-1))+v;
    v=(float)(-9*P(-2,1))+v;
    v=(float)(-9*P(-1,2))+v;
    v=(float)(-9*P(1,2))+v;
    v=v+(float)(-9*P(2,1));
    v=v+(float)(-9*P(2,-1));
    v=v+(float)(-9*P(1,-2));
    v=v+(float)(81*P(0,-1));
    v=v+(float)(81*P(-1,0));
    v=v+(float)(81*P(0,1));
    v=v+(float)(81*P(1,0));
#undef P
    return v*0.00390625f;
}

static int mirror_neighbor(int pos, int delta, int length) {
    int n=pos+delta;
    if (n<0) n=-n;
    if (n>=length) n=2*(length-1)-n;
    return n;
}

typedef struct {
    const uint16_t *input; uint16_t *output; const uint8_t *pattern;
    int width,height,row_offset,col_offset,first_row; unsigned ceiling;
} BayerJob;
static void bicubic_row(void *context,int row) {
    BayerJob *job=context;
    if (row<job->first_row) return;
        for (int col=0;col<job->width;col++) {
            if (tomono_cfa_color(job->pattern,row,col,job->row_offset,job->col_offset)==1) continue;
            int32_t patch[49];
            for (int dy=-3;dy<=3;dy++) {
                int y=job->first_row ? tomono_neighbor(row,dy,job->height) : mirror_neighbor(row,dy,job->height);
                for (int dx=-3;dx<=3;dx++) {
                    int x=job->first_row ? tomono_neighbor(col,dx,job->width) : mirror_neighbor(col,dx,job->width);
                    patch[(dy+3)*7+dx+3]=job->input[(size_t)y*job->width+x];
                }
            }
            float v=tomono_bicubic_green_patch(patch);
            /* Legacy clipping followed by integer truncation. */
            if (v>(float)job->ceiling) v=(float)job->ceiling;
            if (v<0.0f) v=0.0f;
            job->output[(size_t)row*job->width+col]=(uint16_t)v;
        }
}

static int bicubic_plane(const uint16_t *input, size_t input_count,
    uint16_t *output, size_t output_count, int width, int height,
    const uint8_t pattern[4], int row_offset, int col_offset, unsigned ceiling, int first_row) {
    if (ceiling<1 || ceiling>65535) return -1;
    if (!input || !output || !pattern || width<8 || height<8) return -1;
    if ((size_t)height > SIZE_MAX/(size_t)width) return -1;
    size_t count=(size_t)width*(size_t)height;
    if (input_count<count || output_count<count) return -1;
    if (count>SIZE_MAX/sizeof(uint16_t)) return -1;
    uintptr_t a=(uintptr_t)input,b=(uintptr_t)output;
    size_t bytes=count*sizeof(uint16_t);
    if (a>UINTPTR_MAX-bytes || b>UINTPTR_MAX-bytes) return -1;
    if (a < b+bytes && b < a+bytes) return -1;
    int greens=0,reds=0,blues=0;
    for (int i=0;i<4;i++) {
        if (pattern[i]==1) greens++;
        else if (pattern[i]==0) reds++;
        else if (pattern[i]==2) blues++;
        else return -1;
    }
    if (greens!=2 || reds!=1 || blues!=1 || pattern[0]==pattern[1] ||
        pattern[0]==pattern[2] || pattern[1]==pattern[3] ||
        pattern[2]==pattern[3]) return -1;
    if (row_offset<0 || col_offset<0) return -1;
    memcpy(output,input,count*sizeof(*input));
    BayerJob job={input,output,pattern,width,height,row_offset,col_offset,first_row,ceiling};
    run_rows(&job,bicubic_row,height);
    return 0;
}

int tomono_bicubic_green_plane(const uint16_t *input, size_t input_count,
    uint16_t *output, size_t output_count, int width, int height,
    const uint8_t pattern[4], int row_offset, int col_offset) {
    return bicubic_plane(input,input_count,output,output_count,width,height,pattern,row_offset,col_offset,16383,1);
}
int tomono_bicubic_green_plane_range(const uint16_t *input, size_t input_count,
    uint16_t *output, size_t output_count, int width, int height,
    const uint8_t pattern[4], int row_offset, int col_offset, unsigned ceiling) {
    return bicubic_plane(input,input_count,output,output_count,width,height,pattern,row_offset,col_offset,ceiling,0);
}

typedef struct {
    const uint16_t *input; uint16_t *output; const uint8_t *pattern;
    int width,height,pattern_rows,pattern_cols; unsigned ceiling;
} LatticeJob;
static void lattice_row(void *context,int row) {
    LatticeJob *job=context;
    for (int col=0;col<job->width;col++) {
        size_t index=(size_t)row*job->width+col;
        if (job->pattern[(row%job->pattern_rows)*job->pattern_cols+col%job->pattern_cols]==1) { job->output[index]=job->input[index]; continue; }
        double sum=0.0,weights=0.0;int found=0;
        for (int radius=1;radius<=16;radius++) {
            for (int dy=-radius;dy<=radius;dy++) for (int dx=-radius;dx<=radius;dx++) {
                if (dx!=radius && dx!=-radius && dy!=radius && dy!=-radius) continue;
                int y=row+dy,x=col+dx;
                while (y<0 || y>=job->height) { if (y<0) y=-y; if (y>=job->height) y=2*(job->height-1)-y; }
                while (x<0 || x>=job->width) { if (x<0) x=-x; if (x>=job->width) x=2*(job->width-1)-x; }
                if (job->pattern[(y%job->pattern_rows)*job->pattern_cols+x%job->pattern_cols]!=1) continue;
                double weight=1.0/(double)(dx*dx+dy*dy);
                sum+=job->input[(size_t)y*job->width+x]*weight;weights+=weight;found++;
            }
            if (found>=4) break;
        }
        if (weights==0.0) { job->output[index]=0; continue; }
        double value=sum/weights;
        if (value>job->ceiling) value=job->ceiling;
        job->output[index]=(uint16_t)(value+0.5);
    }
}

int tomono_green_lattice_plane(const uint16_t *input, size_t input_count,
    uint16_t *output, size_t output_count, int width, int height,
    const uint8_t *pattern, int pattern_rows, int pattern_cols, unsigned ceiling) {
    if (!input || !output || !pattern || input==output || width<2 || height<2 ||
        pattern_rows<1 || pattern_rows>16 || pattern_cols<1 || pattern_cols>16 ||
        ceiling<1 || ceiling>65535 || (size_t)height>SIZE_MAX/(size_t)width) return -1;
    size_t count=(size_t)height*(size_t)width;
    if (input_count<count || output_count<count) return -1;
    int greens=0;
    for (int i=0;i<pattern_rows*pattern_cols;i++) greens+=(pattern[i]==1);
    if (!greens) return -1;
    LatticeJob job={input,output,pattern,width,height,pattern_rows,pattern_cols,ceiling};
    run_rows(&job,lattice_row,height);
    return 0;
}

typedef struct {
    const uint16_t *input; const uint8_t *pattern; const double *black,*white;
    double *output; int width,height,pr,pc,target,start,phase_y,phase_x,interpolation,strict_green;
} ChannelJob;
static int reflect_index(int p,int count) {
    while (p<0 || p>=count) { if (p<0) p=-p; if (p>=count) p=2*(count-1)-p; }
    return p;
}
static double channel_value(const ChannelJob *j,int y,int x) {
    int phase=(y%j->pr)*j->pc+x%j->pc;
    return ((double)j->input[(size_t)y*j->width+x]-j->black[phase])/(j->white[phase]-j->black[phase]);
}
static double grid_value(const ChannelJob *j,int gy,int gx) {
    int ny=(j->height-j->phase_y+1)/2,nx=(j->width-j->phase_x+1)/2;
    int y=2*reflect_index(gy,ny)+j->phase_y,x=2*reflect_index(gx,nx)+j->phase_x;
    return channel_value(j,y,x);
}
static double pure_green_value(const ChannelJob *j,int row,int col,int dy,int dx) {
    return channel_value(j,reflect_index(row+dy,j->height),reflect_index(col+dx,j->width));
}
static void channel_row(void *context,int local_row) {
    ChannelJob *j=context;int row=j->start+local_row;
    for (int col=0;col<j->width;col++) {
        size_t out=(size_t)local_row*j->width+col;
        if (j->pattern[(row%j->pr)*j->pc+col%j->pc]==j->target) {
            j->output[out]=channel_value(j,row,col);continue;
        }
        if (j->strict_green) {
            static const int near[4][2]={{-1,0},{1,0},{0,-1},{0,1}};
            double value=0,lo=1e30,hi=-1e30;
            for (int k=0;k<4;k++) {
                double v=pure_green_value(j,row,col,near[k][0],near[k][1]);
                value+=v;if (v<lo) lo=v;if (v>hi) hi=v;
            }
            if (j->interpolation==1) value*=0.25;
            else {
                static const int knight[8][2]={{-1,-2},{-2,-1},{-2,1},{-1,2},{1,2},{2,1},{2,-1},{1,-2}};
                value*=81.0;
                for (int k=0;k<8;k++) value-=9.0*pure_green_value(j,row,col,knight[k][0],knight[k][1]);
                for (int k=0;k<4;k++) value+=pure_green_value(j,row,col,3*near[k][0],3*near[k][1]);
                value/=256.0;
                if (value<lo) value=lo;if (value>hi) value=hi;
            }
            j->output[out]=value;
        } else if (j->phase_y>=0) {
            int dy=row-j->phase_y,dx=col-j->phase_x;
            int by=dy<0 ? -1 : dy/2,bx=dx<0 ? -1 : dx/2;
            int fy=(dy%2)!=0,fx=(dx%2)!=0;
            const double cubic[4]={-0.0625,0.5625,0.5625,-0.0625};
            const double linear[4]={0,0.5,0.5,0};
            const double *kernel=j->interpolation==1 ? linear : cubic;
            const double exact[4]={0,1,0,0};const double *wy=fy ? kernel : exact,*wx=fx ? kernel : exact;
            double value=0;
            for (int y=0;y<4;y++) for (int x=0;x<4;x++) {
                if (wy[y]!=0 && wx[x]!=0) value+=wy[y]*wx[x]*grid_value(j,by+y-1,bx+x-1);
            }
            double lo=grid_value(j,by,bx),hi=lo;
            for (int y=0;y<=fy;y++) for (int x=0;x<=fx;x++) {
                double v=grid_value(j,by+y,bx+x);if (v<lo) lo=v;if (v>hi) hi=v;
            }
            if (value<lo) value=lo;if (value>hi) value=hi;
            j->output[out]=value;
        } else {
            double sum=0,weight=0;int found=0;
            for (int radius=1;radius<=16;radius++) {
                for (int dy=-radius;dy<=radius;dy++) for (int dx=-radius;dx<=radius;dx++) {
                    if (abs(dx)!=radius && abs(dy)!=radius) continue;
                    int y=reflect_index(row+dy,j->height),x=reflect_index(col+dx,j->width);
                    if (j->pattern[(y%j->pr)*j->pc+x%j->pc]!=j->target) continue;
                    double w=1.0/(double)(dx*dx+dy*dy);sum+=channel_value(j,y,x)*w;weight+=w;found++;
                }
                if (found>=4) break;
            }
            j->output[out]=(weight>0 ? sum/weight : 0);
        }
    }
}
int tomono_channel_strip(const uint16_t *input,size_t input_count,int width,int height,
    const uint8_t *pattern,int pr,int pc,int target,const double *black,const double *white,
    int start,int rows,double *output,size_t output_count) {
    if (!input || !pattern || !black || !white || !output || width<8 || height<8 ||
        pr<1 || pr>16 || pc<1 || pc>16 || target<0 || target>2 || start<0 || rows<1 ||
        start>height-rows || (size_t)height>SIZE_MAX/(size_t)width ||
        input_count<(size_t)height*width || output_count<(size_t)rows*width) return -1;
    int count=0,py=-1,px=-1;
    for (int y=0;y<pr;y++) for (int x=0;x<pc;x++) {
        int k=y*pc+x;
        if (pattern[k]>2 || !isfinite(black[k]) || !isfinite(white[k]) || black[k]<0 || white[k]<=black[k] || white[k]>65535) return -1;
        if (pattern[k]==target) { count++;py=y;px=x; }
    }
    if (!count) return -1;
    if (pr!=2 || pc!=2 || count!=1) py=px=-1;
    ChannelJob job={input,pattern,black,white,output,width,height,pr,pc,target,start,py,px,0,0};
    run_rows(&job,channel_row,rows);return 0;
}

int tomono_pure_channel_strip(const uint16_t *input,size_t input_count,int width,int height,
    const uint8_t pattern[4],int target,int interpolation,const double black[4],const double white[4],
    int start,int rows,double *output,size_t output_count) {
    if (!input || !pattern || !black || !white || !output || width<8 || height<8 ||
        target<0 || target>2 || interpolation<0 || interpolation>1 || start<0 || rows<1 ||
        start>height-rows || (size_t)height>SIZE_MAX/(size_t)width) return -1;
    size_t count=(size_t)height*width,out_count=(size_t)rows*width;
    if (input_count<count || output_count<out_count || count>SIZE_MAX/sizeof(*input) ||
        out_count>SIZE_MAX/sizeof(*output)) return -1;
    uintptr_t a=(uintptr_t)input,b=(uintptr_t)output;
    size_t input_bytes=count*sizeof(*input),output_bytes=out_count*sizeof(*output);
    if (a>UINTPTR_MAX-input_bytes || b>UINTPTR_MAX-output_bytes ||
        (a<b+output_bytes && b<a+input_bytes)) return -1;
    int counts[3]={0,0,0},py=-1,px=-1;
    for (int k=0;k<4;k++) {
        if (pattern[k]>2 || !isfinite(black[k]) || !isfinite(white[k]) ||
            black[k]<0 || white[k]<=black[k] || white[k]>65535) return -1;
        counts[pattern[k]]++;
        if (pattern[k]==target) { py=k/2;px=k%2; }
    }
    if (counts[0]!=1 || counts[1]!=2 || counts[2]!=1 || pattern[0]==pattern[1] ||
        pattern[0]==pattern[2] || pattern[1]==pattern[3] || pattern[2]==pattern[3]) return -1;
    if (target==1) py=px=-1;
    ChannelJob job={input,pattern,black,white,output,width,height,2,2,target,start,py,px,interpolation,target==1};
    run_rows(&job,channel_row,rows);return 0;
}

/* Green-only directional interpolation. R/B samples never enter estimates or
   gradients. The inverse-square gradient weights adapt locally; no learned
   texture or sharpening. Measured greens remain unchanged. */
static double sample_green(const BayerJob *job,int row,int col,int dy,int dx) {
    int y=mirror_neighbor(row,dy,job->height),x=mirror_neighbor(col,dx,job->width);
    return job->input[(size_t)y*job->width+x];
}
static void edge_row(void *context,int row) {
    BayerJob *job=context;
    for (int col=0;col<job->width;col++) {
        size_t index=(size_t)row*job->width+col;
        if (tomono_cfa_color(job->pattern,row,col,0,0)==1) { job->output[index]=job->input[index]; continue; }
#define G(dy,dx) sample_green(job,row,col,dy,dx)
        double l=G(0,-1),r=G(0,1),u=G(-1,0),d=G(1,0);
        double gh=fabs(l-r)+0.5*(fabs(G(-2,-1)-G(-2,1))+fabs(G(2,-1)-G(2,1)));
        double gv=fabs(u-d)+0.5*(fabs(G(-1,-2)-G(1,-2))+fabs(G(-1,2)-G(1,2)));
        double floor=job->ceiling/4096.0+1.0;
        double wh=1.0/((gh+floor)*(gh+floor)),wv=1.0/((gv+floor)*(gv+floor));
        double v=((l+r)*wh+(u+d)*wv)/(2.0*(wh+wv));
        if (v>job->ceiling) v=job->ceiling;
        job->output[index]=(uint16_t)(v+0.5);
#undef G
    }
}
int tomono_edge_green_plane(const uint16_t *input,size_t input_count,uint16_t *output,size_t output_count,
    int width,int height,const uint8_t pattern[4],unsigned ceiling) {
    if (!input || !output || !pattern || width<8 || height<8 || ceiling<1 || ceiling>65535 ||
        (size_t)height>SIZE_MAX/(size_t)width) return -1;
    size_t count=(size_t)height*width,bytes=count*sizeof(*input);
    if (input_count<count || output_count<count || count>SIZE_MAX/sizeof(*input)) return -1;
    uintptr_t a=(uintptr_t)input,b=(uintptr_t)output;
    if (a>UINTPTR_MAX-bytes || b>UINTPTR_MAX-bytes || (a<b+bytes && b<a+bytes)) return -1;
    if (pattern[0]>2 || pattern[1]>2 || pattern[2]>2 || pattern[3]>2 ||
        ((pattern[0]==1)+(pattern[1]==1)+(pattern[2]==1)+(pattern[3]==1))!=2 ||
        pattern[0]==pattern[1] || pattern[0]==pattern[2] || pattern[1]==pattern[3] || pattern[2]==pattern[3]) return -1;
    BayerJob job={input,output,pattern,width,height,0,0,0,ceiling};
    run_rows(&job,edge_row,height);
    return 0;
}

/* Geometry is sampled once, from linear floating-point sensor units. Invalid
   exterior coordinates become black rather than copied/reflective detail. */
typedef struct {
    const float *input,*xy; uint16_t *output; int width,height,rows; float black;
} RemapJob;
static void remap_row(void *context,int row) {
    RemapJob *job=context;
    for (int col=0;col<job->width;col++) {
        size_t i=(size_t)row*job->width+col;
        float x=job->xy[2*i],y=job->xy[2*i+1];double value=job->black;
        if (isfinite(x) && isfinite(y) && x>=0 && y>=0 && x<=job->width-1 && y<=job->height-1) {
            int x0=(int)x,y0=(int)y;
            double fx=x-x0,fy=y-y0,wx[4],wy[4];
            wx[0]=-.5*fx+fx*fx-.5*fx*fx*fx;
            wx[1]=1-2.5*fx*fx+1.5*fx*fx*fx;
            wx[2]=.5*fx+2*fx*fx-1.5*fx*fx*fx;wx[3]=-.5*fx*fx+.5*fx*fx*fx;
            wy[0]=-.5*fy+fy*fy-.5*fy*fy*fy;
            wy[1]=1-2.5*fy*fy+1.5*fy*fy*fy;
            wy[2]=.5*fy+2*fy*fy-1.5*fy*fy*fy;wy[3]=-.5*fy*fy+.5*fy*fy*fy;
            double sum=0,lo=1e30,hi=-1e30;
            for (int dy=0;dy<4;dy++) {
                int yy=y0+dy-1;if (yy<0) yy=0;if (yy>=job->height) yy=job->height-1;
                for (int dx=0;dx<4;dx++) {
                    int xx=x0+dx-1;if (xx<0) xx=0;if (xx>=job->width) xx=job->width-1;
                    double sample=job->input[(size_t)yy*job->width+xx];
                    if (sample<lo) lo=sample;if (sample>hi) hi=sample;
                    sum+=sample*wx[dx]*wy[dy];
                }
            }
            if (sum<lo) sum=lo;if (sum>hi) sum=hi;
            value=sum+job->black;
        }
        if (!isfinite(value) || value<0) value=0;
        if (value>65535) value=65535;
        job->output[i]=(uint16_t)(value+0.5);
    }
}
int tomono_remap_gray_strip(const float *input,size_t input_count,int width,int height,
    const float *xy,size_t xy_count,uint16_t *output,size_t output_count,int rows,float black) {
    if (!input || !xy || !output || width<2 || height<2 || rows<1 || rows>height ||
        !(black>=0 && black<=65535) || (size_t)height>SIZE_MAX/(size_t)width) return -1;
    size_t count=(size_t)width*height,strip=(size_t)width*rows;
    if (input_count<count || xy_count<strip*2 || output_count<strip) return -1;
    RemapJob job={input,xy,output,width,height,rows,black};run_rows(&job,remap_row,rows);return 0;
}
