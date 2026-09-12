// Stable C ABI: Python owns contiguous double buffers; no allocation crosses ABI.
#include <cmath>
#include <algorithm>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C"
#endif
API int mechanics_abi_version() { return 1; }
API int assemble(int n, double length, double rigidity, int beam, double* k, double* g) {
    if(n<1 || n>160 || !(length>0) || !(rigidity>0) || !k || !g) return 1;
    const double h=length/n; const int size=beam?2*(n+1):n+1;
    std::fill(k,k+size*size,0.); std::fill(g,g+size*size,0.);
    const double kb[16]={12,6*h,-12,6*h,6*h,4*h*h,-6*h,2*h*h,-12,-6*h,12,-6*h,6*h,2*h*h,-6*h,4*h*h};
    const double kg[16]={36,3*h,-36,3*h,3*h,4*h*h,-3*h,-h*h,-36,-3*h,36,-3*h,3*h,-h*h,-3*h,4*h*h};
    for(int e=0;e<n;e++) for(int i=0;i<(beam?4:2);i++) for(int j=0;j<(beam?4:2);j++) {
        int offset=(e*(beam?2:1)+i)*size+e*(beam?2:1)+j;
        k[offset]+=beam ? rigidity/(h*h*h)*kb[4*i+j] : rigidity/h*(i==j?1:-1);
        if(beam) g[offset]+=kg[4*i+j]/(30*h);
    }
    return 0;
}
static double load(double t,double duration,double maximum) {
    double s=std::min(1.,std::max(0.,t/duration));
    return maximum*s*s*s*(10-15*s+6*s*s);
}
// parameters: dt,duration,maximum,hold,damping,E,nu,sy,Q,b,onset,Gf,damage_enabled,last_reaction.
// buffers: x0,x,v,acc,mass,A0,L0,hp,ep,d,he,stress,lateral,force,old_length,work,internal.
API int rod_advance(int n,int count,int start,const double* p,double** a,double* out) {
    if(n<1 || n>160 || count<0 || !p || !a || !out || !(p[0]>0)) return 1;
    auto x0=a[0],x=a[1],v=a[2],acc=a[3],mass=a[4],area=a[5],ref=a[6],hp=a[7],ep=a[8],d=a[9],he=a[10],stress=a[11],lat=a[12],force=a[13],old=a[14],work=a[15],internal=a[16];
    const double dt=p[0],young=p[5],nu=p[6],sy=p[7],q=p[8],b=p[9];
    double ew=0,dw=0,last=p[13];
    out[0]=start;out[1]=-1;out[2]=0;out[3]=0;
    for(int step=0;step<count;step++) {
        int index=start+step+1;
        double prev=load((index-1)*dt,p[1],p[2]),u=load(index*dt,p[1],p[2]);
        if(p[3]<1e20) prev=u=p[3];
        for(int i=0;i<=n;i++){v[i]+=.5*dt*acc[i];x[i]+=dt*v[i];internal[i]=0;}
        x[0]=x0[0];x[n]=x0[n]+u;v[0]=0;v[n]=(u-prev)/dt;
        for(int e=0;e<n;e++) {
            double len=x[e+1]-x[e],stretch=len/ref[e],f=0;
            if(stretch<=.02){out[0]=index;out[1]=e;out[2]=ew;out[3]=dw;return 0;}
            if(d[e]<1) {
                double trial=young*(std::log(stretch)-hp[e]),flow=sy+q*(1-std::exp(-b*ep[e])),dp=0;
                if(std::abs(trial)>flow) {
                    dp=(std::abs(trial)-flow)/(young+q*b*std::exp(-b*ep[e]));
                    for(int k=0;k<6;k++){double ex=std::exp(-b*(ep[e]+dp));dp+=(std::abs(trial)-young*dp-sy-q*(1-ex))/(young+q*b*ex);}
                    dp=std::max(0.,dp);
                }
                hp[e]+=(trial>=0?1:-1)*dp; ep[e]+=dp;
                he[e]=std::log(stretch)-hp[e];double tau=young*he[e];
                if(p[12] && ep[e]>p[10] && tau>0) {
                    double y0=sy+q*(1-std::exp(-b*p[10])),yn=sy+q*(1-std::exp(-b*ep[e]));
                    d[e]=std::min(1.,std::max(d[e],1-y0/yn*std::max(0.,1-ref[e]*(ep[e]-p[10])/(2*p[11]/y0))));
                }
                lat[e]=-.5*hp[e]-nu*he[e];stress[e]=tau*(1-d[e])/std::exp((1-2*nu)*he[e]);
                f=area[e]*tau*(1-d[e])/stretch;
            } else stress[e]=0;
            work[e]+=.5*(force[e]+f)*(len-old[e]);old[e]=len;force[e]=f;internal[e]-=f;internal[e+1]+=f;
        }
        ew+=.5*(last+internal[n])*(u-prev);last=internal[n];
        for(int i=1;i<n;i++){dw+=p[4]*mass[i]*v[i]*v[i]*dt;acc[i]=-internal[i]/mass[i]-p[4]*v[i];}
        acc[0]=acc[n]=0;
        for(int i=0;i<=n;i++)v[i]+=.5*dt*acc[i];
    }
    out[0]=start+count;out[2]=ew;out[3]=dw;return 0;
}
