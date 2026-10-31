/* Production port of frozen D10/D11 same-colour detail kernels.
 * All formulas are inspired_not_reproduction, not a named paper reproduction.
 */
#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

unsigned tomono_detail_version(void){return 0x100u;}

static int mirror(int k,int n){int p=2*(n-1);k%=p;if(k<0)k+=p;return k<n?k:p-k;}
static double get(const float *a,int h,int w,int y,int x){return a[(size_t)mirror(y,h)*w+mirror(x,w)];}
static double clip(double x,double lo,double hi){return x<lo?lo:(x>hi?hi:x);}
static double cubic(double a,double b,double c,double d){return (-a+9*b+9*c-d)/16;}

/* Directions share the same midpoint and symmetric, sum-one stencils. */
static void candidates(const float *a,int h,int w,int y,int x,int scale,
                       double *lh,double *lv,double *kh,double *kv,
                       double *lo,double *hi){
    double hs[4],vs[4];const int offset[4]={-3,-1,1,3};
    *lo=INFINITY;*hi=-INFINITY;
    for(int i=0;i<4;i++){
        hs[i]=get(a,h,w,y,x+offset[i]*scale);
        vs[i]=get(a,h,w,y+offset[i]*scale,x);
        *lo=fmin(*lo,fmin(hs[i],vs[i]));*hi=fmax(*hi,fmax(hs[i],vs[i]));
    }
    *lh=.5*(hs[1]+hs[2]);*lv=.5*(vs[1]+vs[2]);
    *kh=(hs[1]+hs[2]-hs[0]-hs[3])/16;
    *kv=(vs[1]+vs[2]-vs[0]-vs[3])/16;
}

static double green_ar(const float *a,int h,int w,int y,int x,int noiseaware,double sigma){
    double lh[24],lv[24],kh[24],kv[24],truth[24],weight[24];
    double curvature=0,total_weight=0;int n=0;
    for(int oy=-3;oy<=3;oy++)for(int ox=-3;ox<=3;ox++)if((oy+ox)&1){
        double lo,hi;
        candidates(a,h,w,y+oy,x+ox,2,&lh[n],&lv[n],&kh[n],&kv[n],&lo,&hi);
        truth[n]=get(a,h,w,y+oy,x+ox);
        weight[n]=1/(1+.25*(oy*oy+ox*ox));
        curvature+=weight[n]*.5*(kh[n]*kh[n]+kv[n]*kv[n]);
        total_weight+=weight[n];n++;
    }
    double s2=sigma*sigma;
    double beta=1;
    if(noiseaware&&sigma>0){
        double energy=curvature/total_weight;
        beta=clip((energy-s2/64)/(energy+1e-14),0,1);
    }
    double dd=0,dr=0,base_error=0,ds[24],rs[24];
    for(int i=0;i<n;i++){
        double qh=lh[i]+beta*kh[i],qv=lv[i]+beta*kv[i];
        ds[i]=qv-qh;rs[i]=truth[i]-.5*(qh+qv);
        dd+=weight[i]*ds[i]*ds[i];dr+=weight[i]*ds[i]*rs[i];
        base_error+=weight[i]*rs[i]*rs[i];
    }
    double ridge=.01*dd+total_weight*1e-12;
    double den=dd+ridge,delta=clip(dr/den,-.5,.5),loo_error=0;
    for(int i=0;i<n;i++){
        double leverage=weight[i]*ds[i]*ds[i]/den;
        /* Fixed-design linear-ridge PRESS uses the unclipped fit. Stabilize its
         * denominator and bound the final mix. Since CFA supports overlap and
         * X is data-dependent, this is a reliability surrogate, not independent
         * source-sample held-out validation. */
        double residual=rs[i]-(dr/den)*ds[i];
        double leave_one_out=residual/fmax(1-leverage,.05);
        loo_error+=weight[i]*leave_one_out*leave_one_out;
    }
    double reliability=clip((base_error-loo_error)/(base_error+total_weight*1e-14),0,1);
    if(noiseaware&&sigma>0){
        /* With beta-scaled curvature, Var(q)=sigma2*(.5+beta/8+beta2/64).
         * H/V noise is disjoint, hence Var(qV-qH)=2*Var(q). */
        double noise_difference=2*s2*(.5+beta/8+beta*beta/64);
        double energy=dd/total_weight;
        reliability*=clip((energy-noise_difference)/(energy+1e-14),0,1);
    }
    double hl,vl,hk,vk,lo,hi;
    candidates(a,h,w,y,x,1,&hl,&vl,&hk,&vk,&lo,&hi);
    double qh=hl+beta*hk,qv=vl+beta*vk;
    double alpha=clip(.5+reliability*delta,0,1);
    return clip((1-alpha)*qh+alpha*qv,lo,hi);
}

