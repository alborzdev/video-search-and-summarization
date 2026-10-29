// SPDX-License-Identifier: Apache-2.0
// Compile in the pinned DeepStream build container. Calls the production kernel.
#include "../src/rfdetr_preprocess.cu"
#include "rfdetr_core.hpp"
#include <cassert>
#include <vector>
#include <iostream>
int main() {
  constexpr unsigned sw=19,sh=11,dw=13,dh=17,pitch=sw*4+12;
  std::vector<unsigned char> image(pitch*sh,0);
  for(unsigned y=0;y<sh;y++)for(unsigned x=0;x<sw;x++)for(unsigned c=0;c<4;c++)
    image[y*pitch+4*x+c]=(y*17+x*13+c*71)%256;
  unsigned char* input=nullptr;float* output=nullptr;
  assert(cudaMalloc(&input,image.size())==cudaSuccess);
  assert(cudaMalloc(&output,3*dw*dh*sizeof(float))==cudaSuccess);
  assert(cudaMemcpy(input,image.data(),image.size(),cudaMemcpyHostToDevice)==cudaSuccess);
  tensor_kernel<<<(dw*dh+255)/256,256>>>(input,pitch,sw,sh,output,dw,dh);
  assert(cudaDeviceSynchronize()==cudaSuccess);
  std::vector<float> actual(3*dw*dh);
  assert(cudaMemcpy(actual.data(),output,actual.size()*sizeof(float),cudaMemcpyDeviceToHost)==cudaSuccess);
  float maximum_error=0;
  for(unsigned y=0;y<dh;y++)for(unsigned x=0;x<dw;x++)for(unsigned c=0;c<3;c++) {
    float sx=std::max(0.f,(x+.5f)*float(sw)/dw-.5f),sy=std::max(0.f,(y+.5f)*float(sh)/dh-.5f);
    unsigned x0=std::min(unsigned(sx),sw-1),x1=std::min(x0+1,sw-1);
    unsigned y0=std::min(unsigned(sy),sh-1),y1=std::min(y0+1,sh-1);
    float ax=sx-x0,ay=sy-y0;
    float a=image[y0*pitch+4*x0+c]*(1-ax)+image[y0*pitch+4*x1+c]*ax;
    float b=image[y1*pitch+4*x0+c]*(1-ax)+image[y1*pitch+4*x1+c]*ax;
    float expected=city::normalize_rgb(a*(1-ay)+b*ay,c);
    maximum_error=std::max(maximum_error,std::abs(expected-actual[c*dw*dh+y*dw+x]));
  }
  assert(maximum_error<3e-6);
  trafficcam_tensor_kernel<<<(dw*dh+255)/256,256>>>(input,pitch,sw,sh,output,dw,dh);
  assert(cudaDeviceSynchronize()==cudaSuccess);
  assert(cudaMemcpy(actual.data(),output,actual.size()*sizeof(float),cudaMemcpyDeviceToHost)==cudaSuccess);
  constexpr unsigned tw=sw & ~1u, th=sh & ~1u;
  const double hdest=double(dw)*th/tw,wdest=double(dh)*tw/th;
  const unsigned rw=hdest<=dh ? dw : std::max(1u,unsigned(wdest));
  const unsigned rh=hdest<=dh ? std::max(1u,unsigned(hdest)) : dh;
  float traffic_error=0;
  for(unsigned y=0;y<dh;y++)for(unsigned x=0;x<dw;x++)for(unsigned c=0;c<3;c++) {
    float expected=0.f;
    if(x<rw && y<rh) {
      const float sx=std::max(0.f,(x+.5f)*float(tw)/rw-.5f),sy=std::max(0.f,(y+.5f)*float(th)/rh-.5f);
      const unsigned x0=std::min(unsigned(sx),tw-1),x1=std::min(x0+1,tw-1),y0=std::min(unsigned(sy),th-1),y1=std::min(y0+1,th-1);
      const float ax=sx-x0,ay=sy-y0;
      const float a=image[y0*pitch+4*x0+c]*(1-ax)+image[y0*pitch+4*x1+c]*ax;
      const float b=image[y1*pitch+4*x0+c]*(1-ax)+image[y1*pitch+4*x1+c]*ax;
      expected=(a*(1-ay)+b*ay)/255.f;
    }
    traffic_error=std::max(traffic_error,std::abs(expected-actual[c*dw*dh+y*dw+x]));
  }
  cudaFree(input);cudaFree(output);
  assert(traffic_error<3e-6);
  std::cout<<"TrafficCamNet RGB letterbox parity max error "<<traffic_error<<'\n';
  std::cout<<"Production CUDA preprocessing parity max error "<<maximum_error<<'\n';
}
