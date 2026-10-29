// SPDX-License-Identifier: Apache-2.0
#pragma once
#include "gstnvdsmeta.h"
#include <array>
#include <chrono>
#include <cstdint>
#include <optional>

namespace city {
// Admission is counted per source, independently of partial mux batches and SDK
// frame-number replacement. This metadata belongs to the exact video frame.
struct DetectorSchedule {
  bool selected=true;
  unsigned cadence=1,batch_size=0;
  uint64_t entered_ns=0,detector_done_ns=0,tracker_entered_ns=0;
};
inline uint64_t pipeline_steady_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
inline NvDsMetaType detector_schedule_type() {
  static const auto type=nvds_get_user_meta_type(const_cast<gchar*>("VSS.CITY.DETECTOR_SCHEDULE.V1"));return type;
}
inline DetectorSchedule* detector_schedule(NvDsFrameMeta* frame) {
  DetectorSchedule* found=nullptr;
  for(auto* item=frame->frame_user_meta_list;item;item=item->next) {
    auto* meta=static_cast<NvDsUserMeta*>(item->data);
    if(meta->base_meta.meta_type==detector_schedule_type()) {
      if(found||!meta->user_meta_data)return nullptr;
      found=static_cast<DetectorSchedule*>(meta->user_meta_data);
    }
  }
  return found;
}
inline gpointer copy_detector_schedule(gpointer data,gpointer) {
  return new DetectorSchedule(*static_cast<DetectorSchedule*>(static_cast<NvDsUserMeta*>(data)->user_meta_data));
}
inline void release_detector_schedule(gpointer data,gpointer) {
  auto* meta=static_cast<NvDsUserMeta*>(data);
  delete static_cast<DetectorSchedule*>(meta->user_meta_data);meta->user_meta_data=nullptr;
}
struct DetectorCadence {
  std::array<uint64_t,2> admitted{};
  std::array<std::optional<uint64_t>,2> previous_pts{};
  bool select(unsigned source,uint64_t pts,unsigned cadence) {
    if(source>=admitted.size()||cadence<1||cadence>3)return false;
    // A rewind/discontinuity must start with a detector measurement.
    if(previous_pts[source]&&pts<=*previous_pts[source])admitted[source]=0;
    previous_pts[source]=pts;
    return admitted[source]++%cadence==0;
  }
};
inline bool stamp_detector_schedule(NvDsBatchMeta* batch,NvDsFrameMeta* frame,DetectorSchedule value) {
  if(detector_schedule(frame))return false;
  auto* meta=nvds_acquire_user_meta_from_pool(batch);if(!meta)return false;
  meta->base_meta.meta_type=detector_schedule_type();meta->user_meta_data=new DetectorSchedule(value);
  meta->base_meta.copy_func=copy_detector_schedule;meta->base_meta.release_func=release_detector_schedule;
  nvds_add_user_meta_to_frame(frame,meta);return true;
}
}