/* Same-colour regular R/B lattice fallback: bounded separable Catmull midpoint.
 * It is intentionally identical for the two G-only AR experiments. */
static double regular_cubic(const float *a,int h,int w,int y,int x,int py,int px){
    int dy=(y-py)&1,dx=(x-px)&1;
    if(!dy&&!dx)return get(a,h,w,y,x);
    const int offset[4]={-3,-1,1,3};double rows[4],lo=INFINITY,hi=-INFINITY;
    if(!dy){
        double s[4];for(int k=0;k<4;k++){s[k]=get(a,h,w,y,x+offset[k]);lo=fmin(lo,s[k]);hi=fmax(hi,s[k]);}
        return clip(cubic(s[0],s[1],s[2],s[3]),lo,hi);
    }
    if(!dx){
        double s[4];for(int k=0;k<4;k++){s[k]=get(a,h,w,y+offset[k],x);lo=fmin(lo,s[k]);hi=fmax(hi,s[k]);}
        return clip(cubic(s[0],s[1],s[2],s[3]),lo,hi);
    }
    for(int j=0;j<4;j++){
        double s[4];for(int k=0;k<4;k++){s[k]=get(a,h,w,y+offset[j],x+offset[k]);lo=fmin(lo,s[k]);hi=fmax(hi,s[k]);}
        rows[j]=cubic(s[0],s[1],s[2],s[3]);
    }
    return clip(cubic(rows[0],rows[1],rows[2],rows[3]),lo,hi);
}

/* Spectral range limiter. Keep a smooth local extremum when supported by nearby
 * measured extrema, but forbid a new local range. Constant plateaus are exact,
 * so sinc side lobes outside the local edge neighbourhood cannot survive.
 * All tests use selected samples, never reconstructed gradients or other CFA.
 */
static double spectral_guard(const float *a,int h,int w,int y,int x,int green,int py,int px,double proposed,double sigma){
    double lo=INFINITY,hi=-INFINITY,sum=0,sum2=0;int n=0;
    int radius=green?3:4;
    for(int oy=-radius;oy<=radius;oy++)for(int ox=-radius;ox<=radius;ox++){
        int yy=y+oy,xx=x+ox;
        int measured=green?((((yy+xx)&1)==((py+px)&1))):(((yy&1)==py)&&((xx&1)==px));
        if(!measured)continue;
        double z=get(a,h,w,yy,xx);lo=fmin(lo,z);hi=fmax(hi,z);sum+=z;sum2+=z*z;n++;
    }
    double bounded=clip(proposed,lo,hi);
    /* Reject unobserved high-frequency noise amplification, with known sigma
     * only. With sigma0 there is no implicit noise/texture discrimination. */
    if(sigma>0){
        double variance=fmax(0,sum2/n-(sum/n)*(sum/n));
        double reliability=clip((variance-sigma*sigma)/(variance+1e-14),0,1);
        double pilot;
        if(green)pilot=.25*(get(a,h,w,y-1,x)+get(a,h,w,y+1,x)+get(a,h,w,y,x-1)+get(a,h,w,y,x+1));
        else pilot=regular_cubic(a,h,w,y,x,py,px);
        bounded=clip(pilot+reliability*(bounded-pilot),lo,hi);
    }
    return bounded;
}

int tomono_detail_reconstruct(const float *input,int h,int w,int py,int px,int green,
                           int method,double sigma,const float *spectral,float *out){
    if(!input||!out||h<8||w<8||method<0||method>2||(method==2&&!spectral))return 1;
    memcpy(out,input,(size_t)h*w*sizeof(float));
    for(int y=0;y<h;y++)for(int x=0;x<w;x++){
        int measured=green?(((y+x)&1)==((py+px)&1)):(((y&1)==py)&&((x&1)==px));
        if(measured)continue;
        if(method==2)out[(size_t)y*w+x]=(float)spectral_guard(input,h,w,y,x,green,py,px,spectral[(size_t)y*w+x],sigma);
        else if(green)out[(size_t)y*w+x]=(float)green_ar(input,h,w,y,x,method==1,sigma);
        else out[(size_t)y*w+x]=(float)regular_cubic(input,h,w,y,x,py,px);
    }
    return 0;
}
