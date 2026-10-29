// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <gst/gst.h>
#include <array>
#include <cstdint>
#include <deque>
#include <optional>
#include <string>
#include <stdexcept>
#include <unordered_map>

namespace city {
constexpr uint64_t kNtpUnixEpochDifferenceNs=2208988800000000000ULL;
constexpr size_t kSourceClockEvidenceLimit=512;
enum class ClockProbeStage:size_t {Depay=0,Parsed=1,Decoded=2,BeforeMux=3};
inline const char* clock_stage_name(ClockProbeStage stage) {
  static const char* names[]{"depay","parsed","decoded","beforeMux"};return names[size_t(stage)];
}
struct ReferenceClockSample {
  uint64_t probe_wall_ns=0;
  unsigned meta_count=0;
  std::optional<uint64_t> timestamp_ns,unix_ns,duration_ns;
  std::string caps,state="missing";
  bool present=false,duplicate_pts=false,discontinuity=false;
};
inline ReferenceClockSample reference_clock_sample(GstBuffer* buffer,uint64_t wall_ns) {
  ReferenceClockSample out;out.present=true;out.probe_wall_ns=wall_ns;
  out.discontinuity=GST_BUFFER_FLAG_IS_SET(buffer,GST_BUFFER_FLAG_DISCONT);
  gpointer iterator=nullptr;
  while(auto* base=gst_buffer_iterate_meta_filtered(buffer,&iterator,GST_REFERENCE_TIMESTAMP_META_API_TYPE)) {
    ++out.meta_count;
    const auto* meta=reinterpret_cast<const GstReferenceTimestampMeta*>(base);
    if(out.meta_count!=1)continue;
    if(meta->reference) {
      auto* text=gst_caps_to_string(meta->reference);out.caps=text?text:"";g_free(text);
      if(out.caps.size()>512)out.caps.resize(512);
    }
    if(GST_CLOCK_TIME_IS_VALID(meta->timestamp))out.timestamp_ns=meta->timestamp;
    if(GST_CLOCK_TIME_IS_VALID(meta->duration))out.duration_ns=meta->duration;
    const auto* structure=meta->reference&&gst_caps_get_size(meta->reference)?gst_caps_get_structure(meta->reference,0):nullptr;
    const char* name=structure?gst_structure_get_name(structure):"";
    if(out.timestamp_ns&&std::string(name)=="timestamp/x-ntp"&&*out.timestamp_ns>=kNtpUnixEpochDifferenceNs)
      out.unix_ns=*out.timestamp_ns-kNtpUnixEpochDifferenceNs;
    else if(out.timestamp_ns&&std::string(name)=="timestamp/x-unix")out.unix_ns=*out.timestamp_ns;
    out.state=out.unix_ns?"reference-present":"unsupported-or-invalid-reference";
  }
  if(out.meta_count>1) {out.unix_ns.reset();out.state="multiple-references";}
  return out;
}
struct SourceClockFrameEvidence {
  uint64_t pts=GST_CLOCK_TIME_NONE;
  uint64_t evidence_epoch=0;
  std::array<ReferenceClockSample,4> stages;
};
struct SourceClockCounters {
  std::array<uint64_t,4> buffers{},with_reference{},missing{},multiple{},unsupported{},duplicate_pts{};
  uint64_t evicted=0,matched_observations=0,unmatched_observations=0,retired_epochs=0;
};
// Caller owns the existing timeline mutex. Exact source+PTS is a bounded
// evidence key, not a clock replacement or a nearest-frame association.
struct SourceClockEvidence {
  std::unordered_map<uint64_t,SourceClockFrameEvidence> frames;
  std::deque<uint64_t> order;
  SourceClockCounters counters;
  std::array<std::optional<uint64_t>,4> last_pts;
  std::optional<uint64_t> last_discontinuity_pts;
  std::optional<uint32_t> last_segment_sequence;
  void retire() {frames.clear();order.clear();last_pts={};++counters.retired_epochs;}
  void segment(uint32_t sequence) {
    if(last_segment_sequence==sequence)return;
    retire();last_segment_sequence=sequence;last_discontinuity_pts.reset();
  }
  void record(uint64_t pts,ClockProbeStage stage,ReferenceClockSample sample) {
    const auto index=size_t(stage);++counters.buffers[index];
    counters.with_reference[index]+=sample.unix_ns.has_value();
    counters.missing[index]+=sample.meta_count==0;counters.multiple[index]+=sample.meta_count>1;
    counters.unsupported[index]+=sample.meta_count==1&&!sample.unix_ns;
    if(!GST_CLOCK_TIME_IS_VALID(pts))return;
    if((sample.discontinuity&&last_discontinuity_pts!=pts)||(last_pts[index]&&pts<*last_pts[index])) {
      retire();if(sample.discontinuity)last_discontinuity_pts=pts;
    }
    const bool repeated_pts=last_pts[index]&&pts==*last_pts[index];
    if(repeated_pts) {
      ++counters.duplicate_pts[index];sample.duplicate_pts=true;
      sample.unix_ns.reset();sample.state="duplicate-source-pts";
    }
    last_pts[index]=pts;
    auto found=frames.find(pts);
    if(found==frames.end()) {
      order.push_back(pts);found=frames.emplace(pts,SourceClockFrameEvidence{}).first;
      found->second.pts=pts;found->second.evidence_epoch=counters.retired_epochs;
    }
    auto& saved=found->second.stages[index];
    if(saved.present) {
      if(!repeated_pts)++counters.duplicate_pts[index];
      saved.duplicate_pts=true;saved.unix_ns.reset();saved.state="duplicate-source-pts";
    } else saved=std::move(sample);
    while(order.size()>kSourceClockEvidenceLimit) {
      counters.evicted+=frames.erase(order.front());order.pop_front();
    }
  }
  std::optional<SourceClockFrameEvidence> take(uint64_t pts) {
    const auto found=frames.find(pts);
    if(found==frames.end()){++counters.unmatched_observations;return std::nullopt;}
    auto value=std::move(found->second);frames.erase(found);++counters.matched_observations;return value;
  }
};
struct MuxClockSettings {
  bool sync_inputs=false;
  unsigned max_latency_ns=0;
  int sync_inputs_ntp_ns=0;
};
inline MuxClockSettings configure_mux_clock_settings(GstElement* mux,bool sync_inputs,
    std::optional<unsigned> max_latency_ns,std::optional<unsigned> sync_inputs_ntp_ns) {
  auto* klass=G_OBJECT_GET_CLASS(mux);
  auto require=[&](const char* name,GType type) {
    const auto* property=g_object_class_find_property(klass,name);
    if(!property||G_PARAM_SPEC_VALUE_TYPE(property)!=type)
      throw std::runtime_error(std::string("Unsupported actual mux clock property/type: ")+name);
  };
  require("sync-inputs",G_TYPE_BOOLEAN);require("max-latency",G_TYPE_UINT);require("sync-inputs-ntp",G_TYPE_INT);
  if(sync_inputs)g_object_set(mux,"sync-inputs",TRUE,nullptr);
  if(max_latency_ns)g_object_set(mux,"max-latency",guint(*max_latency_ns),nullptr);
  if(sync_inputs_ntp_ns)g_object_set(mux,"sync-inputs-ntp",gint(*sync_inputs_ntp_ns),nullptr);
  gboolean actual_sync=FALSE;guint actual_latency=0;gint actual_ntp=0;
  g_object_get(mux,"sync-inputs",&actual_sync,"max-latency",&actual_latency,"sync-inputs-ntp",&actual_ntp,nullptr);
  return {bool(actual_sync),actual_latency,actual_ntp};
}
}
