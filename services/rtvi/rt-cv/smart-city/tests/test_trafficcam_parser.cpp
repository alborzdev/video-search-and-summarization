// SPDX-License-Identifier: Apache-2.0
#include "../src/rfdetr_parser.cpp"
#include <cassert>
#include <iostream>
int main() {
  float boxes[]={.5f,.5f,.2f,.4f, .2f,.2f,.1f,.1f, .8f,.8f,.1f,.1f, .5f,.5f,.1f,.1f};
  float logits[]={-10,3,-10,-10,-10, -10,-10,4,-10,-10, -10,-10,-10,5,-10, 6,-10,-10,-10,-10};
  NvDsInferLayerInfo box{},classes{};box.layerName="pred_boxes";box.dataType=FLOAT;box.buffer=boxes;box.inferDims.numElements=16;
  classes.layerName="pred_logits";classes.dataType=FLOAT;classes.buffer=logits;classes.inferDims.numElements=20;
  NvDsInferNetworkInfo network{};network.width=960;network.height=544;
  NvDsInferParseDetectionParams params{};params.numClassesConfigured=7;params.perClassPreclusterThreshold.assign(7,.35f);
  std::vector<NvDsInferObjectDetectionInfo> objects;
  assert(NvDsInferParseCityTrafficCamNet({box,classes},network,params,objects));
  assert(objects.size()==3 && objects[0].classId==0 && objects[1].classId==2 && objects[2].classId==6);
  assert(std::abs(objects[2].left-384)<1e-4 && std::abs(objects[2].top-163.2)<1e-3);
  params.perClassPreclusterThreshold[6]=.99;objects.clear();
  assert(NvDsInferParseCityTrafficCamNet({box,classes},network,params,objects));
  assert(objects.size()==2);
  classes.inferDims.numElements=19;objects.clear();
  assert(!NvDsInferParseCityTrafficCamNet({box,classes},network,params,objects));
  assert(city::tracking_model_revision("trafficcamnet-test").find("nvidia-tao-top200-city-traffic-v1")!=std::string::npos);
  assert(std::string(city::class_name(6))=="two-wheeler");
  std::cout<<"TrafficCamNet native output contract, coarse taxonomy and revision passed\n";
}
