// SPDX-License-Identifier: Apache-2.0
// Exact model tensor semantics: RGB float -> half-pixel bilinear, antialias=false,
// align_corners=false -> ImageNet mean/std. No uint8 intermediate resize.
#include <vector>
#include <string>
#include "nvdspreprocess_interface.h"
#include "detector_schedule.hpp"
#include <cuda_runtime.h>
#include <cmath>
#include <cstdio>

struct CustomCtx { cudaStream_t stream{}; unsigned width=0, height=0, capacity=0; };

__global__ void tensor_kernel(const unsigned char* rgba, unsigned pitch,
    unsigned sw, unsigned sh, float* output, unsigned dw, unsigned dh) {
  unsigned index=blockIdx.x*blockDim.x+threadIdx.x;
  if(index>=dw*dh) return;
  unsigned x=index%dw,y=index/dw;
  float sx=fmaxf(0.f,(x+.5f)*float(sw)/dw-.5f);
  float sy=fmaxf(0.f,(y+.5f)*float(sh)/dh-.5f);
  unsigned x0=min(unsigned(sx),sw-1),x1=min(x0+1,sw-1);
  unsigned y0=min(unsigned(sy),sh-1),y1=min(y0+1,sh-1);
  float ax=sx-x0,ay=sy-y0;
  const float mean[3]={.485f,.456f,.406f},stddev[3]={.229f,.224f,.225f};
  for(unsigned c=0;c<3;c++) {
    float a=rgba[y0*pitch+x0*4+c]*(1-ax)+rgba[y0*pitch+x1*4+c]*ax;
    float b=rgba[y1*pitch+x0*4+c]*(1-ax)+rgba[y1*pitch+x1*4+c]*ax;
    output[c*dw*dh+index]=((a*(1-ay)+b*ay)/255.f-mean[c])/stddev[c];
  }
}

// Top-left letterbox and RGB 0..1 used by the NVIDIA TrafficCamNet model.
__global__ void trafficcam_tensor_kernel(const unsigned char* rgba, unsigned pitch,
    unsigned sw, unsigned sh, float* output, unsigned dw, unsigned dh) {
  unsigned index=blockIdx.x*blockDim.x+threadIdx.x;
  if(index>=dw*dh) return;
  const unsigned x=index%dw,y=index/dw;
  // Match gst-nvdspreprocess ROI metadata: it rounds source extents down
  // to even pixels and truncates the aspect-preserving destination extent.
  sw &= ~1u; sh &= ~1u;
  if(!sw || !sh) { for(unsigned c=0;c<3;c++) output[c*dw*dh+index]=0.f; return; }
  const double hdest=double(dw)*sh/sw, wdest=double(dh)*sw/sh;
  const unsigned rw=hdest<=dh ? dw : max(1u,unsigned(wdest));
  const unsigned rh=hdest<=dh ? max(1u,unsigned(hdest)) : dh;
  if(x>=rw || y>=rh) { for(unsigned c=0;c<3;c++) output[c*dw*dh+index]=0.f; return; }
  const float sx=fmaxf(0.f,(x+.5f)*float(sw)/rw-.5f);
  const float sy=fmaxf(0.f,(y+.5f)*float(sh)/rh-.5f);
  const unsigned x0=min(unsigned(sx),sw-1),x1=min(x0+1,sw-1);
  const unsigned y0=min(unsigned(sy),sh-1),y1=min(y0+1,sh-1);
  const float ax=sx-x0,ay=sy-y0;
  for(unsigned c=0;c<3;c++) {
    const float a=rgba[y0*pitch+x0*4+c]*(1-ax)+rgba[y0*pitch+x1*4+c]*ax;
    const float b=rgba[y1*pitch+x0*4+c]*(1-ax)+rgba[y1*pitch+x1*4+c]*ax;
    output[c*dw*dh+index]=(a*(1-ay)+b*ay)/255.f;
  }
}

