// SPDX-License-Identifier: Apache-2.0
#include "rfdetr_core.hpp"
#include <cassert>
#include <iostream>
int main() {
  float boxes[] = {.5f,.5f,.2f,.4f,.95f,.05f,.2f,.2f};
  std::vector<float> logits(2*91,-100.f);
  logits[1]=4; logits[6]=3; logits[91+8]=5; logits[91+90]=6;
  auto ds=city::decode(boxes,logits.data(),2,91,1000,500,.5f,4);
  assert(ds.size()==3); // Sparse COCO90 isn't dropped as a made-up background: filtered by capability.
  assert(ds[0].class_id==5 && ds[1].class_id==0 && ds[2].class_id==4);
  assert(std::abs(ds[1].x-400)<.01 && std::abs(ds[1].height-200)<.01);
  assert(ds[0].x+ds[0].width <= 1000 && ds[0].y >= 0);
  assert(std::abs(city::sigmoid(1000)-1)<1e-5 && city::sigmoid(-1000)==0);
  assert(std::abs(city::normalize_rgb(255,0)-2.2489083)<1e-5);
  assert(city::city_class(5)==-1 && city::city_class(6)==4);
  const auto identity=city::tracking_model_revision("rfdetr-medium-fp16@sha256:example");
  assert(identity=="rfdetr-medium-fp16@sha256:example;postprocess=one-city-class-per-query-v1");
  assert(city::tracking_model_revision(identity)==identity);
  // Global top-k must be applied before dropping unsupported classes.
  assert(city::decode(boxes,logits.data(),2,91,1000,500,.5f,1).empty());
  auto tracks=city::decode_for_tracking(boxes,logits.data(),2,91,1000,500,.5f,4);
  assert(tracks.size()==2 && tracks[0].class_id==5 && tracks[1].class_id==0);
  assert(tracks[0].query_index==1 && tracks[1].query_index==0);
  // A bus/truck ambiguity from one query must not become two object tracks.
  std::vector<float> ambiguous(2*91,-100.f);
  ambiguous[6]=std::log(.354880095f/(1-.354880095f));
  ambiguous[8]=std::log(.660172343f/(1-.660172343f));
  auto reference=city::decode(boxes,ambiguous.data(),2,91,1000,500,.35f);
  auto unique=city::decode_for_tracking(boxes,ambiguous.data(),2,91,1000,500,.35f);
  assert(reference.size()==2 && unique.size()==1 && unique[0].class_id==5);
  // Do not use spatial NMS: a different query with the same box is retained.
  float overlapping[]={.5f,.5f,.2f,.4f,.5f,.5f,.2f,.4f};
  ambiguous[91+6]=2;
  unique=city::decode_for_tracking(overlapping,ambiguous.data(),2,91,1000,500,.35f);
  assert(unique.size()==2 && unique[0].query_index!=unique[1].query_index);
  assert(unique[0].x==unique[1].x && unique[0].width==unique[1].width);
  // Equal competing logits use the deterministic reference category order.
  ambiguous[8]=ambiguous[6]=2;
  unique=city::decode_for_tracking(boxes,ambiguous.data(),2,91,1000,500,.35f);
  assert(unique.size()==2 && unique[0].class_id==4);
  logits[1]=NAN; assert(city::decode(boxes,logits.data(),2,91,1000,500,.5f).size()==2);
  bool threw=false; try {city::decode(boxes,logits.data(),2,80,1000,500,.5f);} catch(...) {threw=true;}
  assert(threw);
  std::cout << "RF-DETR sparse-category/global-top-k/clipping/numerical controls passed\n";
}
