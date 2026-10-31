/* Independent same-colour interpolation prototypes, 2026-10-31.
 * Inspired by NEDI covariance duality and WENO polynomial smoothness weighting;
 * neither routine is a reproduction of the named papers. No product/V2 code.
 */
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

static int mirror(int k,int n){
    int p=2*(n-1); if(n<2)return 0; k%=p; if(k<0)k+=p;
    return k<n?k:p-k;
}
static double get(const float *v,int h,int w,int y,int x){
    return v[(size_t)mirror(y,h)*w+mirror(x,w)];
}
static double clamp(double v,double a,double b){return v<a?a:(v>b?b:v);}
static int solve3(double a[3][3],double b[3],double x[3]){
    double m[3][4];
    for(int i=0;i<3;i++){for(int j=0;j<3;j++)m[i][j]=a[i][j];m[i][3]=b[i];}
    for(int i=0;i<3;i++){
        int p=i;for(int j=i+1;j<3;j++)if(fabs(m[j][i])>fabs(m[p][i]))p=j;
        if(fabs(m[p][i])<1e-30)return 0;
        if(p!=i)for(int j=i;j<4;j++){double t=m[p][j];m[p][j]=m[i][j];m[i][j]=t;}
        double d=m[i][i];for(int j=i;j<4;j++)m[i][j]/=d;
        for(int j=0;j<3;j++)if(j!=i){d=m[j][i];for(int k=i;k<4;k++)m[j][k]-=d*m[i][k];}
    }
    for(int i=0;i<3;i++)x[i]=m[i][3];return 1;
}

/* Fit low-resolution four-neighbour prediction, with sum(weights)=1 exactly.
 * The ridge shrinks coefficient *changes* towards the symmetric prior. Training
 * uses real same-colour sites in pass 1 and the derived checkerboard in pass 2.
 */
static double nedi_point(const float *v,int h,int w,int y,int x,int diagonal,double sigma){
    const int ddy[4]={-1,-1,1,1},ddx[4]={-1,1,-1,1};
    const int cdy[4]={-1,1,0,0},cdx[4]={0,0,-1,1};
    const int *dy=diagonal?ddy:cdy,*dx=diagonal?ddx:cdx;
    double A[3][3]={{0}},b[3]={0},sum=0,sum2=0;int n=0;
    for(int oy=-3;oy<=3;oy++)for(int ox=-3;ox<=3;ox++){
        if(diagonal?(!(oy&1)||!(ox&1)):!((oy+ox)&1))continue;
        int cy=y+oy,cx=x+ox;double q[4],mean=0,d[3];
        for(int k=0;k<4;k++){q[k]=get(v,h,w,cy+2*dy[k],cx+2*dx[k]);mean+=.25*q[k];}
        double c=get(v,h,w,cy,cx),r=c-mean;
        for(int k=0;k<3;k++)d[k]=q[k]-q[3];
        for(int i=0;i<3;i++){b[i]+=d[i]*r;for(int j=0;j<3;j++)A[i][j]+=d[i]*d[j];}
        sum+=c;sum2+=c*c;n++;
    }
    double trace=A[0][0]+A[1][1]+A[2][2];
    double ridge=.015*trace+n*(4*sigma*sigma+1e-12);
    for(int i=0;i<3;i++)for(int j=0;j<3;j++)A[i][j]+=ridge*(1+(i==j));
    double d[3]={0},a[4]={.25,.25,.25,.25};
    if(solve3(A,b,d))for(int k=0;k<3;k++){a[k]+=d[k];a[3]-=d[k];}
    /* Keep covariance ill-conditioning from producing arbitrary extrapolation. */
    double total=0;for(int k=0;k<4;k++){a[k]=clamp(a[k],-.125,1.125);total+=a[k];}
    if(fabs(total)<1e-12)for(int k=0;k<4;k++)a[k]=.25;
    else for(int k=0;k<4;k++)a[k]/=total;
    double result=0,prior=0,lo=INFINITY,hi=-INFINITY;
    for(int k=0;k<4;k++){double z=get(v,h,w,y+dy[k],x+dx[k]);result+=a[k]*z;prior+=.25*z;if(z<lo)lo=z;if(z>hi)hi=z;}
    double variance=fmax(0,sum2/n-(sum/n)*(sum/n));
    double strength=variance/(variance+16*sigma*sigma+1e-12);
    return clamp(prior+strength*(result-prior),lo,hi);
}

/* Two overlapping quadratic polynomials at a midpoint. Equal smoothness gives
 * [-1,9,9,-1]/16, but unequal smoothness suppresses the rougher stencil.
 * Direction weights additionally select the lower-variation same-colour line.
 */
static double weno_point(const float *v,int h,int w,int y,int x,int diagonal,double sigma){
    const int ay[6]={0,1,1,1,2,2},ax[6]={1,0,2,-2,1,-1};
    const int by[6]={1,1,1,1,3,3},bx[6]={1,-1,3,-3,1,-1};
    const int *dy=diagonal?by:ay,*dx=diagonal?bx:ax;
    double total=0,estimate=0,eps=4*sigma*sigma+1e-12;
    for(int k=0;k<6;k++){
        double a=get(v,h,w,y-3*dy[k],x-3*dx[k]);
        double b=get(v,h,w,y-dy[k],x-dx[k]);
        double c=get(v,h,w,y+dy[k],x+dx[k]);
        double d=get(v,h,w,y+3*dy[k],x+3*dx[k]);
        double length=dy[k]*dy[k]+dx[k]*dx[k];
        double slope=(c-b)*(c-b)/length;
        double u=a-2*b+c,z=b-2*c+d;
        double beta0=slope+(13.0/12)*u*u/(length*length);
        double beta1=slope+(13.0/12)*z*z/(length*length);
        double t0=1/((beta0+eps)*(beta0+eps)),t1=1/((beta1+eps)*(beta1+eps));
        double q0=(-a+6*b+3*c)/8,q1=(3*b+6*c-d)/8;
        double q=(t0*q0+t1*q1)/(t0+t1);
        double lo=fmin(fmin(a,b),fmin(c,d)),hi=fmax(fmax(a,b),fmax(c,d));
        q=clamp(q,lo,hi);
        double smooth=fmin(beta0,beta1)+eps;
        double weight=1/(length*smooth*sqrt(smooth));
        total+=weight;estimate+=weight*q;
    }
    return estimate/total;
}

int detail_reconstruct(const float *input,int h,int w,int phase_y,int phase_x,
                       int green,int method,double sigma,float *out){
    if(!input||!out||h<8||w<8||method<0||method>1)return 1;
    size_t count=(size_t)h*w;memcpy(out,input,count*sizeof(float));
    float *stage=NULL;const float *source=input;
    if(!green){
        stage=(float*)malloc(count*sizeof(float));if(!stage)return 2;
        memcpy(stage,input,count*sizeof(float));
        for(int y=1-phase_y;y<h;y+=2)for(int x=1-phase_x;x<w;x+=2)
            stage[(size_t)y*w+x]=(float)(method?nedi_point(input,h,w,y,x,1,sigma):weno_point(input,h,w,y,x,1,sigma));
        source=stage;memcpy(out,stage,count*sizeof(float));
    }
    int known_parity=(phase_y+phase_x)&1;
    for(int y=0;y<h;y++)for(int x=0;x<w;x++)if(((y+x)&1)!=known_parity)
        out[(size_t)y*w+x]=(float)(method?nedi_point(source,h,w,y,x,0,sigma):weno_point(source,h,w,y,x,0,sigma));
    free(stage);return 0;
}