extern "C" CustomCtx* initLib(CustomInitParams params) {
  const auto& s=params.tensor_params.network_input_shape;
  if(s.size()!=4 || s[1]!=3 || s[0]<=0 || s[2]<=0 || s[3]<=0 ||
     params.tensor_params.data_type!=NvDsDataType_FP32 ||
     params.tensor_params.network_input_order!=NvDsPreProcessNetworkInputOrder_kNCHW) return nullptr;
  auto* ctx=new CustomCtx; ctx->height=s[2];ctx->width=s[3];ctx->capacity=s[0];
  if(cudaStreamCreateWithFlags(&ctx->stream,cudaStreamNonBlocking)!=cudaSuccess) {delete ctx;return nullptr;}
  return ctx;
}
extern "C" void deInitLib(CustomCtx* ctx) {
  if(ctx) {cudaStreamDestroy(ctx->stream);delete ctx;}
}
// The plugin establishes ROI metadata and owns pool lifetimes. Our tensor
// callback samples unit.input_surf_params directly; converted uint8 pixels
// would add a quantization absent from RF-DETR's tensor resize reference.
extern "C" NvDsPreProcessStatus CustomTransformation(
    NvBufSurface*, NvBufSurface*, CustomTransformParams&) { return NVDSPREPROCESS_SUCCESS; }

static NvDsPreProcessStatus prepare_tensor(bool trafficcam, CustomCtx* ctx,
    NvDsPreProcessBatch* batch,NvDsPreProcessCustomBuf*& buf,
    CustomTensorParams& params,NvDsPreProcessAcquirer* acquirer) {
  if(!ctx || !batch || batch->units.empty() || batch->units.size()>ctx->capacity) return NVDSPREPROCESS_INVALID_PARAMS;
  // Keep video buffers in the plugin's ordered output queue. An absent tensor
  // makes nvinfer forward the frame without inference (bInferDone stays false),
  // allowing native MV3DT's visual tracker to run on every admitted frame.
  std::vector<size_t> selected;
  params.seq_params.roi_vector.clear();
  for(size_t n=0;n<batch->units.size();++n) {
    auto* frame=batch->units[n].roi_meta.frame_meta;
    const auto* schedule=frame?city::detector_schedule(frame):nullptr;
    if(!schedule||schedule->selected) {
      selected.push_back(n);params.seq_params.roi_vector.push_back(batch->units[n].roi_meta);
    }
  }
  buf=nullptr;
  if(selected.empty())return NVDSPREPROCESS_TENSOR_NOT_READY;
  buf=acquirer->acquire(); if(!buf) return NVDSPREPROCESS_RESOURCE_ERROR;
  auto fail=[&]() {acquirer->release(buf);buf=nullptr;return NVDSPREPROCESS_CUDA_ERROR;};
  for(size_t n=0;n<selected.size();n++) {
    const auto* surface=batch->units[selected[n]].input_surf_params;
    if(!surface || surface->colorFormat!=NVBUF_COLOR_FORMAT_RGBA || !surface->dataPtr ||
       !surface->width || !surface->height) {
      std::fprintf(stderr,"City preprocess requires linear GPU RGBA input surfaces\n");return fail();
    }
    float* output=static_cast<float*>(buf->memory_ptr)+n*3*ctx->width*ctx->height;
    if(trafficcam) trafficcam_tensor_kernel<<<(ctx->width*ctx->height+255)/256,256,0,ctx->stream>>>(
        static_cast<unsigned char*>(surface->dataPtr),surface->pitch,
        surface->width,surface->height,output,ctx->width,ctx->height);
    else tensor_kernel<<<(ctx->width*ctx->height+255)/256,256,0,ctx->stream>>>(
        static_cast<unsigned char*>(surface->dataPtr),surface->pitch,
        surface->width,surface->height,output,ctx->width,ctx->height);
    if(cudaGetLastError()!=cudaSuccess) return fail();
  }
  if(cudaStreamSynchronize(ctx->stream)!=cudaSuccess) return fail();
  params.params.buffer_size=selected.size()*3*ctx->width*ctx->height*sizeof(float);
  params.params.network_input_shape[0]=selected.size();
  return NVDSPREPROCESS_SUCCESS;
}

extern "C" NvDsPreProcessStatus CustomTensorPreparation(CustomCtx* ctx,
    NvDsPreProcessBatch* batch,NvDsPreProcessCustomBuf*& buf,
    CustomTensorParams& params,NvDsPreProcessAcquirer* acquirer) {
  return prepare_tensor(false,ctx,batch,buf,params,acquirer);
}
extern "C" NvDsPreProcessStatus CustomTrafficCamTensorPreparation(CustomCtx* ctx,
    NvDsPreProcessBatch* batch,NvDsPreProcessCustomBuf*& buf,
    CustomTensorParams& params,NvDsPreProcessAcquirer* acquirer) {
  return prepare_tensor(true,ctx,batch,buf,params,acquirer);
}
