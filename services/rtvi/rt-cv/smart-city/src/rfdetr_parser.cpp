// SPDX-License-Identifier: Apache-2.0
#include "nvdsinfer_custom_impl.h"
#include "rfdetr_core.hpp"
#include <cstring>
#include <iostream>
extern "C" bool NvDsInferParseCityRFDETR(
    const std::vector<NvDsInferLayerInfo>& layers,
    const NvDsInferNetworkInfo& network,
    const NvDsInferParseDetectionParams& params,
    std::vector<NvDsInferObjectDetectionInfo>& objects) {
  const NvDsInferLayerInfo *boxes=nullptr, *labels=nullptr;
  for (const auto& layer : layers) {
    if (!std::strcmp(layer.layerName, "dets")) boxes=&layer;
    if (!std::strcmp(layer.layerName, "labels")) labels=&layer;
  }
  if (!boxes || !labels || boxes->dataType != FLOAT || labels->dataType != FLOAT) {
    std::cerr << "RF-DETR parser requires FP32 dets and labels outputs\n"; return false;
  }
  const auto q = boxes->inferDims.numElements / 4;
  if (!q || boxes->inferDims.numElements % 4 || labels->inferDims.numElements % q) return false;
  const auto classes = labels->inferDims.numElements / q;
  float threshold = .35f;
  if (!params.perClassPreclusterThreshold.empty()) threshold = *std::min_element(
      params.perClassPreclusterThreshold.begin(), params.perClassPreclusterThreshold.end());
  try {
    for (const auto& d : city::decode_for_tracking(static_cast<const float*>(boxes->buffer),
        static_cast<const float*>(labels->buffer), q, classes,
        network.width, network.height, threshold)) {
      if (d.class_id < params.perClassPreclusterThreshold.size() &&
          d.score < params.perClassPreclusterThreshold[d.class_id]) continue;
      NvDsInferObjectDetectionInfo object{};
      object.classId=d.class_id; object.detectionConfidence=d.score;
      object.left=d.x; object.top=d.y; object.width=d.width; object.height=d.height;
      objects.push_back(object);
    }
  } catch (const std::exception& e) { std::cerr << e.what() << '\n'; return false; }
  return true;
}
CHECK_CUSTOM_PARSE_FUNC_PROTOTYPE(NvDsInferParseCityRFDETR);

// NVIDIA's DDETR TAO contract: argmax per query, sigmoid, descending top 200.
// Native traffic classes are background, two-wheeler, car, person, road sign.
// Map the coarse two-wheeler label without claiming a bicycle or motorcycle.
extern "C" bool NvDsInferParseCityTrafficCamNet(
    const std::vector<NvDsInferLayerInfo>& layers,
    const NvDsInferNetworkInfo& network,
    const NvDsInferParseDetectionParams& params,
    std::vector<NvDsInferObjectDetectionInfo>& objects) {
  const NvDsInferLayerInfo *boxes=nullptr, *logits=nullptr;
  for (const auto& layer : layers) {
    if (!layer.layerName) continue;
    if (!std::strcmp(layer.layerName,"pred_boxes")) boxes=&layer;
    if (!std::strcmp(layer.layerName,"pred_logits")) logits=&layer;
  }
  if (!boxes || !logits || boxes->dataType != FLOAT || logits->dataType != FLOAT ||
      !boxes->buffer || !logits->buffer || !network.width || !network.height ||
      params.perClassPreclusterThreshold.size() != 7 ||
      boxes->inferDims.numElements % 4 || !boxes->inferDims.numElements ||
      logits->inferDims.numElements != boxes->inferDims.numElements/4*5) return false;
  struct Candidate { float score; unsigned native_class; size_t query; };
  const auto q=boxes->inferDims.numElements/4;
  const auto* b=static_cast<const float*>(boxes->buffer);
  const auto* l=static_cast<const float*>(logits->buffer);
  std::vector<Candidate> candidates;
  candidates.reserve(q);
  for (size_t i=0;i<q;++i) {
    const auto* begin=l+i*5;
    const auto* best=std::max_element(begin,begin+5);
    if (!std::isfinite(*best)) continue;
    const auto native=unsigned(best-begin);
    const auto score=city::sigmoid(*best);
    // The supplied config uses one common threshold for all native classes.
    const auto threshold=native==1 ? params.perClassPreclusterThreshold[6] :
        native==2 ? params.perClassPreclusterThreshold[2] :
        native==3 ? params.perClassPreclusterThreshold[0] :
        *std::min_element(params.perClassPreclusterThreshold.begin(),params.perClassPreclusterThreshold.end());
    if (score>=threshold) candidates.push_back({score,native,i});
  }
  std::stable_sort(candidates.begin(),candidates.end(),[](const auto& a,const auto& b){return a.score>b.score;});
  if (candidates.size()>200) candidates.resize(200);
  for (const auto& c:candidates) {
    if (c.native_class!=1 && c.native_class!=2 && c.native_class!=3) continue;
    const float* rect=b+c.query*4;
    if (!std::isfinite(rect[0]) || !std::isfinite(rect[1]) || !std::isfinite(rect[2]) || !std::isfinite(rect[3])) continue;
    const float x1=std::clamp((rect[0]-rect[2]/2)*network.width,0.f,float(network.width-1));
    const float x2=std::clamp((rect[0]+rect[2]/2)*network.width,0.f,float(network.width-1));
    const float y1=std::clamp((rect[1]-rect[3]/2)*network.height,0.f,float(network.height-1));
    const float y2=std::clamp((rect[1]+rect[3]/2)*network.height,0.f,float(network.height-1));
    if (x2<=x1 || y2<=y1) continue;
    NvDsInferObjectDetectionInfo object{};
    object.classId=c.native_class==1 ? 6 : c.native_class==2 ? 2 : 0;
    object.detectionConfidence=c.score;
    object.left=x1;object.top=y1;object.width=x2-x1;object.height=y2-y1;
    objects.push_back(object);
  }
  return true;
}
CHECK_CUSTOM_PARSE_FUNC_PROTOTYPE(NvDsInferParseCityTrafficCamNet);
