// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <optional>
#include <stdexcept>
#include <string>
#include <unordered_map>
namespace city {
inline std::string tracker_mode(const std::string& mode) {
  // Configuration/metadata presence is not qualification. There is no trusted
  // clock, association, ID-correction or member-epoch contract in this worker.
  if(mode=="mv3dt")
    throw std::runtime_error("--tracker-mode mv3dt is disabled: global identity output is unqualified; use mv3dt-diagnostic");
  if(mode!="camera-local"&&mode!="mv3dt-diagnostic"&&mode!="mv3dt-demo")
    throw std::runtime_error("--tracker-mode must be camera-local, mv3dt-diagnostic or mv3dt-demo");
  return mode;
}
inline void retire_diagnostic_fusion_epoch(std::string& epoch,const std::string& replacement) {
  if(replacement.empty()||replacement==epoch)
    throw std::runtime_error("A source reset requires a new diagnostic fusion epoch");
  epoch=replacement;
}
inline bool valid_world_foot(double x,double y) {
  return std::isfinite(x)&&std::isfinite(y)&&std::abs(x)<=100000&&std::abs(y)<=100000;
}
inline bool valid_visibility(double value) {
  return std::isfinite(value)&&value>=0&&value<=1;
}
// Per-frame only. IDs corrected by the SDK can temporarily occur on multiple
// objects, including different classes. Omit every occurrence; never pick a
// winner, merge boxes or fabricate an identity. Bound storage independently of
// native metadata size and fail closed if that bound is exceeded.
struct DemoTrackIdCounts {
  static constexpr size_t maximum_distinct_ids=4096;
  std::unordered_map<uint64_t,uint64_t> counts;
  uint64_t duplicate_ids=0,duplicate_objects=0,total_objects=0;
  bool capacity_exceeded=false;
  void observe(uint64_t id) {
    if(id==std::numeric_limits<uint64_t>::max())return;
    ++total_objects;
    auto found=counts.find(id);
    if(found==counts.end()) {
      if(counts.size()==maximum_distinct_ids){capacity_exceeded=true;return;}
      counts.emplace(id,1);return;
    }
    if(found->second++==1){++duplicate_ids;duplicate_objects+=2;}
    else ++duplicate_objects;
  }
  bool reject(uint64_t id) const {
    if(capacity_exceeded)return true;
    const auto found=counts.find(id);
    return found!=counts.end()&&found->second>1;
  }
  uint64_t omitted_objects() const {return capacity_exceeded?total_objects:duplicate_objects;}
};
// Explicit experimental map hint, never a production association contract.
// ROI/event/count authority remains camera-local. Reject missing, predicted or
// unsynchronized evidence rather than treating optional metadata as truth.
inline std::optional<std::string> demo_global_identity(
    const std::string& mode,unsigned class_id,bool observed,const std::string& clock_basis,
    const std::optional<std::array<double,2>>& world_foot,
    const std::optional<std::array<double,2>>& image_foot,
    const std::optional<double>& visibility,const std::string& epoch,uint64_t target_id,
    bool native_capture_qualified=false,bool native_multiclass=false) {
  const bool capture_clock=clock_basis=="source-rtcp"||
      (clock_basis=="source-native-sei"&&native_capture_qualified);
  if(mode!="mv3dt-demo"||(native_multiclass?class_id>=7:class_id!=0)||!observed||!capture_clock||epoch.empty()||
     target_id==std::numeric_limits<uint64_t>::max()||!world_foot||!image_foot||!visibility||
     !valid_world_foot((*world_foot)[0],(*world_foot)[1])||
     !std::isfinite((*image_foot)[0])||!std::isfinite((*image_foot)[1])||
     !valid_visibility(*visibility)||*visibility<0.25)return std::nullopt;
  return "mv3dt-demo:"+epoch+":"+std::to_string(target_id);
}
}
