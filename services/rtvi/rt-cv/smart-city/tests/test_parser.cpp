// SPDX-License-Identifier: Apache-2.0
// Exercise the real exported parser using CPU tensors. No engine/GPU is loaded.
#include "../src/rfdetr_parser.cpp"
#include <cassert>

int main() {
  float boxes[]={.5f,.5f,.2f,.4f,.5f,.5f,.2f,.4f};
  std::vector<float> logits(2*91,-100.f);
  logits[6]=std::log(.354880095f/(1-.354880095f));
  logits[8]=std::log(.660172343f/(1-.660172343f));
  NvDsInferLayerInfo box{},labels{};
  box.layerName="dets";box.dataType=FLOAT;box.buffer=boxes;box.inferDims.numElements=8;
  labels.layerName="labels";labels.dataType=FLOAT;labels.buffer=logits.data();labels.inferDims.numElements=182;
  NvDsInferNetworkInfo network{};network.width=1000;network.height=500;network.channels=3;
  NvDsInferParseDetectionParams params{};params.numClassesConfigured=6;params.perClassPreclusterThreshold.assign(6,.35f);
  std::vector<NvDsInferObjectDetectionInfo> objects;
  assert(NvDsInferParseCityRFDETR({box,labels},network,params,objects));
  assert(objects.size()==1 && objects[0].classId==5);
  assert(std::abs(objects[0].detectionConfidence-.660172343f)<1e-6);
  logits[91+6]=2;objects.clear();
  assert(NvDsInferParseCityRFDETR({box,labels},network,params,objects));
  assert(objects.size()==2 && objects[0].classId==4 && objects[1].classId==5);
  assert(objects[0].left==objects[1].left && objects[0].width==objects[1].width);
  // Per-class gating still applies to the winning label, without substituting
  // another label just because that class has a lower configured threshold.
  params.perClassPreclusterThreshold[5]=.7f;objects.clear();
  assert(NvDsInferParseCityRFDETR({box,labels},network,params,objects));
  assert(objects.size()==1 && objects[0].classId==4);
  labels.dataType=HALF;objects.clear();
  assert(!NvDsInferParseCityRFDETR({box,labels},network,params,objects));
  assert(objects.empty());
  std::cout<<"Production RF-DETR parser: one city label per query, distinct overlapping queries, class thresholds and FP32 contract passed\n";
}
