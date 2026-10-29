// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <algorithm>
#include <array>
#include <charconv>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <limits>
#include <map>
#include <memory>
#include <optional>
#include <mutex>
#include <regex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>
namespace city {
constexpr uint32_t kDefaultPreviewFps=15;
constexpr size_t kMaxPreviewBytes=2*1024*1024;
constexpr size_t kPreviewIdentityLimit=32;
// Keep encoder identities far from ordinary file/RTSP running-time PTS. If a
// transform restores camera PTS instead of preserving our token, fail closed.
constexpr uint64_t kPreviewTokenBase=1ULL<<62;
struct PreviewProvenance {
  std::string source,session,model;
  uint64_t sequence=0,source_time_ns=0;
  uint32_t width=0,height=0;
  uint64_t selected_steady_ns=0; // Internal stage timing; never a capture clock.
};

struct PreviewTimingSnapshot {
  uint64_t count=0;
  double mean_ms=0,last_ms=0,max_ms=0,p50_upper_ms=0,p95_upper_ms=0;
};
class PreviewTiming {
  std::mutex mutex_;
  static constexpr std::array<uint64_t,12> bounds_={1000000ULL,2000000ULL,5000000ULL,10000000ULL,
      20000000ULL,50000000ULL,100000000ULL,200000000ULL,500000000ULL,1000000000ULL,5000000000ULL,UINT64_MAX};
  std::array<uint64_t,12> bins_{};
  uint64_t count_=0,last_=0,max_=0;
  long double total_=0;
 public:
  void record(uint64_t ns) {
    std::lock_guard<std::mutex> lock(mutex_);++count_;total_+=ns;last_=ns;max_=std::max(max_,ns);
    for(size_t i=0;i<bounds_.size();++i)if(ns<=bounds_[i]){++bins_[i];break;}
  }
  PreviewTimingSnapshot snapshot() {
    std::lock_guard<std::mutex> lock(mutex_);
    PreviewTimingSnapshot result{count_};if(!count_)return result;
    result.mean_ms=double(total_/count_/1000000);result.last_ms=double(last_)/1000000;result.max_ms=double(max_)/1000000;
    uint64_t cumulative=0;const auto p50=(count_+1)/2,p95=count_-count_/20;
    for(size_t i=0;i<bounds_.size();++i) {
      cumulative+=bins_[i];const double upper=double(std::min(bounds_[i],max_))/1000000;
      if(!result.p50_upper_ms&&cumulative>=p50)result.p50_upper_ms=upper;
      if(cumulative>=p95){result.p95_upper_ms=upper;break;}
    }
    return result;
  }
};
inline uint32_t parse_preview_fps(const std::string& text) {
  uint32_t value=0;auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
  if(parsed.ec!=std::errc()||parsed.ptr!=text.data()+text.size()||value<1||value>30)
    throw std::runtime_error("--preview-fps must be an integer from 1 to 30");
  return value;
}
inline bool preview_url_valid(const std::string& url) {
  return url.size()<=2048&&std::regex_match(url,std::regex(R"(https?://[A-Za-z0-9.\[\]:_-]+/api/v1/city/preview)"));
}
inline bool preview_header_valid(const std::string& text) {
  if(text.empty()||text.size()>512)return false;
  for(unsigned char c:text)if(c<32||c>126)return false;
  return true;
}
class PreviewSampler {
  // Credits use exact integer frame units: 1e9 credits == one frame. A burst
  // can contain two current frames; a pause never builds an unbounded backlog.
  static constexpr uint64_t kFrame=1000000000ULL,kCapacity=2*kFrame;
  std::optional<uint64_t> previous_;
  uint64_t credits_=kCapacity;
 public:
  bool select(uint64_t steady_ns,uint32_t fps) {
    if(!fps)throw std::invalid_argument("preview sampling rate must be positive");
    if(previous_) {
      // A clock rollback cannot mint another burst or repeatedly refill credit.
      if(steady_ns<*previous_)return false;
      const uint64_t elapsed=steady_ns-*previous_;
      if(elapsed>=(kCapacity+fps-1)/fps)credits_=kCapacity;
      else credits_=std::min(kCapacity,credits_+elapsed*fps);
    }
    previous_=steady_ns;
    if(credits_<kFrame)return false;
    credits_-=kFrame;
    return true;
  }
};
// PTS values are opaque encoder identities, not camera or display timestamps.
// Ordered storage also bounds evicted/consumed bookkeeping under endless replay.
class PreviewIdentityMap {
  uint64_t next_=1;
  size_t limit_;
  std::map<uint64_t,PreviewProvenance> values_;
 public:
  uint64_t evicted=0;
  explicit PreviewIdentityMap(size_t limit=kPreviewIdentityLimit):limit_(limit) {
    if(!limit)throw std::invalid_argument("preview identity bound must be positive");
  }
  uint64_t reserve(PreviewProvenance provenance) {
    if(next_>(std::numeric_limits<uint64_t>::max()-kPreviewTokenBase)/1000000ULL)throw std::overflow_error("preview identity exhausted");
    const auto tag=kPreviewTokenBase+next_++*1000000ULL;
    return reserve_at(tag,std::move(provenance));
  }
  // Video needs a real running-time cadence, while preserving exact lookup
  // through conversion/encoding. The encoder must return this very same PTS.
  uint64_t reserve_at(uint64_t tag,PreviewProvenance provenance) {
    if(tag==UINT64_MAX||values_.count(tag))throw std::invalid_argument("duplicate or invalid encoder PTS");
    if(values_.size()>=limit_){values_.erase(values_.begin());++evicted;}
    values_.emplace(tag,std::move(provenance));return tag;
  }
  std::optional<PreviewProvenance> take(uint64_t tag) {
    auto found=values_.find(tag);if(found==values_.end())return std::nullopt;
    auto result=std::move(found->second);values_.erase(found);return result;
  }
  size_t size()const{return values_.size();}
};
// An admission receipt, not a capture clock or browser acknowledgement. Only
// the isolated video publication branch waits; inference never waits on HTTP.
class PreviewMetadataReceipt {
  std::mutex mutex_;
  std::condition_variable changed_;
  bool finished_=false,accepted_=false;
 public:
  void finish(bool accepted) {
    {std::lock_guard<std::mutex> lock(mutex_);if(finished_)return;finished_=true;accepted_=accepted;}
    changed_.notify_all();
  }
  bool wait(std::chrono::milliseconds maximum) {
    std::unique_lock<std::mutex> lock(mutex_);
    return changed_.wait_for(lock,maximum,[&]{return finished_;})&&accepted_;
  }
};
struct PreviewPacket {
  size_t source_index=0;
  PreviewProvenance provenance;
  std::vector<uint8_t> jpeg;
  uint64_t encoded_steady_ns=0;
  std::shared_ptr<PreviewMetadataReceipt> metadata_receipt;
};
// One latest pending JPEG per source. Replacement never waits for HTTP.
// Thread synchronization belongs to the caller, independently of observations.
class PreviewOutbox {
  size_t sources_,per_source_;
  std::deque<PreviewPacket> values_;
 public:
  explicit PreviewOutbox(size_t sources=2,size_t per_source=1):sources_(sources),per_source_(per_source){
    if(!per_source||per_source>16)throw std::invalid_argument("invalid preview queue bound");
  }
  bool push(PreviewPacket value) {
    if(value.source_index>=sources_||value.jpeg.size()>kMaxPreviewBytes)throw std::invalid_argument("invalid preview packet");
    if(per_source_==1) {
      for(auto& pending:values_)if(pending.source_index==value.source_index){pending=std::move(value);return true;}
    }
    bool dropped=false;
    if(std::count_if(values_.begin(),values_.end(),[&](const auto& pending){return pending.source_index==value.source_index;})>=static_cast<long>(per_source_)) {
      auto oldest=std::find_if(values_.begin(),values_.end(),[&](const auto& pending){return pending.source_index==value.source_index;});
      values_.erase(oldest);dropped=true;
    }
    values_.push_back(std::move(value));return dropped;
  }
  std::optional<PreviewPacket> pop() {
    if(values_.empty())return std::nullopt;
    auto result=std::move(values_.front());values_.pop_front();return result;
  }
  bool has_source(size_t source) const {
    return std::any_of(values_.begin(),values_.end(),[&](const auto& value){return value.source_index==source;});
  }
  std::optional<PreviewPacket> pop_source(size_t source) {
    auto found=std::find_if(values_.begin(),values_.end(),[&](const auto& value){return value.source_index==source;});
    if(found==values_.end())return std::nullopt;
    auto result=std::move(*found);values_.erase(found);return result;
  }
  size_t size()const{return values_.size();}
};
}
