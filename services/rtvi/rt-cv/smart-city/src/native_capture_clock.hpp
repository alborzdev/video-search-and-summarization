// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <gst/gst.h>
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <cstdint>
#include <deque>
#include <limits>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>

namespace city {
// This is the explicit UUID + five-field publisher format, not an invented
// version field in the current Isaac producer. Capture is encoded-frame
// handoff wall time; it does not claim physical exposure synchronization.
constexpr const char* kNativeCaptureFormat="isaacsim-native-wall-capture-v1";
constexpr std::array<uint8_t,16> kNativeCaptureUuid{
  0xaa,0x71,0xe4,0x8f,0x07,0x11,0x5d,0x80,0xa2,0x47,0xcd,0x31,0xca,0x6f,0xa4,0x9c};
constexpr size_t kNativeAuBytes=16*1024*1024,kNativeJsonBytes=4096,kNativeClockFrames=512;
constexpr uint64_t kNativeCaptureMaxAgeNs=2000000000ULL,kNativeCaptureFutureNs=50000000ULL;
struct NativeCaptureSample {
  uint64_t capture_ns=0,frame_counter=0,diagnostic_sim_ns=0;
};
struct NativeCaptureMissingMetadata : std::runtime_error {
  NativeCaptureMissingMetadata():std::runtime_error("Picture AU lacks native capture metadata"){}
};
inline bool native_capture_fresh(uint64_t capture,uint64_t now) {
  return capture&&((capture<=now&&now-capture<=kNativeCaptureMaxAgeNs)||
                   (capture>now&&capture-now<=kNativeCaptureFutureNs));
}
inline NativeCaptureSample native_capture_json(const uint8_t* data,size_t size) {
  if(!size||size>kNativeJsonBytes)throw std::runtime_error("Native capture JSON byte bound");
  std::set<std::string> keys;
  auto callback=[&](int depth,nlohmann::json::parse_event_t event,nlohmann::json& parsed) {
    if((event==nlohmann::json::parse_event_t::object_start&&depth!=0)||event==nlohmann::json::parse_event_t::array_start)
      throw std::runtime_error("Flat native capture object required");
    if(event==nlohmann::json::parse_event_t::key&&!keys.insert(parsed.get<std::string>()).second)
      throw std::runtime_error("Duplicate native capture JSON key");
    return true;
  };
  const auto value=nlohmann::json::parse(data,data+size,callback);
  static const std::set<std::string> expected{"timestamp","timestamp_iso8601","frame_num","publish_sim_time_ns","timestamp_basis"};
  if(!value.is_object()||keys!=expected||value.size()!=expected.size()||
     !value["timestamp_basis"].is_string()||value["timestamp_basis"]!="wall-capture"||
     !value["timestamp_iso8601"].is_string())throw std::runtime_error("Unsupported native capture format/basis");
  for(const auto* key:{"timestamp","frame_num","publish_sim_time_ns"})
    if(!value[key].is_number_unsigned())throw std::runtime_error("Native capture integer required");
  const auto iso=value["timestamp_iso8601"].get<std::string>();
  if(iso.size()<20||iso.size()>40||iso[4]!='-'||iso[7]!='-'||iso[10]!='T'||iso[13]!=':'||iso[16]!=':'||
     (iso.back()!='Z'&&(iso.size()<6||iso.substr(iso.size()-6)!="+00:00")))
    throw std::runtime_error("Native capture UTC label required");
  for(unsigned char c:iso)if(c<32||c>126)throw std::runtime_error("Invalid native capture UTC label");
  NativeCaptureSample sample{value["timestamp"].get<uint64_t>(),value["frame_num"].get<uint64_t>(),value["publish_sim_time_ns"].get<uint64_t>()};
  if(!sample.capture_ns)throw std::runtime_error("Zero native capture wall clock");
  auto* date=g_date_time_new_from_iso8601(iso.c_str(),nullptr);
  if(!date)throw std::runtime_error("Invalid native capture UTC label");
  const auto seconds=g_date_time_to_unix(date);
  const auto micros=g_date_time_get_microsecond(date);
  g_date_time_unref(date);
  if(seconds<0||uint64_t(seconds)>std::numeric_limits<uint64_t>::max()/1000000000ULL)
    throw std::runtime_error("Native capture UTC range");
  const auto iso_ns=uint64_t(seconds)*1000000000ULL+uint64_t(micros)*1000ULL;
  if((iso_ns>sample.capture_ns?iso_ns-sample.capture_ns:sample.capture_ns-iso_ns)>2000)
    throw std::runtime_error("Native capture UTC label/time mismatch");
  return sample;
}
struct NativeAuSample {bool has_picture=false;std::optional<NativeCaptureSample> capture;unsigned discarded_prefix_units=0;};
inline void native_capture_nal(const uint8_t* data,size_t size,NativeAuSample& out) {
  if(!size||(data[0]&0x80))throw std::runtime_error("Empty/forbidden H264 NAL");
  const auto kind=data[0]&31;
  if(kind>=1&&kind<=5)out.has_picture=true;
  if(kind!=6)return;
  std::vector<uint8_t> rbsp;rbsp.reserve(size);
  unsigned zeros=0;
  for(size_t i=1;i<size;++i) {
    const auto byte=data[i];
    if(zeros>=2&&byte==3) {
      if(i+1>=size||data[i+1]>3)throw std::runtime_error("Invalid H264 emulation prevention");
      zeros=0;continue;
    }
    rbsp.push_back(byte);zeros=byte==0?zeros+1:0;
  }
  size_t cursor=0,payloads=0;bool trailing=false,native_in_nal=false;
  while(cursor<rbsp.size()) {
    if(rbsp[cursor]==0x80&&std::all_of(rbsp.begin()+cursor+1,rbsp.end(),[](uint8_t v){return v==0;})) {
      trailing=true;break;
    }
    if(++payloads>64)throw std::runtime_error("SEI payload count bound");
    auto field=[&]() {
      size_t result=0;
      while(cursor<rbsp.size()&&rbsp[cursor]==255){result+=255;++cursor;}
      if(cursor>=rbsp.size())throw std::runtime_error("Truncated SEI field");
      return result+rbsp[cursor++];
    };
    const auto type=field(),bytes=field();
    if(bytes>rbsp.size()-cursor)throw std::runtime_error("Truncated SEI payload");
    if(type==5&&bytes>=16&&std::equal(kNativeCaptureUuid.begin(),kNativeCaptureUuid.end(),rbsp.data()+cursor)) {
      // A duplicate is always ambiguous and remains a hard failure. Parse the
      // second bounded record for useful diagnostics: this distinguishes an
      // exact repeat from two publisher frames grouped into the same AU,
      // without choosing either clock or forwarding the affected picture.
      const auto sample=native_capture_json(rbsp.data()+cursor+16,bytes-16);
      if(out.capture) {
        const auto& first=*out.capture;
        const bool identical=first.capture_ns==sample.capture_ns&&
            first.frame_counter==sample.frame_counter&&first.diagnostic_sim_ns==sample.diagnostic_sim_ns;
        throw std::runtime_error(std::string("Duplicate native capture UUID metadata; same-fields=")+
            (identical?"true":"false")+" same-nal="+(native_in_nal?"true":"false")+
            " first-frame="+std::to_string(first.frame_counter)+" second-frame="+std::to_string(sample.frame_counter)+
            " first-capture-ns="+std::to_string(first.capture_ns)+" second-capture-ns="+std::to_string(sample.capture_ns));
      }
      native_in_nal=true;
      out.capture=sample;
    }
    cursor+=bytes;
  }
  // VIOS adds a separate NVDS_CUSTOMMETA UUID payload without RBSP trailing
  // bits. It is not our clock authority. Enforce complete payload bounds for
  // every SEI and require proper trailing bits for the native UUID NAL itself.
  if(!trailing&&native_in_nal)throw std::runtime_error("Missing native H264 SEI RBSP trailing bits");
}
inline NativeAuSample native_capture_au(const uint8_t* data,size_t size,bool annex_b,unsigned length_size=4) {
  if(!size||size>kNativeAuBytes)throw std::runtime_error("H264 AU byte bound");
  NativeAuSample out;size_t count=0;bool seen_aud=false,capture_before_aud=false;
  auto nal=[&](size_t start,size_t end) {
    if(++count>256)throw std::runtime_error("H264 NAL count bound");
    NativeAuSample item;native_capture_nal(data+start,end-start,item);
    const auto kind=data[start]&31;
    if(item.capture&&out.capture) {
      // The native producer prefixes its clock immediately before the AUD.
      // h264parse can retain pictureless prefix units while waiting for an
      // IDR, then attach them to that picture's buffer. Explicit AUDs prove
      // those older records have NO picture. Never borrow their time, merge
      // two pictured units, or accept two clocks inside one delimited unit.
      if(out.has_picture||!seen_aud||!capture_before_aud)
        native_capture_nal(data+start,end-start,out); // retain strict duplicate diagnostic
      const auto& before=*out.capture;const auto& after=*item.capture;
      if(after.frame_counter<=before.frame_counter||after.capture_ns<=before.capture_ns||
         after.diagnostic_sim_ns<before.diagnostic_sim_ns)
        throw std::runtime_error("Nonprogressing pictureless native capture prefix");
      if(++out.discarded_prefix_units>8)throw std::runtime_error("Pictureless native prefix bound");
      out.capture.reset();seen_aud=false;capture_before_aud=false;
    }
    if(kind==9) {
      if(end-start!=2||(data[start+1]&31)!=0x10||seen_aud||out.has_picture)
        throw std::runtime_error("Invalid/multiple native access unit delimiters");
      seen_aud=true;
    }
    if(item.capture){out.capture=item.capture;capture_before_aud=!seen_aud;}
    if(item.has_picture) {
      if(out.discarded_prefix_units&&(!seen_aud||!capture_before_aud))
        throw std::runtime_error("Pictureless prefix lacks final native delimiter");
      out.has_picture=true;
    }
  };
  if(!annex_b) {
    if(length_size!=1&&length_size!=2&&length_size!=4)throw std::runtime_error("Unsupported AVC NAL length size");
    size_t cursor=0;
    while(cursor<size) {
      if(size-cursor<length_size)throw std::runtime_error("Truncated AVC length field");
      size_t bytes=0;for(unsigned i=0;i<length_size;++i)bytes=(bytes<<8)|data[cursor++];
      if(!bytes||bytes>size-cursor)throw std::runtime_error("Truncated AVC NAL");
      nal(cursor,cursor+bytes);cursor+=bytes;
    }
  } else {
    auto code=[&](size_t i)->size_t {
      if(i+3<=size&&data[i]==0&&data[i+1]==0&&data[i+2]==1)return 3;
      if(i+4<=size&&data[i]==0&&data[i+1]==0&&data[i+2]==0&&data[i+3]==1)return 4;
      return 0;
    };
    size_t cursor=0;
    while(cursor<size&&!code(cursor)){if(data[cursor++])throw std::runtime_error("Invalid Annex B prefix");}
    if(cursor==size)throw std::runtime_error("Missing Annex B start code");
    while(cursor<size) {
      const auto prefix=code(cursor);if(!prefix)throw std::runtime_error("Invalid Annex B start code");
      const auto start=cursor+prefix;cursor=start;
      while(cursor<size&&!code(cursor))++cursor;
      size_t end=cursor;while(end>start&&data[end-1]==0)--end;
      nal(start,end);
    }
  }
  if(out.has_picture&&!out.capture)throw NativeCaptureMissingMetadata();
  if(!out.has_picture&&out.capture)throw std::runtime_error("Native capture metadata has no picture AU");
  return out;
}
inline NativeAuSample native_capture_buffer(GstBuffer* buffer,GstCaps* caps) {
  if(!caps||gst_caps_get_size(caps)!=1)throw std::runtime_error("One encoded AU caps required");
  const auto* structure=gst_caps_get_structure(caps,0);
  if(std::string(gst_structure_get_name(structure))!="video/x-h264")throw std::runtime_error("H264 AU caps required");
  const auto* format=gst_structure_get_string(structure,"stream-format");
  const auto* alignment=gst_structure_get_string(structure,"alignment");
  if(!format||!alignment||std::string(alignment)!="au")throw std::runtime_error("Aligned H264 AU required");
  const bool annex=std::string(format)=="byte-stream";
  if(!annex&&std::string(format)!="avc"&&std::string(format)!="avc3")throw std::runtime_error("Unsupported H264 stream format");
  unsigned length_size=4;
  if(!annex) {
    const auto* value=gst_structure_get_value(structure,"codec_data");
    auto* codec=value&&GST_VALUE_HOLDS_BUFFER(value)?gst_value_get_buffer(value):nullptr;
    GstMapInfo map{};
    if(!codec||!gst_buffer_map(codec,&map,GST_MAP_READ))throw std::runtime_error("AVC codec_data required");
    if(map.size<5||map.data[0]!=1){gst_buffer_unmap(codec,&map);throw std::runtime_error("Unsupported AVC codec_data");}
    length_size=(map.data[4]&3)+1;gst_buffer_unmap(codec,&map);
  }
  GstMapInfo map{};
  if(!gst_buffer_map(buffer,&map,GST_MAP_READ))throw std::runtime_error("Cannot read encoded AU");
  try {auto result=native_capture_au(map.data,map.size,annex,length_size);gst_buffer_unmap(buffer,&map);return result;}
  catch(...){gst_buffer_unmap(buffer,&map);throw;}
}
struct NativeCaptureFrame {
  NativeCaptureSample sample;uint64_t pts=0,epoch=0,sdk_ntp_ns=0;
  bool decoded=false,before_mux=false,applied=false;
};
// The caller owns timeline_mutex. A clock discontinuity fails this worker
// closed; a fresh managed process supplies a new source/fusion epoch. We never
// reuse old PTS keys across an in-process reconnect or silently fall back.
struct NativeCaptureClock {
  std::unordered_map<uint64_t,NativeCaptureFrame> frames;
  std::deque<uint64_t> order;
  std::optional<uint64_t> last_pts,last_capture,last_counter,last_sim;
  std::optional<uint32_t> segment_sequence;
  uint64_t epoch=0,parsed=0,applied=0,evicted=0;
  uint64_t unproven_startup_aus=0;
  std::optional<uint64_t> unproven_startup_begin;
  // Set only by the explicit all-file, no-network-output replay option. Format,
  // monotonicity, exact AU/PTS identity and single-use checks still apply.
  bool failed=false,recorded_replay=false;
  bool discard_unproven_startup(uint64_t monotonic_now) {
    // A live RTSP join can begin after the first picture's SEI NAL. Discard
    // that incomplete join; never decode it or invent a capture timestamp.
    // Missing metadata after the first proof, or in recordings, stays fatal.
    if(failed||recorded_replay||parsed)return false;
    if(!unproven_startup_begin)unproven_startup_begin=monotonic_now;
    if(monotonic_now<*unproven_startup_begin||monotonic_now-*unproven_startup_begin>2000000000ULL||unproven_startup_aus>=8)return false;
    ++unproven_startup_aus;return true;
  }
  [[noreturn]] void reject(const std::string& reason) {failed=true;frames.clear();order.clear();++epoch;throw std::runtime_error(reason);}
  void segment(uint32_t sequence) {
    if(failed)reject("Native capture clock already rejected");
    if(segment_sequence&&*segment_sequence!=sequence&&last_pts)reject("Native capture segment changed; new worker epoch required");
    segment_sequence=sequence;
  }
  void record(uint64_t pts,const NativeCaptureSample& sample,uint64_t now,bool discontinuity) {
    if(failed)reject("Native capture clock already rejected");
    if(!GST_CLOCK_TIME_IS_VALID(pts)||!sample.capture_ns||
       (!recorded_replay&&!native_capture_fresh(sample.capture_ns,now)))reject("Invalid/stale/future native capture clock");
    if(last_pts&&(discontinuity||pts<=*last_pts||sample.capture_ns<=*last_capture||
        sample.frame_counter<=*last_counter||sample.diagnostic_sim_ns<*last_sim))reject("Native capture source clock/frame epoch changed");
    last_pts=pts;last_capture=sample.capture_ns;last_counter=sample.frame_counter;last_sim=sample.diagnostic_sim_ns;
    frames.emplace(pts,NativeCaptureFrame{sample,pts,epoch,0,false,false,false});order.push_back(pts);++parsed;
    while(order.size()>kNativeClockFrames){evicted+=frames.erase(order.front());order.pop_front();}
  }
  NativeCaptureFrame& exact(uint64_t pts) {
    const auto found=frames.find(pts);
    if(failed||found==frames.end()||found->second.epoch!=epoch)reject("Missing exact native AU PTS evidence");
    return found->second;
  }
  void decoded(uint64_t pts) {auto& frame=exact(pts);if(frame.decoded)reject("Duplicate decoded native AU PTS");frame.decoded=true;}
  void before_mux(uint64_t pts) {auto& frame=exact(pts);if(!frame.decoded||frame.before_mux)reject("Missing/duplicate decoded native AU PTS");frame.before_mux=true;}
  NativeCaptureFrame& qualified(uint64_t pts,bool prepared,uint64_t current_ntp=0) {
    auto& frame=exact(pts);
    const auto detail=" pts="+std::to_string(pts)+" frameCounter="+std::to_string(frame.sample.frame_counter);
    if(!frame.decoded)reject("Native capture evidence not decoded"+detail);
    if(!frame.before_mux)reject("Native capture evidence did not reach mux"+detail);
    if(frame.applied!=prepared)reject("Native capture evidence prepared state mismatch"+detail);
    if(prepared&&frame.sample.capture_ns!=current_ntp)reject("Native capture authority changed after tracking"+detail);
    return frame;
  }
  bool fresh(uint64_t pts,uint64_t now,bool allow_stale_drop=false) {
    const auto& frame=exact(pts);const auto capture=frame.sample.capture_ns;
    if((recorded_replay&&capture)||native_capture_fresh(capture,now))return true;
    // Only previously verified evidence delayed in our pipeline may be
    // discarded during an explicit, bounded reset drain. Future evidence,
    // missing records and all qualification failures still reject the clock.
    if(allow_stale_drop&&capture&&capture<now)return false;
    reject(std::string(capture<now?"Stale":"Future/zero")+" native capture before tracking pts="+
        std::to_string(pts)+" captureNs="+std::to_string(capture)+" nowNs="+std::to_string(now)+
        " frameCounter="+std::to_string(frame.sample.frame_counter));
  }
  void discard_unprepared(uint64_t pts) {qualified(pts,false);frames.erase(pts);}
  NativeCaptureFrame prepare(uint64_t pts,uint64_t sdk_ntp,uint64_t now) {
    auto& frame=qualified(pts,false);fresh(pts,now);
    frame.applied=true;frame.sdk_ntp_ns=sdk_ntp;++applied;return frame;
  }
  NativeCaptureFrame take(uint64_t pts,uint64_t current_ntp) {
    auto value=qualified(pts,true,current_ntp);
    frames.erase(pts);return value;
  }
};
}
