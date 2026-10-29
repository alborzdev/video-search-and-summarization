// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <optional>
#include <ostream>
#include <vector>

namespace city {
// Diagnostic evidence only. These records never supply production boxes,
// map anchors, identities, rule inputs or association thresholds.
constexpr size_t kTrackerDiagnosticObjectLimit=256;
template<size_t N> inline bool diagnostic_finite(const std::array<double,N>& value) {
  for(const auto v:value)if(!std::isfinite(v))return false;
  return true;
}
inline std::optional<std::array<double,4>> diagnostic_box(
    double left,double top,double width,double height,double sx,double sy) {
  const std::array<double,4> value{left*sx,top*sy,width*sx,height*sy};
  if(!diagnostic_finite(value)||value[2]<=0||value[3]<=0)return std::nullopt;
  // Deliberately retain unclipped SDK coordinates, including negative edges.
  return value;
}
struct TrackerObjectDiagnostic {
  uint64_t sdk_target_id=0;
  int sdk_class_id=-1;
  bool detector_observed=false,id_rejected_as_ambiguous=false;
  std::optional<std::array<double,4>> detector_box,tracker_box,rect_box;
  std::optional<std::array<double,2>> world_foot,image_foot;
  std::optional<double> visibility;
  std::vector<std::array<double,2>> projected_hull;
};
template<size_t N> inline void diagnostic_array(
    std::ostream& out,const std::optional<std::array<double,N>>& value) {
  if(!value||!diagnostic_finite(*value)){out<<"null";return;}
  out<<'[';for(size_t i=0;i<N;++i){if(i)out<<',';out<<(*value)[i];}out<<']';
}
inline void write_tracker_object_diagnostic(std::ostream& out,const TrackerObjectDiagnostic& value) {
  out<<"{\"sdkTargetId\":\""<<value.sdk_target_id<<"\",\"sdkClassId\":"<<value.sdk_class_id
     <<",\"detectorObservedThisFrame\":"<<(value.detector_observed?"true":"false")
     <<",\"idRejectedAsAmbiguous\":"<<(value.id_rejected_as_ambiguous?"true":"false")
     <<",\"detectorBboxPx\":";
  // Retained detector boxes on skipped inference frames are not observations.
  diagnostic_array(out,value.detector_observed?value.detector_box:std::nullopt);
  out<<",\"trackerBboxPx\":";diagnostic_array(out,value.tracker_box);
  out<<",\"rectBboxPx\":";diagnostic_array(out,value.rect_box);
  out<<",\"nativeWorldFootM\":";diagnostic_array(out,value.world_foot);
  out<<",\"nativeImageFootPx\":";diagnostic_array(out,value.image_foot);
  out<<",\"nativeVisibility\":";
  if(value.visibility&&std::isfinite(*value.visibility)&&*value.visibility>=0&&*value.visibility<=1)out<<*value.visibility;
  else out<<"null";
  out<<",\"nativeProjectedHullPx\":[";
  for(size_t i=0;i<value.projected_hull.size()&&i<64;++i) {
    if(i)out<<',';
    diagnostic_array(out,std::optional<std::array<double,2>>(value.projected_hull[i]));
  }
  out<<']';
  out<<'}';
}
inline void write_tracker_frame_diagnostics(std::ostream& out,uint64_t frame_number,uint64_t ntp_ns,
    uint64_t pts_ns,unsigned source_width,unsigned source_height,unsigned processing_width,
    unsigned processing_height,size_t raw_object_count,const std::vector<TrackerObjectDiagnostic>& objects) {
  const auto exported=std::min(objects.size(),kTrackerDiagnosticObjectLimit);
  out<<"{\"schemaVersion\":\"city.tracker-diagnostics.v1\",\"sdkFrameNumber\":\""<<frame_number
     <<"\",\"sdkNtpTimestampNs\":";
  if(ntp_ns)out<<'\"'<<ntp_ns<<'\"';else out<<"null";
  out<<",\"sdkBufPtsNs\":\""<<pts_ns<<"\",\"sourceImageSize\":["<<source_width<<','<<source_height
     <<"],\"processingImageSize\":["<<processing_width<<','<<processing_height
     <<"],\"trackerImageSize\":[640,384],\"bboxSpace\":\"source-image-pixels-unclipped\""
     <<",\"rawObjectCount\":"<<raw_object_count<<",\"exportedObjectCount\":"<<exported
     <<",\"truncated\":"<<(raw_object_count>exported?"true":"false")<<",\"objects\":[";
  for(size_t i=0;i<exported;++i){if(i)out<<',';write_tracker_object_diagnostic(out,objects[i]);}
  out<<"]}";
}
}
