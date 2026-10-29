// SPDX-License-Identifier: Apache-2.0
#include <gst/gst.h>
#include <gst/app/gstappsink.h>
#include <gst/rtp/gstrtpbuffer.h>
#include <glib-unix.h>
#include <curl/curl.h>
#include "gstnvdsmeta.h"
#include "gst-nvevent.h"
#include "nvds_analytics_meta.h"
#include "nvds_tracker_meta.h"
#include "tracker_3d.hpp"
#include "tracker_diagnostics.hpp"
#include "staged_tracking.hpp"
#include "detector_schedule.hpp"
#include "rfdetr_core.hpp"
#include "media_clock.hpp"
#include "source_epoch.hpp"
#include "source_clock_diagnostics.hpp"
#include "native_capture_clock.hpp"
#include "runtime_tuning.hpp"
#include "preview_core.hpp"
#include "analytics_config.hpp"
#include "rolling_output.hpp"
#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <csignal>
#include <cstdint>
#include <deque>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <memory>
#include <mutex>
#include <sstream>
#include <string>
#include <thread>
#include <vector>
#include <unordered_map>
#include <filesystem>
#include <unistd.h>

extern "C" void configure_source_for_ntp_sync(GstElement*);
namespace {
std::string quote(const std::string& s) {
  std::ostringstream out;out<<'"';
  for(unsigned char c:s) {
    if(c=='"'||c=='\\') out<<'\\'<<c;
    else if(c<32) out<<"\\u"<<std::hex<<std::setw(4)<<std::setfill('0')<<int(c)<<std::dec;
    else out<<c;
  }
  out<<'"';return out.str();
}
uint64_t utc_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count();
}
std::string uuid() {gchar* s=g_uuid_string_random();std::string result(s);g_free(s);return result;}
struct Source {
  std::string id,uri,session=uuid();
  uint64_t sequence=0,first_pts=GST_CLOCK_TIME_NONE;
  city::SourceEpochClock epoch_clock;
  bool recorded=false;
  GstSegment segment{};
  std::unordered_map<uint64_t,city::MediaClock> media_clocks;
  std::deque<uint64_t> media_order;
  city::SourceClockEvidence clock_evidence;
  city::NativeCaptureClock native_capture_clock;
};
struct Options {
  std::string site="expo-intersection",config="/opt/city/configs",post,output,model="rfdetr-small-fp16",analytics_config,ack_file;
  std::string preview_url,preview_stats_file;
  std::string preview_transport="jpeg",video_rtsp_base="rtsp://127.0.0.1:18558/city";
  std::string tracker_config,tracker_mode="camera-local",tracker_calibration_revision,local_tracker_config;
  std::string tracking_architecture;
  std::vector<Source> sources;
  unsigned width=1920,height=1080,frames=0,queue_limit=1024;
  uint64_t output_max_bytes=0;unsigned output_retained_files=0;
  unsigned mux_timeout_us=city::kDefaultMuxTimeoutUs;
  unsigned detector_cadence=1;
  unsigned decoder_extra_surfaces=0;
  bool decoder_low_latency=false;
  bool mux_sync_inputs=false;
  std::optional<unsigned> mux_max_latency_ns,mux_sync_inputs_ntp_ns;
  unsigned preview_fps=city::kDefaultPreviewFps;
  bool realtime=true,cpu_decode=false,tracker_diagnostics=false,source_clock_diagnostics=false,source_native_sei_clock=false;
  bool recorded_native_sei_clock=false;
  bool native_car_truck_family=false;
  bool native_tracker_sub_batches=false;
  unsigned replay_second_source_delay_ms=0;
};
struct App;
struct PreviewSource {
  App* app=nullptr;size_t index=0;GstElement* caps_filter=nullptr;
  std::mutex mutex;city::PreviewIdentityMap identities;city::PreviewSampler sampler;
  std::atomic<uint64_t> selected{0},rate_dropped{0},identity_missing{0},identity_evicted{0},
      geometry_mismatch{0},encoded{0},oversize{0},network_queue_dropped{0},published{0},
      post_failed{0},pending{0},queue_overruns{0},last_published_ns{0},metadata_ready{0},metadata_unconfirmed{0};
  std::atomic<unsigned> width{0},height{0};
  city::PreviewTiming selected_to_jpeg,post_queue,post_duration,metadata_wait;
  uint64_t video_origin_ns=0,last_video_pts=0;
};
struct App {
  Options options;GMainLoop* loop=nullptr;GstElement *pipeline=nullptr,*analytics=nullptr;
  std::string fusion_epoch=uuid();
  struct ScenarioReset {std::string epoch;uint64_t after_capture_ns=0;};
  std::mutex boundary_mutex;
  std::optional<ScenarioReset> pending_boundary;
  std::string tracking_epoch,seen_boundary_epoch;
  std::array<std::atomic<unsigned>,2> boundary_events{};
  unsigned tracker_stages=1;
  uint64_t boundary_capture_floor_ns=0;
  std::atomic<uint64_t> boundary_drain_deadline_ns{0},boundary_stale_mux_batches{0},boundary_stale_tracker_batches{0};
  struct BoundaryOutputSamples {uint64_t first_capture=0,last_capture=0,count=0;};
  std::unordered_map<unsigned,BoundaryOutputSamples> boundary_fresh_sources;
  std::atomic<bool> failed{false},stopping{false};
  uint64_t replay_epoch=utc_ns(),frames=0,peak_queue=0;
  uint64_t ambiguous_demo_frames=0,omitted_demo_objects=0;
  uint64_t staged_frame_token=0;
  city::DetectorCadence detector_cadence;
  std::atomic<uint64_t> scheduled_batches{0},full_batches{0},inferred_frames{0},tracked_frames{0};
  city::PreviewTiming preprocess_infer_latency,tracker_analytics_latency;
  std::array<std::atomic<unsigned>,2> decode_backend{},decode_extra_surfaces{};
  std::array<std::atomic<bool>,2> decode_low_latency{};
  city::MuxClockSettings mux_clock_settings;
  std::atomic<uint64_t> enqueued{0},published{0},backpressure_waits{0};
  std::mutex mutex,analytics_mutex,timeline_mutex,config_reload_mutex;std::condition_variable changed;std::deque<std::string> queue;
  std::thread sender;std::ofstream output;std::unique_ptr<city::RollingOutput> rolling_output;
  city::AnalyticsReload analytics_reload;
  std::optional<city::ConfigIdentity> analytics_seen;
  GstElement* preview_bin=nullptr;GstPad* preview_tee_pad=nullptr;
  std::atomic<bool> preview_failed{false};std::atomic<uint64_t> preview_batch_overruns{0};
  std::array<PreviewSource,2> previews;
  std::mutex preview_mutex;std::condition_variable preview_changed;city::PreviewOutbox preview_outbox,video_outbox{2,16};
  std::array<std::thread,2> preview_senders;std::string preview_error;
  uint64_t preview_stats_last_ns=0;
  std::array<uint64_t,2> preview_stats_encoded{},preview_stats_published{};
};
uint64_t steady_ns() {
  return std::chrono::duration_cast<std::chrono::nanoseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
constexpr uint64_t kBoundaryDrainNs=20000000000ULL;
bool boundary_drain_active(App* app) {
  const auto deadline=app->boundary_drain_deadline_ns.load();
  if(deadline&&steady_ns()>deadline)throw std::runtime_error("Scenario reset capture backlog drain exceeded 20 seconds");
  return deadline!=0;
}
struct BoundaryFrame {std::string tracking_epoch,fusion_epoch;};
NvDsMetaType boundary_meta_type() {
  static auto type=nvds_get_user_meta_type(const_cast<gchar*>("VSS.CITY.TRACKING_BOUNDARY.V1"));return type;
}
gpointer copy_boundary_meta(gpointer data,gpointer) {
  auto* meta=static_cast<NvDsUserMeta*>(data);
  return new BoundaryFrame(*static_cast<BoundaryFrame*>(meta->user_meta_data));
}
void release_boundary_meta(gpointer data,gpointer) {
  auto* meta=static_cast<NvDsUserMeta*>(data);
  delete static_cast<BoundaryFrame*>(meta->user_meta_data);meta->user_meta_data=nullptr;
}
void stamp_boundary_frame(NvDsBatchMeta* batch,NvDsFrameMeta* frame,const BoundaryFrame& value) {
  auto* meta=nvds_acquire_user_meta_from_pool(batch);
  if(!meta)throw std::runtime_error("Cannot allocate exact tracking epoch metadata");
  meta->user_meta_data=new BoundaryFrame(value);meta->base_meta.meta_type=boundary_meta_type();
  meta->base_meta.copy_func=copy_boundary_meta;meta->base_meta.release_func=release_boundary_meta;
  nvds_add_user_meta_to_frame(frame,meta);
}
const BoundaryFrame* boundary_frame(const NvDsFrameMeta* frame) {
  const BoundaryFrame* result=nullptr;
  for(auto* item=frame->frame_user_meta_list;item;item=item->next) {
    auto* meta=static_cast<NvDsUserMeta*>(item->data);
    if(meta->base_meta.meta_type==boundary_meta_type()) {
      if(result||!meta->user_meta_data)throw std::runtime_error("Ambiguous tracking epoch metadata");
      result=static_cast<BoundaryFrame*>(meta->user_meta_data);
    }
  }
  return result;
}
void note_boundary_output(App* app,unsigned source,const std::string& epoch,uint64_t capture) {
  if(!app->options.source_native_sei_clock||!app->boundary_drain_deadline_ns)return;
  const auto now=utc_ns();
  if(!city::native_capture_fresh(capture,now))return;
  std::lock_guard<std::mutex> lock(app->boundary_mutex);
  if(!app->boundary_drain_deadline_ns||app->pending_boundary||epoch!=app->tracking_epoch)return;
  boundary_drain_active(app); // the original deadline is never extended
  auto& sample=app->boundary_fresh_sources[source];
  if(!sample.count)sample.first_capture=capture;
  sample.last_capture=capture;++sample.count;
  if(app->boundary_fresh_sources.size()!=app->options.sources.size())return;
  for(const auto& item:app->boundary_fresh_sources) {
    const auto& seen=item.second;
    if(seen.count<3||seen.last_capture-seen.first_capture<1000000000ULL||
       !city::native_capture_fresh(seen.last_capture,now))return;
  }
  app->boundary_drain_deadline_ns=0;
  std::cerr<<"Scenario capture backlog drained after fresh tracker output; staleMuxBatches="<<app->boundary_stale_mux_batches
           <<" staleTrackerBatches="<<app->boundary_stale_tracker_batches<<'\n';
}
NvDsMetaType preview_meta_type() {
  static auto type=nvds_get_user_meta_type(const_cast<gchar*>("VSS.CITY.PREVIEW_FRAME.V1"));return type;
}
gpointer copy_preview_meta(gpointer data,gpointer) {
  auto* meta=static_cast<NvDsUserMeta*>(data);
  return new city::PreviewProvenance(*static_cast<city::PreviewProvenance*>(meta->user_meta_data));
}
void release_preview_meta(gpointer data,gpointer) {
  auto* meta=static_cast<NvDsUserMeta*>(data);
  delete static_cast<city::PreviewProvenance*>(meta->user_meta_data);meta->user_meta_data=nullptr;
}
void attach_preview_meta(NvDsBatchMeta* batch,NvDsFrameMeta* frame,city::PreviewProvenance provenance) {
  auto* meta=nvds_acquire_user_meta_from_pool(batch);if(!meta)return;
  meta->user_meta_data=new city::PreviewProvenance(std::move(provenance));
  meta->base_meta.meta_type=preview_meta_type();meta->base_meta.copy_func=copy_preview_meta;
  meta->base_meta.release_func=release_preview_meta;nvds_add_user_meta_to_frame(frame,meta);
}
gboolean preview_stats(gpointer data) {
  auto* app=static_cast<App*>(data);if(app->options.preview_url.empty()||app->options.preview_stats_file.empty())return G_SOURCE_CONTINUE;
  const auto path=app->options.preview_stats_file+".tmp";std::ofstream out(path);
  if(!out){std::cerr<<"Cannot write native preview statistics\n";return G_SOURCE_CONTINUE;}
  size_t pending,metadata_pending;std::string error;
  {std::lock_guard<std::mutex> lock(app->preview_mutex);pending=app->preview_outbox.size();metadata_pending=app->video_outbox.size();error=app->preview_error;}
  const auto now=steady_ns();const double elapsed=app->preview_stats_last_ns?double(now-app->preview_stats_last_ns)/1e9:0;
  out<<"{\"schemaVersion\":\"city.preview-native-status.v1\",\"enabled\":true,\"failed\":"<<(app->preview_failed?"true":"false")
     <<",\"transport\":"<<quote(app->options.preview_transport)<<",\"codec\":"<<quote(app->options.preview_transport=="webrtc"?"H264":"JPEG")
     <<",\"updatedAtNs\":"<<quote(std::to_string(utc_ns()))<<",\"error\":"<<quote(error)
     <<",\"fpsLimitPerSource\":"<<app->options.preview_fps<<",\"jpegQuality\":"<<(app->options.preview_transport=="webrtc"?0:70)<<",\"maxJpegBytes\":"<<city::kMaxPreviewBytes
     <<",\"identityLimitPerSource\":"<<city::kPreviewIdentityLimit<<",\"pendingJpegs\":"<<pending
     <<",\"pendingMetadata\":"<<metadata_pending<<",\"metadataQueueLimitPerSource\":16"
     <<",\"batchQueueOverruns\":"<<app->preview_batch_overruns;
  const auto detector_timing=app->preprocess_infer_latency.snapshot(),tracker_timing=app->tracker_analytics_latency.snapshot();
  out<<",\"pipeline\":{\"detectorCadence\":"<<app->options.detector_cadence
     <<",\"muxTimeoutUs\":"<<app->options.mux_timeout_us<<",\"batches\":"<<app->scheduled_batches
     <<",\"fullBatches\":"<<app->full_batches<<",\"inferredFrames\":"<<app->inferred_frames
     <<",\"trackedFrames\":"<<app->tracked_frames
     <<",\"preprocessInferPathMs\":{\"mean\":"<<detector_timing.mean_ms<<",\"p95Upper\":"<<detector_timing.p95_upper_ms<<'}'
     <<",\"trackerAnalyticsPathMs\":{\"mean\":"<<tracker_timing.mean_ms<<",\"p95Upper\":"<<tracker_timing.p95_upper_ms<<"}},\"sources\":[";
  for(size_t i=0;i<app->options.sources.size();++i) {
    auto& p=app->previews[i];size_t identities;
    {std::lock_guard<std::mutex> lock(p.mutex);identities=p.identities.size();}
    const uint64_t encoded=p.encoded,published=p.published;
    if(i)out<<',';
    out<<"{\"sourceId\":"<<quote(app->options.sources[i].id)<<",\"width\":"<<p.width<<",\"height\":"<<p.height
       <<",\"decoder\":"<<quote(app->decode_backend[i]==2?"hardware":app->decode_backend[i]==1?"cpu":"unknown")
       <<",\"decoderExtraSurfaces\":"<<app->decode_extra_surfaces[i]
       <<",\"decoderLowLatency\":"<<(app->decode_low_latency[i]?"true":"false")
       <<",\"selected\":"<<p.selected<<",\"rateDropped\":"<<p.rate_dropped<<",\"sourceQueueOverruns\":"<<p.queue_overruns
       <<",\"identityMissing\":"<<p.identity_missing<<",\"identityEvicted\":"<<p.identity_evicted<<",\"identitiesPending\":"<<identities
       <<",\"geometryMismatch\":"<<p.geometry_mismatch<<",\"encoded\":"<<p.encoded<<",\"oversizeDropped\":"<<p.oversize
       <<",\"networkQueueDropped\":"<<p.network_queue_dropped<<",\"published\":"<<p.published
       <<",\"postFailed\":"<<p.post_failed<<",\"pendingDropped\":"<<p.pending
       <<",\"metadataReadyBeforeVideo\":"<<p.metadata_ready<<",\"metadataUnconfirmedBeforeVideo\":"<<p.metadata_unconfirmed
       <<",\"lastPublishedAtNs\":"<<quote(std::to_string(p.last_published_ns.load()))
       <<",\"observedEncodedFps\":";
    if(elapsed>0)out<<double(encoded-app->preview_stats_encoded[i])/elapsed;else out<<"null";
    out<<",\"observedPublishedFps\":";
    if(elapsed>0)out<<double(published-app->preview_stats_published[i])/elapsed;else out<<"null";
    auto timing=[&](const char* name,city::PreviewTiming& values) {
      const auto t=values.snapshot();
      out<<quote(name)<<":{\"count\":"<<t.count<<",\"mean\":"<<t.mean_ms<<",\"last\":"<<t.last_ms
         <<",\"max\":"<<t.max_ms<<",\"p50Upper\":"<<t.p50_upper_ms<<",\"p95Upper\":"<<t.p95_upper_ms<<'}';
    };
    out<<",\"timingMs\":{";timing(app->options.preview_transport=="webrtc"?"selectedToEncode":"selectedToJpeg",p.selected_to_jpeg);out<<',';
    timing("postQueue",p.post_queue);out<<',';timing("post",p.post_duration);out<<',';timing("metadataAdmissionWait",p.metadata_wait);out<<"}}";
    app->preview_stats_encoded[i]=encoded;app->preview_stats_published[i]=published;
  }
  app->preview_stats_last_ns=now;
  out<<"]}\n";out.close();std::error_code ec;std::filesystem::rename(path,app->options.preview_stats_file,ec);
  if(ec)std::cerr<<"Cannot commit native preview statistics\n";
  return G_SOURCE_CONTINUE;
}
size_t response_body(char* data,size_t size,size_t nmemb,void* state) {
  auto* body=static_cast<std::string*>(state);const size_t bytes=size*nmemb;
  if(body->size()+bytes>65536)return 0;
  body->append(data,bytes);return bytes;
}
void preview_send_loop(App* app,size_t source_index) {
  CURL* curl=curl_easy_init();
  if(!curl){app->preview_failed=true;std::lock_guard<std::mutex> lock(app->preview_mutex);app->preview_error="curl-init";return;}
  curl_easy_setopt(curl,CURLOPT_URL,app->options.preview_url.c_str());
  curl_easy_setopt(curl,CURLOPT_CONNECTTIMEOUT_MS,100L);curl_easy_setopt(curl,CURLOPT_TIMEOUT_MS,500L);
  curl_easy_setopt(curl,CURLOPT_NOSIGNAL,1L);curl_easy_setopt(curl,CURLOPT_FOLLOWLOCATION,0L);
  curl_easy_setopt(curl,CURLOPT_WRITEFUNCTION,response_body);
  auto& outbox=app->options.preview_transport=="webrtc"?app->video_outbox:app->preview_outbox;
  while(!app->stopping) {
    std::optional<city::PreviewPacket> packet;
    {std::unique_lock<std::mutex> lock(app->preview_mutex);
      app->preview_changed.wait(lock,[&]{return app->stopping||outbox.has_source(source_index);});
      if(app->stopping)break;
      packet=outbox.pop_source(source_index);}
    if(!packet)continue;
    auto& stats=app->previews[packet->source_index];const auto& p=packet->provenance;
    curl_slist* headers=nullptr;
    const std::vector<std::string> values={app->options.preview_transport=="webrtc"?"Content-Type: application/json":"Content-Type: image/jpeg","Expect:",
      "X-City-Source-Id: "+p.source,"X-City-Session-Id: "+p.session,
      "X-City-Sequence: "+std::to_string(p.sequence),"X-City-Source-Time-Ns: "+std::to_string(p.source_time_ns),
      "X-City-Width: "+std::to_string(p.width),"X-City-Height: "+std::to_string(p.height),
      "X-City-Model-Revision: "+p.model};
    for(const auto& value:values)headers=curl_slist_append(headers,value.c_str());
    std::string response;curl_easy_setopt(curl,CURLOPT_HTTPHEADER,headers);
    curl_easy_setopt(curl,CURLOPT_POSTFIELDS,packet->jpeg.data());
    curl_easy_setopt(curl,CURLOPT_POSTFIELDSIZE_LARGE,curl_off_t(packet->jpeg.size()));
    curl_easy_setopt(curl,CURLOPT_WRITEDATA,&response);
    const auto started=steady_ns();
    if(packet->encoded_steady_ns)stats.post_queue.record(started-packet->encoded_steady_ns);
    const auto code=curl_easy_perform(curl);stats.post_duration.record(steady_ns()-started);
    long status=0;curl_easy_getinfo(curl,CURLINFO_RESPONSE_CODE,&status);
    if(code==CURLE_OK&&(status==200||status==201)){++stats.published;stats.last_published_ns=utc_ns();}
    else if(code==CURLE_OK&&status==202)++stats.pending;
    else ++stats.post_failed;
    if(packet->metadata_receipt)packet->metadata_receipt->finish(code==CURLE_OK&&(status==200||status==201));
    // No retries: an obsolete display image must not monopolize the sender.
    curl_easy_setopt(curl,CURLOPT_HTTPHEADER,nullptr);curl_slist_free_all(headers);
  }
  curl_easy_cleanup(curl);
}
GstPadProbeReturn preview_tag_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* context=static_cast<PreviewSource*>(data);auto* app=context->app;
  if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM) {
    auto* event=GST_PAD_PROBE_INFO_EVENT(info);
    if(GST_EVENT_TYPE(event)==GST_EVENT_SEGMENT) {
      // Encoder PTS is an opaque token on a private zero-based segment. It
      // must never be clipped against the source's RTSP/file segment start.
      GstSegment segment;gst_segment_init(&segment,GST_FORMAT_TIME);
      auto* replacement=gst_event_new_segment(&segment);
      gst_event_set_seqnum(replacement,gst_event_get_seqnum(event));
      GST_PAD_PROBE_INFO_DATA(info)=replacement;gst_event_unref(event);
    }
    return GST_PAD_PROBE_OK;
  }
  if(!(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER))return GST_PAD_PROBE_OK;
  if(app->preview_failed||app->stopping)return GST_PAD_PROBE_DROP;
  auto* buffer=GST_PAD_PROBE_INFO_BUFFER(info);auto* batch=gst_buffer_get_nvds_batch_meta(buffer);
  std::optional<city::PreviewProvenance> provenance;
  if(batch)for(auto* item=batch->frame_meta_list;item;item=item->next) {
    auto* frame=static_cast<NvDsFrameMeta*>(item->data);
    if(frame->source_id!=context->index)continue;
    for(auto* user=frame->frame_user_meta_list;user;user=user->next) {
      auto* meta=static_cast<NvDsUserMeta*>(user->data);
      if(meta->base_meta.meta_type==preview_meta_type()&&meta->user_meta_data)
        provenance=*static_cast<city::PreviewProvenance*>(meta->user_meta_data);
    }
  }
  if(!provenance){++context->identity_missing;return GST_PAD_PROBE_DROP;}
  const auto selected_at=steady_ns();
  if(!context->sampler.select(selected_at,app->options.preview_fps)){++context->rate_dropped;return GST_PAD_PROBE_DROP;}
  provenance->selected_steady_ns=selected_at;
  if(!provenance->width||!provenance->height||provenance->width>65535||provenance->height>65535){++context->geometry_mismatch;return GST_PAD_PROBE_DROP;}
  if(context->width!=provenance->width||context->height!=provenance->height) {
    const bool video=app->options.preview_transport=="webrtc";
    auto* caps=gst_caps_new_simple("video/x-raw","format",G_TYPE_STRING,video?"NV12":"I420",
        "width",G_TYPE_INT,gint(provenance->width),"height",G_TYPE_INT,gint(provenance->height),nullptr);
    if(video)gst_caps_set_features(caps,0,gst_caps_features_new("memory:NVMM",nullptr));
    g_object_set(context->caps_filter,"caps",caps,nullptr);gst_caps_unref(caps);
    context->width=provenance->width;context->height=provenance->height;
  }
  uint64_t tag;
  {std::lock_guard<std::mutex> lock(context->mutex);
    if(app->options.preview_transport=="webrtc") {
      if(!context->video_origin_ns)context->video_origin_ns=provenance->source_time_ns;
      const auto elapsed=provenance->source_time_ns>=context->video_origin_ns?provenance->source_time_ns-context->video_origin_ns:0;
      // Preserve capture cadence on a private segment. Repeated capture times
      // still need distinct encoder identities, with no guessed RTP offset.
      tag=std::max<uint64_t>(context->last_video_pts+GST_MSECOND,GST_SECOND+elapsed);
      context->last_video_pts=tag;context->identities.reserve_at(tag,std::move(*provenance));
    } else tag=context->identities.reserve(std::move(*provenance));
    context->identity_evicted=context->identities.evicted;}
  // The demuxed header is made writable only in the preview branch. Neither
  // camera PTS nor the analytics/observation buffer's timestamp is changed.
  buffer=gst_buffer_make_writable(buffer);GST_PAD_PROBE_INFO_DATA(info)=buffer;
  GST_BUFFER_PTS(buffer)=tag;GST_BUFFER_DTS(buffer)=GST_CLOCK_TIME_NONE;
  GST_BUFFER_DURATION(buffer)=GST_CLOCK_TIME_NONE;++context->selected;
  return GST_PAD_PROBE_OK;
}
GstFlowReturn preview_jpeg_sample(GstAppSink* sink,gpointer data) {
  auto* context=static_cast<PreviewSource*>(data);auto* app=context->app;
  auto* sample=gst_app_sink_pull_sample(sink);if(!sample)return GST_FLOW_OK;
  auto* buffer=gst_sample_get_buffer(sample);std::optional<city::PreviewProvenance> provenance;
  if(buffer){std::lock_guard<std::mutex> lock(context->mutex);provenance=context->identities.take(GST_BUFFER_PTS(buffer));}
  if(!provenance){++context->identity_missing;gst_sample_unref(sample);return GST_FLOW_OK;}
  auto* caps=gst_sample_get_caps(sample);int width=0,height=0;
  if(caps){const auto* shape=gst_caps_get_structure(caps,0);gst_structure_get_int(shape,"width",&width);gst_structure_get_int(shape,"height",&height);}
  if(width!=gint(provenance->width)||height!=gint(provenance->height)) {
    ++context->geometry_mismatch;gst_sample_unref(sample);return GST_FLOW_OK;
  }
  const auto bytes=gst_buffer_get_size(buffer);
  if(bytes>city::kMaxPreviewBytes){++context->oversize;gst_sample_unref(sample);return GST_FLOW_OK;}
  GstMapInfo map;
  if(!gst_buffer_map(buffer,&map,GST_MAP_READ)){++context->identity_missing;gst_sample_unref(sample);return GST_FLOW_OK;}
  city::PreviewPacket packet;packet.source_index=context->index;packet.provenance=std::move(*provenance);
  packet.encoded_steady_ns=steady_ns();
  if(packet.provenance.selected_steady_ns)context->selected_to_jpeg.record(packet.encoded_steady_ns-packet.provenance.selected_steady_ns);
  packet.jpeg.assign(map.data,map.data+map.size);gst_buffer_unmap(buffer,&map);gst_sample_unref(sample);++context->encoded;
  {std::lock_guard<std::mutex> lock(app->preview_mutex);
    if(app->preview_outbox.push(std::move(packet)))++context->network_queue_dropped;}
  // Each source has its own bounded sender. Wake both so the matching source
  // cannot remain asleep when the other thread checks its predicate first.
  app->preview_changed.notify_all();return GST_FLOW_OK;
}
// Observe the actual emitted RTP timestamp. Marker identifies a complete AU.
void preview_rtp_packet(PreviewSource* context,GstBuffer* buffer) {
  GstRTPBuffer rtp=GST_RTP_BUFFER_INIT;
  if(!buffer||!gst_rtp_buffer_map(buffer,GST_MAP_READ,&rtp))return;
  const bool marker=gst_rtp_buffer_get_marker(&rtp);
  const uint32_t timestamp=gst_rtp_buffer_get_timestamp(&rtp);
  gst_rtp_buffer_unmap(&rtp);if(!marker)return;
  auto* app=context->app;std::optional<city::PreviewProvenance> provenance;
  {std::lock_guard<std::mutex> lock(context->mutex);provenance=context->identities.take(GST_BUFFER_PTS(buffer));}
  if(!provenance){++context->identity_missing;return;}
  city::PreviewPacket packet;packet.source_index=context->index;packet.provenance=std::move(*provenance);
  packet.encoded_steady_ns=steady_ns();
  context->selected_to_jpeg.record(packet.encoded_steady_ns-packet.provenance.selected_steady_ns);
  const std::string body="{\"schemaVersion\":\"city.video-rtp.v1\",\"rtpTimestamp\":"+std::to_string(timestamp)+
      ",\"encoder\":\"nvenc-h264\",\"clockRate\":90000}";
  packet.jpeg.assign(body.begin(),body.end());++context->encoded;
  const auto receipt=packet.metadata_receipt=std::make_shared<city::PreviewMetadataReceipt>();
  {std::lock_guard<std::mutex> lock(app->preview_mutex);
    if(app->video_outbox.push(std::move(packet)))++context->network_queue_dropped;}
  app->preview_changed.notify_all();
  // The RTP marker completes this access unit. Admit its exact metadata before
  // releasing it to RTSP/WebRTC, instead of racing a fast UDP video path against
  // asynchronous HTTP/SSE. This queue is isolated and leaky upstream, so a slow
  // metadata service cannot block tracking. A bounded failure still releases
  // video; the browser retains its strict missing-identity behavior.
  const auto waiting=steady_ns();
  if(receipt->wait(std::chrono::milliseconds(200)))++context->metadata_ready;
  else ++context->metadata_unconfirmed;
  context->metadata_wait.record(steady_ns()-waiting);
}
GstPadProbeReturn preview_rtp_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* context=static_cast<PreviewSource*>(data);
  if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER)preview_rtp_packet(context,GST_PAD_PROBE_INFO_BUFFER(info));
  if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER_LIST) {
    auto* list=GST_PAD_PROBE_INFO_BUFFER_LIST(info);
    for(guint i=0;i<gst_buffer_list_length(list);++i)preview_rtp_packet(context,gst_buffer_list_get(list,i));
  }
  return GST_PAD_PROBE_OK;
}
void preview_new_payloader(GstElement*,GstElement* payloader,gpointer data) {
  if(g_object_class_find_property(G_OBJECT_GET_CLASS(payloader),"aggregate-mode"))g_object_set(payloader,"aggregate-mode",1,nullptr);
  auto* pad=gst_element_get_static_pad(payloader,"src");
  gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_BUFFER|GST_PAD_PROBE_TYPE_BUFFER_LIST),preview_rtp_probe,data,nullptr);
  gst_object_unref(pad);
}
bool post(CURL* curl,const std::string& url,const std::string& body) {
  std::string response;
  curl_easy_setopt(curl,CURLOPT_WRITEDATA,&response);
  curl_easy_setopt(curl,CURLOPT_URL,url.c_str());
  curl_easy_setopt(curl,CURLOPT_POSTFIELDS,body.data());
  curl_easy_setopt(curl,CURLOPT_POSTFIELDSIZE_LARGE,curl_off_t(body.size()));
  CURLcode code=curl_easy_perform(curl);long status=0;
  curl_easy_getinfo(curl,CURLINFO_RESPONSE_CODE,&status);
  if(code!=CURLE_OK || status<200 || status>=300) {
    std::cerr<<"Observation POST failed code="<<code<<" status="<<status<<'\n';return false;
  }
  using ReceiptRegex=std::unique_ptr<GRegex,decltype(&g_regex_unref)>;
  // These two fixed patterns apply to every frame. Keep their existing match
  // semantics while avoiding compilation on each observation receipt.
  static const ReceiptRegex accepted_pattern(g_regex_new("\"accepted\"[[:space:]]*:[[:space:]]*true",GRegexCompileFlags(0),GRegexMatchFlags(0),nullptr),g_regex_unref);
  static const ReceiptRegex duplicate_pattern(g_regex_new("\"reason\"[[:space:]]*:[[:space:]]*\"duplicate-or-out-of-order\"",GRegexCompileFlags(0),GRegexMatchFlags(0),nullptr),g_regex_unref);
  if(!accepted_pattern||!duplicate_pattern) {std::cerr<<"Cannot initialize observation receipt patterns\n";return false;}
  const bool accepted=g_regex_match(accepted_pattern.get(),response.c_str(),GRegexMatchFlags(0),nullptr);
  const bool duplicate=g_regex_match(duplicate_pattern.get(),response.c_str(),GRegexMatchFlags(0),nullptr);
  // Sequential publication plus per-run UUIDs makes only an HTTP retry capable
  // of returning a duplicate within this source session; it is idempotent.
  if(!accepted&&!duplicate) {std::cerr<<"Observation consumer rejected frame: "<<response<<'\n';return false;}
  return true;
}
void send_loop(App* app) {
  CURL* curl=curl_easy_init();curl_slist* headers=nullptr;
  headers=curl_slist_append(headers,"Content-Type: application/json");
  curl_easy_setopt(curl,CURLOPT_HTTPHEADER,headers);
  curl_easy_setopt(curl,CURLOPT_CONNECTTIMEOUT_MS,2000L);
  curl_easy_setopt(curl,CURLOPT_TIMEOUT_MS,5000L);
  curl_easy_setopt(curl,CURLOPT_NOSIGNAL,1L);
  curl_easy_setopt(curl,CURLOPT_WRITEFUNCTION,response_body);
  while(true) {
    std::string body;
    {std::unique_lock<std::mutex> lock(app->mutex);
      app->changed.wait(lock,[&]{return app->stopping||!app->queue.empty();});
      if(app->queue.empty()&&app->stopping)break;
      body=std::move(app->queue.front());app->queue.pop_front();
    }
    app->changed.notify_all();
    try {
      if(app->rolling_output)app->rolling_output->write_record(body);
      else if(app->output.is_open()) {
        app->output<<body<<'\n';app->output.flush();
        if(!app->output)throw std::runtime_error("Observation file write failed");
      }
    } catch(const std::exception& error) {
      std::cerr<<"Observation output failed: "<<error.what()<<'\n';app->failed=true;app->changed.notify_all();g_main_loop_quit(app->loop);break;
    }
    if(!app->options.post.empty()) {
      bool accepted=false;
      for(int attempt=0;attempt<3 && !accepted;attempt++) {
        accepted=post(curl,app->options.post,body);
        if(!accepted)std::this_thread::sleep_for(std::chrono::milliseconds(100*(attempt+1)));
      }
      if(!accepted) {app->failed=true;app->changed.notify_all();g_main_loop_quit(app->loop);break;}
    }
    ++app->published;
  }
  curl_slist_free_all(headers);curl_easy_cleanup(curl);
}
void submit(App* app,std::string body) {
  std::unique_lock<std::mutex> lock(app->mutex);
  // A callback can have entered before shutdown. Do not enqueue after the
  // publisher has observed stopping with an empty queue and exited.
  if(app->stopping||app->failed)return;
  const bool recorded=std::all_of(app->options.sources.begin(),app->options.sources.end(),
      [](const Source& source){return source.recorded;});
  if(!app->options.realtime&&recorded) {
    // Offline file evaluation is lossless and may run slower than inference.
    // Propagate bounded backpressure upstream instead of discarding event data.
    if(app->queue.size()>=app->options.queue_limit)++app->backpressure_waits;
    app->changed.wait(lock,[&]{return app->stopping||app->failed||app->queue.size()<app->options.queue_limit;});
    if(app->stopping||app->failed)return;
  }
  if(app->queue.size()>=app->options.queue_limit) {
    // Stop visibly rather than silently drop frames used for durable crossing rules.
    std::cerr<<"Observation consumer cannot keep up: bounded queue exhausted\n";
    app->failed=true;g_main_loop_quit(app->loop);return;
  }
  app->queue.push_back(std::move(body));++app->enqueued;
  app->peak_queue=std::max<uint64_t>(app->peak_queue,app->queue.size());app->changed.notify_all();
}
void string_array(std::ostringstream& out,const std::vector<std::string>& values) {
  out<<'[';for(size_t i=0;i<values.size();i++){if(i)out<<',';out<<quote(values[i]);}out<<']';
}
void write_ack(App* app,const std::string& status,uint64_t source_time=0,const std::string& error="",const std::string& revision_override="",const std::string& epoch_override="") {
  if(app->options.ack_file.empty())return;
  std::lock_guard<std::mutex> lock(app->analytics_mutex);
  const auto path=app->options.ack_file+".tmp";
  std::ofstream out(path);
  if(!out){std::cerr<<"Cannot write native analytics acknowledgement\n";return;}
  out<<"{\"revision\":"<<quote(!revision_override.empty()?revision_override:app->analytics_reload.acknowledgement_revision())
     <<",\"status\":"<<quote(status)<<",\"counterEpoch\":"<<quote(epoch_override.empty()?app->analytics_reload.epoch():epoch_override)
     <<",\"sourceTimeNs\":"<<quote(std::to_string(source_time))<<",\"sourceClockMode\":"
     <<quote(app->options.recorded_native_sei_clock?"recorded-native-sei":app->options.source_native_sei_clock?"source-native-sei":"source-rtcp")<<",\"error\":"<<quote(error)<<"}\n";
  out.close();std::error_code ec;std::filesystem::rename(path,app->options.ack_file,ec);
  if(ec)std::cerr<<"Cannot commit analytics acknowledgement: "<<ec.message()<<'\n';
}
void write_raw_tracker_diagnostics(std::ostream& out,const App& app,const NvDsFrameMeta* frame,
    const std::optional<city::DemoTrackIdCounts>& demo_ids,double sx,double sy) {
  std::vector<city::TrackerObjectDiagnostic> objects;
  objects.reserve(city::kTrackerDiagnosticObjectLimit);size_t count=0;
  for(auto* ol=frame->obj_meta_list;ol;ol=ol->next) {
    ++count;if(objects.size()==city::kTrackerDiagnosticObjectLimit)continue;
    const auto* object=static_cast<const NvDsObjectMeta*>(ol->data);
    city::TrackerObjectDiagnostic diagnostic;
    diagnostic.sdk_target_id=object->object_id;diagnostic.sdk_class_id=object->class_id;
    diagnostic.detector_observed=app.options.tracking_architecture=="mv3dt-native-v1"?
        city::staged_detection_current(city::staged_detection(const_cast<NvDsObjectMeta*>(object)),
            city::staged_frame(const_cast<NvDsFrameMeta*>(frame)),frame,object):
        std::isfinite(object->confidence)&&object->confidence>=0;
    diagnostic.id_rejected_as_ambiguous=demo_ids&&demo_ids->reject(object->object_id);
    const auto& detector=object->detector_bbox_info.org_bbox_coords;
    const auto& tracker=object->tracker_bbox_info.org_bbox_coords;
    const auto& rect=object->rect_params;
    diagnostic.detector_box=city::diagnostic_box(detector.left,detector.top,detector.width,detector.height,sx,sy);
    diagnostic.tracker_box=city::diagnostic_box(tracker.left,tracker.top,tracker.width,tracker.height,sx,sy);
    diagnostic.rect_box=city::diagnostic_box(rect.left,rect.top,rect.width,rect.height,sx,sy);
    for(auto* ul=object->obj_user_meta_list;ul;ul=ul->next) {
      const auto* user=static_cast<const NvDsUserMeta*>(ul->data);if(!user->user_meta_data)continue;
      const auto* value=static_cast<const float*>(user->user_meta_data);
      if(user->base_meta.meta_type==NVDS_OBJ_WORLD_FOOT_LOCATION)
        diagnostic.world_foot=std::array<double,2>{value[0],value[1]};
      else if(user->base_meta.meta_type==NVDS_OBJ_IMAGE_FOOT_LOCATION)
        diagnostic.image_foot=std::array<double,2>{value[0]*sx,value[1]*sy};
      else if(user->base_meta.meta_type==NVDS_OBJ_VISIBILITY)diagnostic.visibility=value[0];
      else if(user->base_meta.meta_type==NVDS_OBJ_IMAGE_CONVEX_HULL) {
        const auto* hull=static_cast<const NvDsObjConvexHull*>(user->user_meta_data);
        if(hull->list&&hull->numPoints<=64)
          for(unsigned i=0;i<hull->numPoints;++i)
            diagnostic.projected_hull.push_back({hull->list[2*i]*sx,hull->list[2*i+1]*sy});
      }
    }
    objects.push_back(std::move(diagnostic));
  }
  city::write_tracker_frame_diagnostics(out,frame->frame_num,frame->ntp_timestamp,frame->buf_pts,
      frame->source_frame_width,frame->source_frame_height,app.options.width,app.options.height,count,objects);
}
// Compare exact detector inputs with SDK outputs. This is diagnostic evidence,
// not a box matcher: proximity never supplies a missing stamp or an identity.
void write_detector_tracker_audit(std::ostream& out,NvDsFrameMeta* frame,
    const std::optional<city::DemoTrackIdCounts>& ids,double sx,double sy) {
  const auto* current=city::staged_frame(frame);
  out<<"{\"schemaVersion\":\"city.detector-tracker-audit.v1\",\"inputDetectionCount\":"
     <<(current?current->detector_input_count:0)
     <<",\"inputSnapshotComplete\":"<<(current&&current->detector_inputs_retained&&
         current->detector_inputs.size()==current->detector_input_count?"true":"false")
     <<",\"inputs\":[";
  bool first=true;
  if(current)for(const auto& input:current->detector_inputs) {
    if(!first)out<<',';
    first=false;
    out<<"{\"ordinal\":"<<input.ordinal<<",\"sdkClassId\":"<<input.raw_class
       <<",\"trackingClassId\":"<<input.tracking_class
       <<",\"confidence\":"<<input.raw_confidence<<",\"bboxPx\":";
    const auto& r=input.raw_rect;
    city::diagnostic_array(out,city::diagnostic_box(r.left,r.top,r.width,r.height,sx,sy));out<<'}';
  }
  out<<"],\"outputs\":[";first=true;size_t count=0;
  for(auto* item=frame->obj_meta_list;item;item=item->next) {
    if(++count>city::kTrackerDiagnosticObjectLimit)continue;
    auto* object=static_cast<NvDsObjectMeta*>(item->data);
    const auto* stamp=city::staged_detection(object);
    const bool exact=city::staged_detection_current(stamp,current,frame,object);
    if(!first)out<<',';
    first=false;
    out<<"{\"sdkTargetId\":"<<quote(std::to_string(object->object_id))
       <<",\"sdkClassId\":"<<object->class_id
       <<",\"sdkDetectorConfidencePresent\":"<<(std::isfinite(object->confidence)&&object->confidence>=0?"true":"false")
       <<",\"stampPresent\":"<<(stamp?"true":"false")
       <<",\"trackingClassId\":"<<(exact?std::to_string(stamp->tracking_class):"null")
       <<",\"detectorClassRestored\":"<<(exact&&stamp->class_restored?"true":"false")
       <<",\"currentDetectorStamp\":"<<(exact?"true":"false")
       <<",\"inputOrdinal\":"<<(exact?std::to_string(stamp->ordinal):"null")
       <<",\"untracked\":"<<(object->object_id==UNTRACKED_OBJECT_ID?"true":"false")
       <<",\"idRejectedAsAmbiguous\":"<<(ids&&ids->reject(object->object_id)?"true":"false")<<'}';
  }
  out<<"],\"outputSnapshotComplete\":"<<(count<=city::kTrackerDiagnosticObjectLimit?"true":"false")
     <<",\"rawSdkOutputCount\":"<<count<<'}';
}
GstPadProbeReturn detector_schedule_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);
  auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
  if(!batch)return GST_PAD_PROBE_OK;
  ++app->scheduled_batches;
  if(batch->num_frames_in_batch==app->options.sources.size())++app->full_batches;
  for(auto* item=batch->frame_meta_list;item;item=item->next) {
    auto* frame=static_cast<NvDsFrameMeta*>(item->data);
    frame->bInferDone=FALSE;
    if(frame->source_id>=app->options.sources.size()||!city::stamp_detector_schedule(batch,frame,{
        app->detector_cadence.select(frame->source_id,frame->buf_pts,app->options.detector_cadence),
        app->options.detector_cadence,batch->num_frames_in_batch,city::pipeline_steady_ns(),0})) {
      app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
    }
  }
  return GST_PAD_PROBE_OK;
}
GstPadProbeReturn detector_completion_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);
  auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
  if(!batch)return GST_PAD_PROBE_OK;
  for(auto* item=batch->frame_meta_list;item;item=item->next) {
    auto* frame=static_cast<NvDsFrameMeta*>(item->data);
    if(auto* schedule=city::detector_schedule(frame)) {
      schedule->detector_done_ns=city::pipeline_steady_ns();
      app->preprocess_infer_latency.record(schedule->detector_done_ns-schedule->entered_ns);
      if(frame->bInferDone)++app->inferred_frames;
      if(schedule->selected!=bool(frame->bInferDone)) {
        std::cerr<<"Detector cadence and SDK inference completion disagree\n";
        app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
      }
    }
  }
  return GST_PAD_PROBE_OK;
}
GstPadProbeReturn staged_detector_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);
  auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
  if(!batch)return GST_PAD_PROBE_OK;
  for(auto* item=batch->frame_meta_list;item;item=item->next) {
    if(!city::stamp_staged_detections(batch,static_cast<NvDsFrameMeta*>(item->data),++app->staged_frame_token,
        app->options.tracker_diagnostics,app->options.native_car_truck_family)) {
      std::cerr<<"Cannot preserve bounded current detector provenance for staged tracking\n";
      app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
    }
  }
  return GST_PAD_PROBE_OK;
}
GstPadProbeReturn native_restore_class_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);
  auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
  if(!batch)return GST_PAD_PROBE_OK;
  for(auto* item=batch->frame_meta_list;item;item=item->next)
    if(!city::restore_native_detector_classes(static_cast<NvDsFrameMeta*>(item->data))) {
      std::cerr<<"Native class restoration requires exact current detector provenance\n";
      app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
    }
  return GST_PAD_PROBE_OK;
}
GstPadProbeReturn tracker_entry_probe(GstPad*,GstPadProbeInfo* info,gpointer) {
  auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
  if(batch)for(auto* item=batch->frame_meta_list;item;item=item->next)
    if(auto* schedule=city::detector_schedule(static_cast<NvDsFrameMeta*>(item->data)))
      schedule->tracker_entered_ns=city::pipeline_steady_ns();
  return GST_PAD_PROBE_OK;
}
GstPadProbeReturn staged_local_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);
  auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
  if(!batch)return GST_PAD_PROBE_OK;
  for(auto* item=batch->frame_meta_list;item;item=item->next)
    if(!city::prepare_staged_second_input(batch,static_cast<NvDsFrameMeta*>(item->data))) {
      std::cerr<<"Invalid or unbounded first-stage local tracking provenance\n";
      app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
    }
  city::remove_first_tracker_batch_meta(batch);return GST_PAD_PROBE_OK;
}
struct PublishedObject {
  uint64_t local_id;gint class_id;NvOSD_RectParams rect;
  float confidence,tracker_confidence;bool observed;
  NvDsObjectMeta* native;
  const city::StagedLocalObject* local=nullptr;
};
void write_clock_diagnostics(std::ostream& out,uint64_t sdk_ntp,uint64_t pts,
    const std::optional<city::SourceClockFrameEvidence>& evidence,const city::SourceClockCounters& counters) {
  auto integer=[&](std::optional<uint64_t> value){if(value)out<<quote(std::to_string(*value));else out<<"null";};
  auto difference=[&](std::optional<uint64_t> a,std::optional<uint64_t> b) {
    if(!a||!b){out<<"null";return;}
    const auto magnitude=*a>=*b?*a-*b:*b-*a;
    if(magnitude>uint64_t(std::numeric_limits<int64_t>::max())){out<<"null";return;}
    out<<quote(std::string(*a<*b?"-":"")+std::to_string(magnitude));
  };
  out<<"{\"schemaVersion\":\"city.source-clock-diagnostics.v1\",\"mode\":\"observe-only\",\"sourcePtsNs\":"<<quote(std::to_string(pts))
     <<",\"sdkNtpUnixNs\":";integer(sdk_ntp?std::optional<uint64_t>(sdk_ntp):std::nullopt);
  out<<",\"exactSourcePtsEvidenceMatched\":"<<(evidence?"true":"false")<<",\"evidenceEpoch\":";
  if(evidence)out<<evidence->evidence_epoch;else out<<"null";
  out<<",\"stages\":{";
  for(size_t index=0;index<4;++index) {
    if(index)out<<',';
    out<<quote(city::clock_stage_name(city::ClockProbeStage(index)))<<':';
    const auto* sample=evidence?&evidence->stages[index]:nullptr;
    if(!sample||!sample->present){out<<"null";continue;}
    out<<"{\"state\":"<<quote(sample->state)<<",\"metaCount\":"<<sample->meta_count
       <<",\"duplicatePts\":"<<(sample->duplicate_pts?"true":"false")<<",\"referenceCaps\":"<<quote(sample->caps)
       <<",\"discontinuity\":"<<(sample->discontinuity?"true":"false")
       <<",\"probeWallUnixNs\":"<<quote(std::to_string(sample->probe_wall_ns))<<",\"referenceTimestampNs\":";integer(sample->timestamp_ns);
    out<<",\"referenceUnixNs\":";integer(sample->unix_ns);out<<",\"referenceDurationNs\":";integer(sample->duration_ns);
    out<<",\"sdkMinusReferenceNs\":";difference(sdk_ntp?std::optional<uint64_t>(sdk_ntp):std::nullopt,sample->unix_ns);
    out<<",\"probeWallMinusReferenceNs\":";difference(sample->probe_wall_ns,sample->unix_ns);out<<'}';
  }
  out<<"},\"counters\":{\"matchedObservations\":"<<counters.matched_observations
     <<",\"unmatchedObservations\":"<<counters.unmatched_observations<<",\"evictedUnconsumedPts\":"<<counters.evicted
     <<",\"retiredEvidenceEpochs\":"<<counters.retired_epochs<<",\"stages\":{";
  for(size_t i=0;i<4;++i) {
    if(i)out<<',';
    out<<quote(city::clock_stage_name(city::ClockProbeStage(i)))<<":{\"buffers\":"<<counters.buffers[i]
        <<",\"withReference\":"<<counters.with_reference[i]<<",\"missingReference\":"<<counters.missing[i]
        <<",\"unsupportedReference\":"<<counters.unsupported[i]
        <<",\"multipleReferences\":"<<counters.multiple[i]<<",\"duplicatePts\":"<<counters.duplicate_pts[i]<<'}';
  }
  out<<"}}}";
}
GstPadProbeReturn observation_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);
  if(app->failed||app->stopping||(app->options.frames&&app->frames>=app->options.frames))return GST_PAD_PROBE_DROP;
  auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
  if(!batch)return GST_PAD_PROBE_OK;
  for(auto* fl=batch->frame_meta_list;fl;fl=fl->next) {
    // A quit request is asynchronous. Enforce the budget before serializing
    // every frame, including the remainder of the last multi-source batch.
    if(app->stopping||(app->options.frames&&app->frames>=app->options.frames))break;
    auto* frame=static_cast<NvDsFrameMeta*>(fl->data);
    if(frame->source_id>=app->options.sources.size())continue;
    const bool staged=!app->options.local_tracker_config.empty();
    const bool native_mv3dt=app->options.tracking_architecture=="mv3dt-native-v1";
    const auto* local_frame=(staged||native_mv3dt)?city::staged_frame(frame):nullptr;
    if((staged||native_mv3dt)&&(!local_frame||(staged&&!local_frame->prepared)||!city::staged_key_current(local_frame->key,frame))) {
      std::cerr<<"Missing exact staged local frame snapshot; refusing observations\n";
      app->failed=true;g_main_loop_quit(app->loop);continue;
    }
    auto& source=app->options.sources[frame->source_id];
    uint64_t pts=frame->buf_pts;
    if(pts==GST_CLOCK_TIME_NONE) {
      std::cerr<<"Missing source PTS; refusing unaligned observations\n";
      app->failed=true;g_main_loop_quit(app->loop);continue;
    }
    if(source.first_pts==GST_CLOCK_TIME_NONE ||
       (source.epoch_clock.last_pts&&pts<*source.epoch_clock.last_pts))source.first_pts=pts;
    const uint64_t media_pts=pts-source.first_pts;
    std::optional<city::MediaClock> media_clock;
    if(source.recorded) {
      std::lock_guard<std::mutex> lock(app->timeline_mutex);
      auto found=source.media_clocks.find(pts);
      if(found!=source.media_clocks.end()){media_clock=found->second;source.media_clocks.erase(found);}
    }
    if(source.recorded&&!media_clock) {
      std::cerr<<"Missing source GstSegment mapping for decoded file PTS; refusing unaligned observations\n";
      app->failed=true;app->changed.notify_all();g_main_loop_quit(app->loop);continue;
    }
    const auto presentation_time=media_clock?media_clock->stream_time:media_pts;
    uint64_t source_time=0;std::string basis;
    std::optional<city::NativeCaptureFrame> native_capture;
    if(app->options.source_native_sei_clock) {
      try {
        std::lock_guard<std::mutex> lock(app->timeline_mutex);
        native_capture=source.native_capture_clock.take(pts,frame->ntp_timestamp);
        source_time=native_capture->sample.capture_ns;
        basis=app->options.recorded_native_sei_clock?"recorded-native-sei":"source-native-sei";
      } catch(const std::exception& error) {
        std::cerr<<"Native capture clock authority rejected after tracking: "<<error.what()<<'\n';
        app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
      }
    }
    else if(source.recorded) {source_time=app->replay_epoch+presentation_time;basis="recorded-pts";}
    else if(frame->ntp_timestamp) {source_time=frame->ntp_timestamp;basis="source-rtcp";}
    else {source_time=app->replay_epoch+media_pts;basis="arrival-pts-unsynchronized";}
    const auto epoch_reason=source.epoch_clock.observe(pts,source_time,basis);
    if(!epoch_reason.empty()) {
      source.session=uuid();source.sequence=0;
      // The diagnostic ID namespace belongs to every member source. A reset
      // in either camera retires it for both, even when the SDK reuses IDs.
      city::retire_diagnostic_fusion_epoch(app->fusion_epoch,uuid());
      std::cerr<<"Source "<<source.id<<" started a new timestamp epoch: "<<epoch_reason<<'\n';
    }
    std::optional<city::ConfigAcknowledgement> acknowledge;
    std::string rules_revision,analytics_revision;
    {std::lock_guard<std::mutex> lock(app->analytics_mutex);
      acknowledge=app->analytics_reload.processed();
      rules_revision=app->analytics_reload.revision();analytics_revision=app->analytics_reload.epoch();
    }
    if(acknowledge)write_ack(app,"active",source_time,"",acknowledge->revision,acknowledge->epoch);
    const unsigned w=frame->source_frame_width,h=frame->source_frame_height;
    if(!w||!h){app->failed=true;g_main_loop_quit(app->loop);continue;}
    const double sx=double(w)/app->options.width,sy=double(h)/app->options.height;
    const auto sequence=source.sequence++;
    std::optional<city::DemoTrackIdCounts> demo_ids;
    if(app->options.tracker_mode=="mv3dt-demo") {
      demo_ids.emplace();
      for(auto* ol=frame->obj_meta_list;ol;ol=ol->next)
        demo_ids->observe(static_cast<NvDsObjectMeta*>(ol->data)->object_id);
      if(demo_ids->omitted_objects()) {
        ++app->ambiguous_demo_frames;app->omitted_demo_objects+=demo_ids->omitted_objects();
        if(app->ambiguous_demo_frames<=4||app->ambiguous_demo_frames%100==0)
          std::cerr<<"Demo SDK ID ambiguity: source="<<source.id<<" frame="<<frame->frame_num
              <<" omittedObjects="<<demo_ids->omitted_objects()<<" duplicateIds="<<demo_ids->duplicate_ids
              <<" scope="<<(staged?"map-association-only":"operational-objects")
              <<" affectedFrames="<<app->ambiguous_demo_frames<<'\n';
      }
    }
    std::string tracking_epoch,fusion_epoch;
    try {
      const auto* provenance=boundary_frame(frame);
      if(provenance){tracking_epoch=provenance->tracking_epoch;fusion_epoch=provenance->fusion_epoch;}
      else {
        // CPU fixtures and the historical direct probe path predate the first
        // boundary. Once a boundary exists, missing per-frame proof is fatal.
        std::lock_guard<std::mutex> lock(app->boundary_mutex);
        if(!app->tracking_epoch.empty())throw std::runtime_error("Missing exact tracking epoch metadata");
        fusion_epoch=app->fusion_epoch;
      }
    } catch(const std::exception& error) {
      std::cerr<<error.what()<<'\n';app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
    }
    std::ostringstream out;out.imbue(std::locale::classic());out<<std::setprecision(9);
    out<<"{\"schemaVersion\":\"city.observations.v1\",\"siteId\":"<<quote(app->options.site)
       <<",\"sourceId\":"<<quote(source.id)<<",\"sourceSessionId\":"<<quote(source.session)
       <<",\"sequence\":"<<quote(std::to_string(sequence))
       <<",\"sourceFrameId\":"<<quote(std::to_string(local_frame?local_frame->key.source_frame:frame->frame_num))
       <<",\"sourceTimeNs\":"<<quote(std::to_string(source_time))
       <<",\"timestampBasis\":"<<quote(basis)
       <<",\"sourceEpochReason\":"<<(epoch_reason.empty()?"null":quote(epoch_reason))
       <<",\"mediaTimeSeconds\":"<<double(presentation_time)/1e9
       <<",\"rawSourcePtsNs\":"<<quote(std::to_string(pts))
       <<",\"mediaTimeBasis\":"<<quote(source.recorded?"gstreamer-segment-stream-time":"source-relative-pts")
       <<",\"image\":{\"width\":"<<w<<",\"height\":"<<h<<'}'
       <<",\"modelRevision\":"<<quote(app->options.model)
       <<",\"rulesRevision\":"<<quote(rules_revision)
       <<",\"trackingMode\":"<<quote(app->options.tracker_mode)
       <<",\"fusionEpoch\":"<<quote(fusion_epoch)
       <<",\"trackingEpoch\":"<<(tracking_epoch.empty()?"null":quote(tracking_epoch))
       <<",\"analyticsRevision\":"<<quote(analytics_revision);
    if(staged)out<<",\"trackingArchitecture\":\"nvdcf-local-then-mv3dt-v1\"";
    if(native_mv3dt)out<<",\"trackingArchitecture\":\"mv3dt-native-v1\"";
    if(app->options.native_car_truck_family)out<<",\"trackingClassPolicy\":\"car-truck-family-v1\"";
    if(const auto* schedule=city::detector_schedule(frame)) {
      ++app->tracked_frames;
      if(schedule->tracker_entered_ns)app->tracker_analytics_latency.record(city::pipeline_steady_ns()-schedule->tracker_entered_ns);
      out<<",\"detectorRan\":"<<(frame->bInferDone?"true":"false")
         <<",\"detectorCadence\":"<<schedule->cadence;
      if(app->options.tracker_diagnostics)out<<",\"pipelineTiming\":{\"batchSize\":"<<schedule->batch_size
         <<",\"preprocessInferMs\":"<<double(schedule->detector_done_ns-schedule->entered_ns)/1e6
         <<",\"trackerAnalyticsMs\":"<<double(city::pipeline_steady_ns()-(schedule->tracker_entered_ns?schedule->tracker_entered_ns:schedule->detector_done_ns))/1e6<<'}';
    }
    if(native_capture) {
      out<<",\"sourceClockEvidence\":{\"schemaVersion\":\"city.source-native-sei.v1\",\"method\":\"isaac-native-sei-wall-capture\",\"correlation\":\"exact-au-pts\""
         <<",\"captureTimeNs\":"<<quote(std::to_string(source_time))
         <<",\"auPtsNs\":"<<quote(std::to_string(pts))
         <<",\"frameCounter\":"<<quote(std::to_string(native_capture->sample.frame_counter))<<'}';
    }
    if(app->options.source_clock_diagnostics) {
      std::optional<city::SourceClockFrameEvidence> clock_evidence;city::SourceClockCounters clock_counters;
      {std::lock_guard<std::mutex> lock(app->timeline_mutex);clock_evidence=source.clock_evidence.take(pts);clock_counters=source.clock_evidence.counters;}
      out<<",\"sourceClockDiagnostics\":";write_clock_diagnostics(out,native_capture?native_capture->sdk_ntp_ns:frame->ntp_timestamp,pts,clock_evidence,clock_counters);
      out<<",\"muxClockSettings\":{\"syncInputs\":"<<(app->mux_clock_settings.sync_inputs?"true":"false")
         <<",\"maxLatencyNs\":"<<app->mux_clock_settings.max_latency_ns
         <<",\"syncInputsNtpNs\":"<<app->mux_clock_settings.sync_inputs_ntp_ns<<'}';
    }
    if(demo_ids)out<<",\"nativeTrackAmbiguity\":{\"duplicateIdCount\":"<<demo_ids->duplicate_ids
        <<",\"omittedObjectCount\":"<<(staged?local_frame->omitted_local_objects:demo_ids->omitted_objects())
        <<",\"rejectedMapObjectCount\":"<<(staged?demo_ids->omitted_objects():0)
        <<",\"duplicateLocalIdCount\":"<<(staged?local_frame->duplicate_local_ids:0)
        <<",\"capacityExceeded\":"<<(demo_ids->capacity_exceeded?"true":"false")<<'}';
    if(app->options.tracker_diagnostics||app->options.tracker_mode=="mv3dt-diagnostic") {
      out<<",\"trackerDiagnostics\":";write_raw_tracker_diagnostics(out,*app,frame,demo_ids,sx,sy);
      if(native_mv3dt) {out<<",\"detectorTrackerAudit\":";write_detector_tracker_audit(out,frame,demo_ids,sx,sy);}
    }
    out<<",\"objects\":[";
    std::vector<PublishedObject> publish_objects;
    if(staged) {
      for(const auto& local:local_frame->local)
        publish_objects.push_back({local.local_id,local.class_id,local.rect,local.confidence,
            local.tracker_confidence,local.observed,city::staged_map_object(frame,local,*demo_ids),&local});
    } else for(auto* ol=frame->obj_meta_list;ol;ol=ol->next) {
      auto* object=static_cast<NvDsObjectMeta*>(ol->data);
      if(object->class_id<0||object->class_id>=7||object->object_id==UNTRACKED_OBJECT_ID||(demo_ids&&demo_ids->reject(object->object_id)))continue;
      const auto* detection=native_mv3dt?city::staged_detection(object):nullptr;
      const bool observed=native_mv3dt?city::staged_detection_current(detection,local_frame,frame,object):
          std::isfinite(object->confidence)&&object->confidence>=0;
      publish_objects.push_back({object->object_id,object->class_id,object->rect_params,
          native_mv3dt?(observed?detection->raw_confidence:-1):object->confidence,object->tracker_confidence,observed,object});
    }
    bool first=true;
    for(const auto& published_object:publish_objects) {
      const auto& published=published_object;auto* object=published.native;
      const auto& box=published.rect;
      double x=std::clamp(double(box.left)*sx,0.,double(w));
      double y=std::clamp(double(box.top)*sy,0.,double(h));
      double bw=std::clamp(double(box.width)*sx,0.,double(w)-x);
      double bh=std::clamp(double(box.height)*sy,0.,double(h)-y);
      if(!std::isfinite(x)||!std::isfinite(y)||!std::isfinite(bw)||!std::isfinite(bh)||bw<=0||bh<=0)continue;
      if(!first)out<<',';
      first=false;
      std::optional<std::array<double,2>> world_foot,image_foot;
      std::optional<double> visibility;
      if(object&&app->options.tracker_mode!="camera-local") {
        for(auto* ul=object->obj_user_meta_list;ul;ul=ul->next) {
          auto* user=static_cast<NvDsUserMeta*>(ul->data);
          if(!user->user_meta_data)continue;
          if(user->base_meta.meta_type==NVDS_OBJ_WORLD_FOOT_LOCATION) {
            auto* value=static_cast<float*>(user->user_meta_data);
            if(city::valid_world_foot(value[0],value[1]))world_foot=std::array<double,2>{value[0],value[1]};
          } else if(user->base_meta.meta_type==NVDS_OBJ_IMAGE_FOOT_LOCATION) {
            auto* value=static_cast<float*>(user->user_meta_data);
            if(std::isfinite(value[0])&&std::isfinite(value[1]))image_foot=std::array<double,2>{value[0]*sx,value[1]*sy};
          } else if(user->base_meta.meta_type==NVDS_OBJ_VISIBILITY) {
            auto value=*static_cast<float*>(user->user_meta_data);
            if(city::valid_visibility(value))visibility=value;
          }
        }
      }
      const bool observed=published.observed;
      // Only the explicitly experimental demo mode can expose an association
      // hint. Canonical production promotion remains disabled by tracker_mode.
      const auto demo_id=city::demo_global_identity(app->options.tracker_mode,published.class_id,
          observed,basis,world_foot,image_foot,visibility,fusion_epoch,object?object->object_id:UNTRACKED_OBJECT_ID,
          native_capture.has_value(),native_mv3dt);
      out<<"{\"localTrackId\":"<<quote(std::to_string(published.local_id))
         <<",\"globalTrackId\":"<<(demo_id?quote(*demo_id):"null")
         <<",\"associationMethod\":"<<(demo_id?quote("mv3dt-demo"):"null")
         <<",\"class\":"<<quote(city::class_name(published.class_id))
         <<",\"confidence\":";
      if(observed)out<<published.confidence;else out<<"null";
      out<<",\"bboxPx\":["<<x<<','<<y<<','<<bw<<','<<bh<<']'
         <<",\"observedThisFrame\":"<<(observed?"true":"false")
         <<",\"trackerConfidence\":";
      if(std::isfinite(published.tracker_confidence)&&published.tracker_confidence>=0)out<<published.tracker_confidence;
      else out<<"null";
      if(world_foot&&image_foot) {
        out<<",\"native3D\":{\"method\":\"nvidia-mv3dt-9.2\",\"targetId\":"<<quote(std::to_string(object->object_id))
           <<",\"calibrationRevision\":"<<quote(app->options.tracker_calibration_revision)
           <<",\"worldPositionM\":["<<(*world_foot)[0]<<','<<(*world_foot)[1]<<']'
           <<",\"imageFootPx\":["<<(*image_foot)[0]<<','<<(*image_foot)[1]<<']'
           <<",\"visibility\":";
        if(visibility)out<<*visibility;else out<<"null";
        out<<",\"state\":"<<quote(observed?"observed":"predicted-or-peer");
        if(staged)out<<",\"localTargetId\":"<<quote(std::to_string(published.local_id))
            <<",\"localTrackingMethod\":"<<quote(city::kLocalTrackingMethod);
        out<<'}';
      }
      if(published.local&&published.local->has_analytics) {
        out<<",\"nativeAnalytics\":{\"roiStatus\":";string_array(out,published.local->roi_status);
        out<<",\"lineCrossings\":";string_array(out,published.local->line_crossings);
        out<<",\"direction\":"<<quote(published.local->direction)<<'}';
      }
      for(auto* ul=(!published.local&&object)?object->obj_user_meta_list:nullptr;ul;ul=ul->next) {
        auto* user=static_cast<NvDsUserMeta*>(ul->data);
        if(user->base_meta.meta_type==NVDS_USER_OBJ_META_NVDSANALYTICS) {
          auto* a=static_cast<NvDsAnalyticsObjInfo*>(user->user_meta_data);
          out<<",\"nativeAnalytics\":{\"roiStatus\":";string_array(out,a->roiStatus);
          out<<",\"lineCrossings\":";string_array(out,a->lcStatus);
          out<<",\"direction\":"<<quote(a->dirStatus)<<'}';
        }
      }
      out<<'}';
    }
    out<<']';
    for(auto* ul=frame->frame_user_meta_list;ul;ul=ul->next) {
      auto* user=static_cast<NvDsUserMeta*>(ul->data);
      if(user->base_meta.meta_type==NVDS_USER_FRAME_META_NVDSANALYTICS) {
        auto* a=static_cast<NvDsAnalyticsFrameMeta*>(user->user_meta_data);
        auto counts=[&](const auto& values) {
          out<<'{';bool first_count=true;
          for(const auto& value:values) {if(!first_count)out<<',';first_count=false;out<<quote(value.first)<<':'<<value.second;}
          out<<'}';
        };
        out<<",\"nativeAnalyticsFrame\":{\"roiCounts\":";counts(a->objInROIcnt);
        out<<",\"lineCrossingsCurrent\":";counts(a->objLCCurrCnt);
        out<<",\"lineCrossingsCumulative\":";counts(a->objLCCumCnt);out<<'}';
      }
    }
    out<<'}';submit(app,out.str());
    try {note_boundary_output(app,frame->source_id,tracking_epoch,source_time);}
    catch(const std::exception& error) {
      std::cerr<<"Scenario capture backlog rejected after tracking: "<<error.what()<<'\n';
      app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
    }
    if(!app->options.preview_url.empty()&&!app->preview_failed&&!app->failed)
      attach_preview_meta(batch,frame,{source.id,source.session,app->options.model,sequence,source_time,w,h});
    if(app->options.frames&&++app->frames>=app->options.frames)g_main_loop_quit(app->loop);
  }
  return GST_PAD_PROBE_OK;
}
gboolean bus_message(GstBus*,GstMessage* message,gpointer data) {
  auto* app=static_cast<App*>(data);
  if(GST_MESSAGE_TYPE(message)==GST_MESSAGE_ERROR) {
    GError* error=nullptr;gchar* detail=nullptr;gst_message_parse_error(message,&error,&detail);
    if(app->preview_bin&&gst_object_has_as_ancestor(GST_MESSAGE_SRC(message),GST_OBJECT(app->preview_bin))) {
      app->preview_failed=true;
      {std::lock_guard<std::mutex> lock(app->preview_mutex);app->preview_error=error->message;}
      std::cerr<<"Preview branch error (display disabled): "<<error->message<<" "<<(detail?detail:"")<<'\n';
      g_error_free(error);g_free(detail);preview_stats(app);return TRUE;
    }
    std::cerr<<"GStreamer error: "<<error->message<<" "<<(detail?detail:"")<<'\n';
    write_ack(app,"error",0,error->message);g_error_free(error);g_free(detail);app->failed=true;g_main_loop_quit(app->loop);
  } else if(GST_MESSAGE_TYPE(message)==GST_MESSAGE_EOS)g_main_loop_quit(app->loop);
  return TRUE;
}
struct SourcePadContext {App* app;size_t index;};
struct SourceClockProbeContext {App* app;size_t index;city::ClockProbeStage stage;};
GstPadProbeReturn native_capture_failure(App* app,const std::exception& error) {
  // Preserve the first cause; clearing caches must not replace it with a
  // cascade of missing-proof reports from other in-flight probes.
  if(app->failed.exchange(true))return GST_PAD_PROBE_DROP;
  std::cerr<<"Native capture clock rejected (no RTCP fallback): "<<error.what()<<'\n';
  {std::lock_guard<std::mutex> lock(app->timeline_mutex);
    for(auto& source:app->options.sources) {
      source.native_capture_clock.failed=true;source.native_capture_clock.frames.clear();
      source.native_capture_clock.order.clear();++source.native_capture_clock.epoch;
    }
  }
  write_ack(app,"error",0,std::string("native-capture-clock-rejected: ")+error.what());
  app->changed.notify_all();g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
}
GstPadProbeReturn native_au_clock_probe(GstPad* pad,GstPadProbeInfo* info,gpointer data) {
  auto* context=static_cast<SourcePadContext*>(data);auto* app=context->app;
  if(app->failed||app->stopping)return GST_PAD_PROBE_DROP;
  try {
    if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM) {
      auto* event=GST_PAD_PROBE_INFO_EVENT(info);
      std::lock_guard<std::mutex> lock(app->timeline_mutex);
      auto& clock=app->options.sources[context->index].native_capture_clock;
      if(GST_EVENT_TYPE(event)==GST_EVENT_SEGMENT)clock.segment(gst_event_get_seqnum(event));
      else if((GST_EVENT_TYPE(event)==GST_EVENT_FLUSH_START||GST_EVENT_TYPE(event)==GST_EVENT_FLUSH_STOP)&&clock.last_pts)
        clock.reject("Native capture stream flushed; new worker epoch required");
      return GST_PAD_PROBE_OK;
    }
    auto* buffer=GST_PAD_PROBE_INFO_BUFFER(info);if(!buffer)return GST_PAD_PROBE_OK;
    auto* caps=gst_pad_get_current_caps(pad);
    city::NativeAuSample au;
    try {au=city::native_capture_buffer(buffer,caps);if(caps)gst_caps_unref(caps);}
    catch(const std::exception& error) {
      if(dynamic_cast<const city::NativeCaptureMissingMetadata*>(&error)) {
        std::lock_guard<std::mutex> lock(app->timeline_mutex);
        auto& source=app->options.sources[context->index];
        if(!source.recorded&&source.native_capture_clock.discard_unproven_startup(steady_ns())) {
          if(caps)gst_caps_unref(caps);
          std::cerr<<"Discarding unproven initial RTSP picture before decode; source="<<source.id
              <<" count="<<source.native_capture_clock.unproven_startup_aus<<'\n';
          return GST_PAD_PROBE_DROP;
        }
      }
      // Retain the rejected encoded AU for data-only diagnosis. Never forward
      // it, reinterpret either clock, or render the rejected material.
      if(!app->options.ack_file.empty()&&gst_buffer_get_size(buffer)<=city::kNativeAuBytes) {
        GstMapInfo rejected{};
        if(gst_buffer_map(buffer,&rejected,GST_MAP_READ)) {
          const auto path=(std::filesystem::path(app->options.ack_file).parent_path()/
              ("native-clock-rejected-"+std::to_string(context->index)+".au")).string();
          std::ofstream file(path,std::ios::binary|std::ios::trunc);
          file.write(reinterpret_cast<const char*>(rejected.data),rejected.size);
          gst_buffer_unmap(buffer,&rejected);
          if(caps){auto* description=gst_caps_to_string(caps);std::ofstream(path+".caps")<<description;g_free(description);}
        }
      }
      if(caps)gst_caps_unref(caps);
      throw std::runtime_error(std::string(error.what())+" source="+app->options.sources[context->index].id+
          " au-pts="+std::to_string(GST_BUFFER_PTS(buffer)));
    }
    catch(...) {if(caps)gst_caps_unref(caps);throw;}
    if(au.has_picture) {
      std::lock_guard<std::mutex> lock(app->timeline_mutex);
      app->options.sources[context->index].native_capture_clock.record(GST_BUFFER_PTS(buffer),*au.capture,utc_ns(),
          GST_BUFFER_FLAG_IS_SET(buffer,GST_BUFFER_FLAG_DISCONT));
    }
    return GST_PAD_PROBE_OK;
  } catch(const std::exception& error){return native_capture_failure(app,error);}
}
GstPadProbeReturn native_decoded_clock_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* context=static_cast<SourcePadContext*>(data);
  if(context->app->failed||context->app->stopping)return GST_PAD_PROBE_DROP;
  if(!(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER))return GST_PAD_PROBE_OK;
  try {
    std::lock_guard<std::mutex> lock(context->app->timeline_mutex);
    context->app->options.sources[context->index].native_capture_clock.decoded(GST_BUFFER_PTS(GST_PAD_PROBE_INFO_BUFFER(info)));
    return GST_PAD_PROBE_OK;
  } catch(const std::exception& error){return native_capture_failure(context->app,error);}
}
// nvtracker's installed fillMOTFrame uses nonzero ntp_timestamp as the actual
// NvMOT timeMeta.frameTimeStamp. Stamp AFTER mux reconstruction but BEFORE
// preprocessing/inference and BOTH native trackers. buf_pts stays untouched.
GstPadProbeReturn native_pretracker_clock_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);
  if(!app->options.source_native_sei_clock)return GST_PAD_PROBE_OK;
  if(app->failed||app->stopping)return GST_PAD_PROBE_DROP;
  try {
    auto* batch=gst_buffer_get_nvds_batch_meta(GST_PAD_PROBE_INFO_BUFFER(info));
    if(!batch)throw std::runtime_error("Missing pre-tracker batch metadata");
    std::lock_guard<std::mutex> lock(app->timeline_mutex);
    const auto now=utc_ns();const bool draining=boundary_drain_active(app);bool fresh=true;
    // Validate the entire batch before discarding or preparing any record.
    // A stale frame must never mask a missing/duplicate proof in its partner.
    for(auto* link=batch->frame_meta_list;link;link=link->next) {
      auto* frame=static_cast<NvDsFrameMeta*>(link->data);
      if(frame->source_id>=app->options.sources.size()||frame->pad_index!=frame->source_id)
        throw std::runtime_error("Ambiguous pre-tracker source/pad identity");
      auto& clock=app->options.sources[frame->source_id].native_capture_clock;
      clock.qualified(frame->buf_pts,false);fresh=clock.fresh(frame->buf_pts,now,draining)&&fresh;
    }
    if(!fresh) {
      for(auto* link=batch->frame_meta_list;link;link=link->next) {
        auto* frame=static_cast<NvDsFrameMeta*>(link->data);
        app->options.sources[frame->source_id].native_capture_clock.discard_unprepared(frame->buf_pts);
      }
      ++app->boundary_stale_mux_batches;return GST_PAD_PROBE_DROP;
    }
    for(auto* link=batch->frame_meta_list;link;link=link->next) {
      auto* frame=static_cast<NvDsFrameMeta*>(link->data);
      if(frame->source_id>=app->options.sources.size()||frame->pad_index!=frame->source_id)
        throw std::runtime_error("Ambiguous pre-tracker source/pad identity");
      const auto sample=app->options.sources[frame->source_id].native_capture_clock.prepare(frame->buf_pts,frame->ntp_timestamp,now);
      frame->ntp_timestamp=sample.sample.capture_ns;
    }
    return GST_PAD_PROBE_OK;
  } catch(const std::exception& error){return native_capture_failure(app,error);}
}
GstPadProbeReturn reference_clock_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* context=static_cast<SourceClockProbeContext*>(data);
  if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM) {
    auto* event=GST_PAD_PROBE_INFO_EVENT(info);
    if(GST_EVENT_TYPE(event)==GST_EVENT_SEGMENT) {
      std::lock_guard<std::mutex> lock(context->app->timeline_mutex);
      context->app->options.sources[context->index].clock_evidence.segment(gst_event_get_seqnum(event));
    }
    return GST_PAD_PROBE_OK;
  }
  auto* buffer=GST_PAD_PROBE_INFO_BUFFER(info);
  if(!buffer)return GST_PAD_PROBE_OK;
  auto sample=city::reference_clock_sample(buffer,utc_ns());
  std::lock_guard<std::mutex> lock(context->app->timeline_mutex);
  context->app->options.sources[context->index].clock_evidence.record(GST_BUFFER_PTS(buffer),context->stage,std::move(sample));
  return GST_PAD_PROBE_OK;
}
void attach_reference_probe(GstPad* pad,const SourcePadContext* context,city::ClockProbeStage stage) {
  gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_BUFFER|GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM),reference_clock_probe,
      new SourceClockProbeContext{context->app,context->index,stage},[](gpointer p){delete static_cast<SourceClockProbeContext*>(p);});
}
void clock_element_added(GstBin*,GstBin*,GstElement* element,gpointer data) {
  auto* context=static_cast<SourcePadContext*>(data);
  auto* factory=gst_element_get_factory(element);if(!factory)return;
  const std::string name=gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory));
  if(name=="avdec_h264")context->app->decode_backend[context->index]=1;
  if(name=="nvv4l2decoder"&&!g_object_get_data(G_OBJECT(element),"city-decoder-configured")) {
    const auto extra=context->app->options.decoder_extra_surfaces;
    g_object_set(element,"num-extra-surfaces",extra,"low-latency-mode",context->app->options.decoder_low_latency,nullptr);
    guint actual=0;g_object_get(element,"num-extra-surfaces",&actual,nullptr);
    context->app->decode_backend[context->index]=2;context->app->decode_extra_surfaces[context->index]=actual;
    g_object_set_data(G_OBJECT(element),"city-decoder-configured",GINT_TO_POINTER(1));
    gboolean low_latency=FALSE;g_object_get(element,"low-latency-mode",&low_latency,nullptr);
    context->app->decode_low_latency[context->index]=low_latency;
    std::cerr<<"Actual decoder: source="<<context->index<<" factory="<<name<<" extraSurfaces="<<actual
        <<" lowLatency="<<low_latency<<'\n';
  }
  if(name!="rtph264depay"&&name!="h264parse")return;
  if(g_object_get_data(G_OBJECT(element),"city-clock-probe-attached"))return;
  auto* pad=gst_element_get_static_pad(element,"src");if(!pad)return;
  if(context->app->options.source_clock_diagnostics)
    attach_reference_probe(pad,context,name=="rtph264depay"?city::ClockProbeStage::Depay:city::ClockProbeStage::Parsed);
  if(context->app->options.source_native_sei_clock&&name=="h264parse")
    gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_BUFFER|GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM|GST_PAD_PROBE_TYPE_EVENT_FLUSH),
        native_au_clock_probe,new SourcePadContext{context->app,context->index},[](gpointer p){delete static_cast<SourcePadContext*>(p);});
  gst_object_unref(pad);g_object_set_data(G_OBJECT(element),"city-clock-probe-attached",GINT_TO_POINTER(1));
}
GstPadProbeReturn source_clock_probe(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* context=static_cast<SourcePadContext*>(data);auto* app=context->app;
  auto& source=app->options.sources[context->index];
  if(app->options.source_native_sei_clock&&(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER)) {
    try {
      std::lock_guard<std::mutex> lock(app->timeline_mutex);
      source.native_capture_clock.before_mux(GST_BUFFER_PTS(GST_PAD_PROBE_INFO_BUFFER(info)));
    } catch(const std::exception& error){return native_capture_failure(app,error);}
  }
  if(!source.recorded&&!app->options.source_clock_diagnostics)return GST_PAD_PROBE_OK;
  std::optional<city::ReferenceClockSample> reference;
  if(app->options.source_clock_diagnostics&&(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER))
    reference=city::reference_clock_sample(GST_PAD_PROBE_INFO_BUFFER(info),utc_ns());
  std::lock_guard<std::mutex> lock(app->timeline_mutex);
  if(app->options.source_clock_diagnostics&&(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM)) {
    auto* event=GST_PAD_PROBE_INFO_EVENT(info);
    if(GST_EVENT_TYPE(event)==GST_EVENT_SEGMENT)source.clock_evidence.segment(gst_event_get_seqnum(event));
  }
  if(reference)source.clock_evidence.record(GST_BUFFER_PTS(GST_PAD_PROBE_INFO_BUFFER(info)),city::ClockProbeStage::BeforeMux,std::move(*reference));
  if(!source.recorded)return GST_PAD_PROBE_OK;
  if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM) {
    GstEvent* event=GST_PAD_PROBE_INFO_EVENT(info);
    if(GST_EVENT_TYPE(event)==GST_EVENT_SEGMENT) {
      const GstSegment* segment=nullptr;gst_event_parse_segment(event,&segment);
      if(segment)source.segment=*segment;
    }
  }
  if(GST_PAD_PROBE_INFO_TYPE(info)&GST_PAD_PROBE_TYPE_BUFFER) {
    auto* buffer=GST_PAD_PROBE_INFO_BUFFER(info);
    const auto pts=GST_BUFFER_PTS(buffer);
    const auto mapped=city::media_clock(source.segment,pts);
    if(mapped) {
      source.media_clocks[pts]=*mapped;source.media_order.push_back(pts);
      while(source.media_order.size()>4096) {
        source.media_clocks.erase(source.media_order.front());source.media_order.pop_front();
      }
    }
  }
  return GST_PAD_PROBE_OK;
}
void decoded_pad(GstElement* decode,GstPad* pad,gpointer target) {
  GstCaps* caps=gst_pad_get_current_caps(pad);if(!caps)caps=gst_pad_query_caps(pad,nullptr);
  const GstStructure* structure=gst_caps_get_structure(caps,0);
  bool video=g_str_has_prefix(gst_structure_get_name(structure),"video/");
  if(video) {
    if(auto* context=static_cast<SourcePadContext*>(g_object_get_data(G_OBJECT(decode),"city-source-clock-context"))) {
      if(context->app->options.source_clock_diagnostics)attach_reference_probe(pad,context,city::ClockProbeStage::Decoded);
      if(context->app->options.source_native_sei_clock)
        gst_pad_add_probe(pad,GST_PAD_PROBE_TYPE_BUFFER,native_decoded_clock_probe,
            new SourcePadContext{context->app,context->index},[](gpointer p){delete static_cast<SourcePadContext*>(p);});
    }
    GstPad* sink=gst_element_get_static_pad(static_cast<GstElement*>(target),"sink");
    if(!gst_pad_is_linked(sink)&&gst_pad_link(pad,sink)!=GST_PAD_LINK_OK)
      std::cerr<<"Cannot link decoded video pad\n";
    gst_object_unref(sink);
  }
  gst_caps_unref(caps);
}
void source_setup(GstElement*,GstElement* source,gpointer data) {
  if(g_object_class_find_property(G_OBJECT_GET_CLASS(source),"latency"))
    g_object_set(source,"latency",200u,nullptr);
  if(g_str_has_prefix(G_OBJECT_TYPE_NAME(source),"GstRTSPSrc")) {
    // GstRTSPLowerTrans TCP = 4. Interleave RTP/RTCP on the RTSP connection;
    // keep the local demo independent of ephemeral UDP ports and packet loss.
    g_object_set(source,"protocols",4u,nullptr);
    const auto* app=static_cast<App*>(data);
    if(app&&app->options.source_clock_diagnostics) {
      if(!g_object_class_find_property(G_OBJECT_GET_CLASS(source),"add-reference-timestamp-meta")) {
        std::cerr<<"RTSP source lacks documented reference timestamp metadata property\n";
        auto* mutable_app=static_cast<App*>(data);mutable_app->failed=true;g_main_loop_quit(mutable_app->loop);return;
      }
      g_object_set(source,"add-reference-timestamp-meta",TRUE,nullptr);
    }
    configure_source_for_ntp_sync(source);
  }
}
GstElement* make(const char* factory,const std::string& name) {
  auto* e=gst_element_factory_make(factory,name.c_str());
  if(!e)throw std::runtime_error(std::string("Missing GStreamer plugin ")+factory);
  return e;
}
GstPadProbeReturn preview_branch_gate(GstPad*,GstPadProbeInfo*,gpointer data) {
  auto* app=static_cast<App*>(data);return app->preview_failed||app->stopping?GST_PAD_PROBE_DROP:GST_PAD_PROBE_OK;
}
// Input is already paced by the live source/tracker. The RTSP RECORD bin's
// internal TCP appsink otherwise synchronizes again using a negotiated global
// pipeline latency, retaining several raw/encoded frames and starving demux.
// Configure the sink through the documented deep-element-added signal after
// its factory defaults have been applied. RTP timestamps are left intact.
void preview_live_publish_element(GstBin*,GstBin*,GstElement* element,gpointer) {
  auto* factory=gst_element_get_factory(element);
  if(factory&&std::string(gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory)))=="appsink")
    g_object_set(element,"sync",FALSE,"async",FALSE,nullptr);
}
void build_preview(App* app,GstElement* tee) {
  app->preview_bin=gst_bin_new("city-preview");
  auto add=[&](const char* factory,const std::string& name){auto* e=make(factory,name);gst_bin_add(GST_BIN(app->preview_bin),e);return e;};
  auto* queue=add("queue","preview-batches");auto* demux=add("nvstreamdemux","preview-demux");
  g_object_set(queue,"max-size-buffers",1u,"max-size-bytes",0u,"max-size-time",guint64(0),"leaky",2,nullptr);
  g_signal_connect(queue,"overrun",G_CALLBACK(+[](GstElement*,gpointer p){++static_cast<App*>(p)->preview_batch_overruns;}),app);
  if(!gst_element_link(queue,demux))throw std::runtime_error("Cannot link preview demux");
  for(size_t i=0;i<app->options.sources.size();++i) {
    const auto suffix=std::to_string(i);auto& p=app->previews[i];p.app=app;p.index=i;
    auto* source_queue=add("queue","preview-source-queue"+suffix);
    auto* convert=add("nvvideoconvert","preview-download"+suffix);
    p.caps_filter=add("capsfilter","preview-original-geometry"+suffix);
    const bool video=app->options.preview_transport=="webrtc";
    auto* jpeg=add(video?"nvv4l2h264enc":"jpegenc","preview-encoder"+suffix);
    auto* sink=add(video?"rtspclientsink":"appsink","preview-sink"+suffix);
    g_object_set(source_queue,"max-size-buffers",1u,"max-size-bytes",0u,"max-size-time",guint64(0),"leaky",2,nullptr);
    g_signal_connect(source_queue,"overrun",G_CALLBACK(+[](GstElement*,gpointer data){++static_cast<PreviewSource*>(data)->queue_overruns;}),&p);
    // RAW (system-memory) caps request GPU conversion and download. The demux
    // keeps mux-sized surfaces; restore each source's exact original geometry.
    g_object_set(convert,"compute-hw",1,"nvbuf-memory-type",2,nullptr);
    auto* caps=gst_caps_from_string(video?"video/x-raw(memory:NVMM),format=NV12":"video/x-raw,format=I420");g_object_set(p.caps_filter,"caps",caps,nullptr);gst_caps_unref(caps);
    if(video) {
      // One NVENC session per source; all viewers share the resulting H.264.
      g_object_set(jpeg,"bitrate",3000000u,"num-B-Frames",0u,"iframeinterval",15u,"idrinterval",15u,
          "insert-sps-pps",TRUE,"tuning-info-id",3u,"preset-id",1u,"profile",0u,nullptr);
      const auto location=app->options.video_rtsp_base+"/"+app->options.sources[i].id+"/"+app->options.sources[i].session;
      g_object_set(sink,"location",location.c_str(),"protocols",4,"latency",0u,"async-handling",TRUE,nullptr);
      g_signal_connect(sink,"new-payloader",G_CALLBACK(preview_new_payloader),&p);
      g_signal_connect(sink,"deep-element-added",G_CALLBACK(preview_live_publish_element),nullptr);
      auto* parse=add("h264parse","preview-h264-parse"+suffix);
      g_object_set(parse,"config-interval",-1,nullptr);
      if(!gst_element_link_many(source_queue,convert,p.caps_filter,jpeg,parse,sink,nullptr))throw std::runtime_error("Cannot link hardware video preview");
    } else {
    g_object_set(jpeg,"quality",70,"snapshot",FALSE,nullptr);
    // The installed jpegenc/libjpeg-turbo path has no thread-count property;
    // one GStreamer streaming worker per source performs each software encode.
    if(g_object_class_find_property(G_OBJECT_GET_CLASS(jpeg),"threads"))g_object_set(jpeg,"threads",1u,nullptr);
    g_object_set(sink,"sync",FALSE,"async",FALSE,"max-buffers",1u,"drop",TRUE,"enable-last-sample",FALSE,"wait-on-eos",FALSE,nullptr);
    GstAppSinkCallbacks callbacks{};callbacks.new_sample=preview_jpeg_sample;
    gst_app_sink_set_callbacks(GST_APP_SINK(sink),&callbacks,&p,nullptr);
    if(!gst_element_link_many(source_queue,convert,p.caps_filter,jpeg,sink,nullptr))throw std::runtime_error("Cannot link source preview encoder");
    }
    GstPad* probe=gst_element_get_static_pad(source_queue,"src");
    gst_pad_add_probe(probe,GstPadProbeType(GST_PAD_PROBE_TYPE_BUFFER|GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM),preview_tag_probe,&p,nullptr);gst_object_unref(probe);
    auto* src=gst_element_request_pad_simple(demux,("src_"+suffix).c_str());auto* dst=gst_element_get_static_pad(source_queue,"sink");
    if(!src||gst_pad_link(src,dst)!=GST_PAD_LINK_OK)throw std::runtime_error("Cannot link demux source preview");
    gst_object_unref(src);gst_object_unref(dst);
  }
  auto* queue_sink=gst_element_get_static_pad(queue,"sink");
  auto* ghost=gst_ghost_pad_new("sink",queue_sink);gst_object_unref(queue_sink);gst_element_add_pad(app->preview_bin,ghost);
  gst_bin_add(GST_BIN(app->pipeline),app->preview_bin);
  app->preview_tee_pad=gst_element_request_pad_simple(tee,"src_%u");auto* dst=gst_element_get_static_pad(app->preview_bin,"sink");
  if(!app->preview_tee_pad)throw std::runtime_error("Cannot request optional preview tee pad");
  gst_pad_add_probe(app->preview_tee_pad,GST_PAD_PROBE_TYPE_BUFFER,preview_branch_gate,app,nullptr);
  if(gst_pad_link(app->preview_tee_pad,dst)!=GST_PAD_LINK_OK)throw std::runtime_error("Cannot attach optional preview branch");
  gst_object_unref(dst);
}
gboolean stop_signal(gpointer data) {auto* app=static_cast<App*>(data);app->stopping=true;app->changed.notify_all();app->preview_changed.notify_all();g_main_loop_quit(app->loop);return G_SOURCE_CONTINUE;}
void apply_pending_analytics(App* app) {
  // This buffer is blocked before nvdsanalytics. Only frames processed after
  // this property update may acknowledge its revision.
  bool applied;
  {std::lock_guard<std::mutex> lock(app->analytics_mutex);
    applied=app->analytics_reload.apply_pending([&](const std::string& path){g_object_set(app->analytics,"config-file",path.c_str(),nullptr);});
  }
  if(applied)write_ack(app,"pending");
}
GstPadProbeReturn apply_analytics(GstPad*,GstPadProbeInfo*,gpointer data) {
  apply_pending_analytics(static_cast<App*>(data));
  // One permanent blocking probe passes each buffer, then blocks the next.
  // Reloading a stalled source replaces one pending snapshot, never adds probes.
  return GST_PAD_PROBE_PASS;
}
bool reload_analytics(App* app) {
  std::lock_guard<std::mutex> configuration_lock(app->config_reload_mutex);
  const auto& path=app->options.analytics_config;
  std::string read_error;const auto generation=city::read_config_generation(path,read_error);
  if(!generation){write_ack(app,"error",0,read_error);return false;}
  app->analytics_seen=generation->identity;
  const auto& config_text=generation->bytes;
  std::istringstream lines(config_text);std::string line,revision;
  while(std::getline(lines,line)) {
    const std::string prefix="# city-rules-revision=";
    if(line.rfind(prefix,0)==0)revision=line.substr(prefix.size());
  }
  if(revision.empty())revision="unversioned-"+uuid();
  GKeyFile* key=g_key_file_new();GError* error=nullptr;
  if(!g_key_file_load_from_data(key,config_text.data(),config_text.size(),G_KEY_FILE_NONE,&error)) {
    write_ack(app,"error",0,error?error->message:"invalid INI",revision);
    if(error)g_error_free(error);
    g_key_file_unref(key);return false;
  }
  const auto width=g_key_file_get_integer(key,"property","config-width",nullptr);
  const auto height=g_key_file_get_integer(key,"property","config-height",nullptr);
  g_key_file_unref(key);
  if(width<=0||height<=0) {write_ack(app,"error",0,"Positive config-width/config-height required",revision);return false;}
  // Freeze the validated bytes. An atomic backend edit may replace the watched
  // path before the next video buffer arrives; that must not apply a newer
  // config under the old revision acknowledgement.
  std::string snapshot_error;bool staged;
  {std::lock_guard<std::mutex> lock(app->analytics_mutex);
    staged=app->analytics_reload.stage(*generation,revision,uuid(),snapshot_error);
  }
  if(!staged){write_ack(app,"error",0,snapshot_error,revision);return false;}
  std::cerr<<"Native analytics reload pending; revision="<<revision<<'\n';
  return true;
}
gboolean reload_signal(gpointer data) {reload_analytics(static_cast<App*>(data));return G_SOURCE_CONTINUE;}
gboolean watch_analytics(gpointer data) {
  auto* app=static_cast<App*>(data);
  auto identity=city::config_path_identity(app->options.analytics_config);
  bool changed;
  {std::lock_guard<std::mutex> configuration_lock(app->config_reload_mutex);changed=identity&&identity!=app->analytics_seen;}
  if(changed)reload_analytics(app);
  return G_SOURCE_CONTINUE;
}
std::string boundary_path(App* app,const char* filename) {
  return (std::filesystem::path(app->options.analytics_config).parent_path()/filename).string();
}
void write_boundary_ack(App* app,const App::ScenarioReset& request,const std::string& status,const std::string& error="") {
  const auto path=boundary_path(app,"scenario-boundary-ack.json"),temporary=path+".tmp";
  std::ofstream out(temporary);
  out<<"{\"schemaVersion\":\"city.scenario-boundary.v1\",\"status\":"<<quote(status)
     <<",\"trackingEpoch\":"<<quote(request.epoch)<<",\"afterCaptureNs\":"<<quote(std::to_string(request.after_capture_ns))
     <<",\"appliedAtNs\":"<<quote(std::to_string(utc_ns()))<<",\"trackerStages\":"<<app->tracker_stages
     <<",\"method\":\"serialized-nvtracker-stream-reset\",\"sourceClockReset\":false,\"error\":"<<quote(error)<<",\"sourceIds\":[";
  for(size_t i=0;i<app->options.sources.size();++i){if(i)out<<',';out<<quote(app->options.sources[i].id);}
  out<<"]}\n";out.close();
  if(!out||std::rename(temporary.c_str(),path.c_str()))std::cerr<<"Cannot write scenario boundary acknowledgement\n";
}
struct BoundaryTrackerContext {App* app;unsigned stage;};
GstPadProbeReturn boundary_tracker_event(GstPad*,GstPadProbeInfo* info,gpointer data) {
  auto* context=static_cast<BoundaryTrackerContext*>(data);
  auto* event=GST_PAD_PROBE_INFO_EVENT(info);
  if(event&&static_cast<GstNvEventType>(GST_EVENT_TYPE(event))==GST_NVEVENT_STREAM_RESET)
    ++context->app->boundary_events[context->stage];
  return GST_PAD_PROBE_OK;
}
bool dispatch_scenario_reset(App* app,GstPad* pad) {
  // Executed at inference output before either tracker. Each serialized event
  // drains that tracker's outstanding buffers and removes its source trackers.
  // It goes downstream only; RTP/decoder/mux/native-AU clock are untouched.
  for(auto& count:app->boundary_events)count=0;
  bool applied=true;
  for(size_t i=0;i<app->options.sources.size();++i)
    applied=gst_pad_push_event(pad,gst_nvevent_new_stream_reset(guint(i)))&&applied;
  for(unsigned stage=0;stage<app->tracker_stages;++stage)
    applied=app->boundary_events[stage]==app->options.sources.size()&&applied;
  return applied;
}
bool boundary_batch_after_capture(const NvDsBatchMeta* batch,uint64_t floor) {
  if(!batch||!batch->frame_meta_list)throw std::runtime_error("Missing boundary batch metadata");
  for(auto* item=batch->frame_meta_list;item;item=item->next) {
    const auto* frame=static_cast<NvDsFrameMeta*>(item->data);
    if(!frame->ntp_timestamp||frame->ntp_timestamp<floor)return false;
  }
  return true;
}
void discard_boundary_capture(App* app,NvDsBatchMeta* batch) {
  if(!app->options.source_native_sei_clock)return;
  // These exact-AU records were prepared before inference. A dropped frame
  // will never reach observation_probe, so consume its proof here once.
  std::lock_guard<std::mutex> lock(app->timeline_mutex);
  for(auto* item=batch->frame_meta_list;item;item=item->next) {
    auto* frame=static_cast<NvDsFrameMeta*>(item->data);
    if(frame->source_id>=app->options.sources.size())throw std::runtime_error("Invalid boundary source");
    app->options.sources[frame->source_id].native_capture_clock.take(frame->buf_pts,frame->ntp_timestamp);
  }
}
bool boundary_capture_fresh(App* app,NvDsBatchMeta* batch) {
  if(!app->options.source_native_sei_clock)return true;
  if(!batch||!batch->frame_meta_list)throw std::runtime_error("Missing boundary batch metadata");
  const bool draining=boundary_drain_active(app);const auto now=utc_ns();bool fresh=true;
  std::lock_guard<std::mutex> lock(app->timeline_mutex);
  for(auto* item=batch->frame_meta_list;item;item=item->next) {
    auto* frame=static_cast<NvDsFrameMeta*>(item->data);
    if(frame->source_id>=app->options.sources.size()||frame->pad_index!=frame->source_id)
      throw std::runtime_error("Ambiguous boundary source/pad identity");
    auto& clock=app->options.sources[frame->source_id].native_capture_clock;
    clock.qualified(frame->buf_pts,true,frame->ntp_timestamp);
    fresh=clock.fresh(frame->buf_pts,now,draining)&&fresh;
  }
  return fresh;
}
GstPadProbeReturn apply_scenario_boundary(GstPad* pad,GstPadProbeInfo* info,gpointer data) {
  auto* app=static_cast<App*>(data);std::optional<App::ScenarioReset> request;
  if(app->failed||app->stopping)return GST_PAD_PROBE_DROP;
  {std::lock_guard<std::mutex> lock(app->boundary_mutex);request=app->pending_boundary;}
  auto* buffer=GST_PAD_PROBE_INFO_BUFFER(info);
  auto* batch=buffer?gst_buffer_get_nvds_batch_meta(buffer):nullptr;
  try {
    if(request&&!app->boundary_drain_deadline_ns)app->boundary_drain_deadline_ns=steady_ns()+kBoundaryDrainNs;
    if(!boundary_capture_fresh(app,batch)) {
      discard_boundary_capture(app,batch);++app->boundary_stale_tracker_batches;return GST_PAD_PROBE_DROP;
    }
    const uint64_t floor=request?std::max(request->after_capture_ns,app->boundary_capture_floor_ns):app->boundary_capture_floor_ns;
    if(floor&&!boundary_batch_after_capture(batch,floor)) {
      discard_boundary_capture(app,batch);return GST_PAD_PROBE_DROP;
    }
    if(!batch||!batch->frame_meta_list)throw std::runtime_error("Missing boundary batch metadata");
    if(request) {
      if(!dispatch_scenario_reset(app,pad))throw std::runtime_error("stream-reset-not-acknowledged-by-every-tracker");
      // Reload unchanged ROI geometry; backend remains event authority.
      if(!reload_analytics(app))throw std::runtime_error("native-primitive-reset-failed");
      apply_pending_analytics(app);
      {std::lock_guard<std::mutex> lock(app->boundary_mutex);
        app->tracking_epoch=request->epoch;city::retire_diagnostic_fusion_epoch(app->fusion_epoch,uuid());
        app->boundary_capture_floor_ns=floor;app->boundary_fresh_sources.clear();
        if(app->pending_boundary&&app->pending_boundary->epoch==request->epoch)app->pending_boundary.reset();}
      write_boundary_ack(app,*request,"applied");
      std::cerr<<"Scenario tracking boundary applied; epoch="<<request->epoch<<" stages="<<app->tracker_stages<<'\n';
    }
    // Serialized tracker resets may block while their queues/MQTT clients
    // drain. The carrier batch must still meet the same 2s clock bound after
    // that wait, immediately before it is admitted to either tracker.
    if(!boundary_capture_fresh(app,batch)) {
      discard_boundary_capture(app,batch);++app->boundary_stale_tracker_batches;return GST_PAD_PROBE_DROP;
    }
    BoundaryFrame provenance;
    {std::lock_guard<std::mutex> lock(app->boundary_mutex);
      provenance={app->tracking_epoch,app->fusion_epoch};
    }
    for(auto* item=batch->frame_meta_list;item;item=item->next)
      stamp_boundary_frame(batch,static_cast<NvDsFrameMeta*>(item->data),provenance);
    return GST_PAD_PROBE_OK;
  } catch(const std::exception& error) {
    if(request)write_boundary_ack(app,*request,"error",error.what());
    std::cerr<<"Scenario boundary rejected: "<<error.what()<<'\n';
    app->failed=true;g_main_loop_quit(app->loop);return GST_PAD_PROBE_DROP;
  }
}
gboolean watch_scenario_boundary(gpointer data) {
  auto* app=static_cast<App*>(data);
  const auto path=boundary_path(app,"scenario-boundary.ini");
  std::ifstream stream(path,std::ios::binary);if(!stream)return G_SOURCE_CONTINUE;
  std::string bytes(4097,'\0');stream.read(bytes.data(),bytes.size());bytes.resize(stream.gcount());
  if(bytes.size()>4096)return G_SOURCE_CONTINUE;
  GKeyFile* key=g_key_file_new();GError* error=nullptr;
  if(!g_key_file_load_from_data(key,bytes.data(),bytes.size(),G_KEY_FILE_NONE,&error)) {
    if(error)g_error_free(error);
    g_key_file_unref(key);return G_SOURCE_CONTINUE;
  }
  gchar* epoch=g_key_file_get_string(key,"scenario-boundary","epoch",nullptr);
  const auto floor=g_key_file_get_uint64(key,"scenario-boundary","after-capture-ns",nullptr);
  if(epoch&&g_uuid_string_is_valid(epoch)&&floor) {
    std::lock_guard<std::mutex> lock(app->boundary_mutex);
    if(app->seen_boundary_epoch!=epoch) {
      app->seen_boundary_epoch=epoch;app->pending_boundary=App::ScenarioReset{epoch,floor};
      app->boundary_drain_deadline_ns=steady_ns()+kBoundaryDrainNs;app->boundary_fresh_sources.clear();
      app->boundary_stale_mux_batches=0;app->boundary_stale_tracker_batches=0;
    }
  }
  g_free(epoch);g_key_file_unref(key);return G_SOURCE_CONTINUE;
}
gint autoplug_select(GstElement*,GstPad*,GstCaps*,GstElementFactory* factory,gpointer data) {
  auto* app=static_cast<App*>(data);const gchar* name=gst_plugin_feature_get_name(GST_PLUGIN_FEATURE(factory));
  // GstAutoplugSelectResult is intentionally not exported by playback headers.
  // 0=TRY, 2=SKIP, per GStreamer's decodebin public signal contract.
  return app->options.cpu_decode && g_str_has_prefix(name,"nvv4l2decoder") ? 2 : 0;
}
// A serialized native tracker reset can block downstream while MQTT peers
// reconnect. Keep decoding live frames during that interval: superseded decoded
// buffers are expendable, but the capture clock and every admitted frame remain
// strictly validated. Recorded playback remains lossless and paced.
void configure_source_queue(GstElement* queue,const Source& source,bool native_clock) {
  g_object_set(queue,"max-size-buffers",4u,"max-size-bytes",0u,"max-size-time",guint64(0),
      "leaky",!source.recorded&&native_clock?2:0,nullptr);
}
Options parse_options(int argc,char** argv) {
  Options o;
  for(int i=1;i<argc;i++) {
    std::string a=argv[i];
    auto value=[&](){if(i+1>=argc)throw std::runtime_error("Missing value for "+a);return std::string(argv[++i]);};
    if(a=="--source") {
      auto s=value();auto split=s.find('=');if(split==std::string::npos)throw std::runtime_error("source is ID=URI");
      Source source;source.id=s.substr(0,split);source.uri=s.substr(split+1);
      source.recorded=source.uri.rfind("file://",0)==0;
      if(source.id.empty()||(!source.recorded&&source.uri.rfind("rtsp://",0)!=0&&source.uri.rfind("rtsps://",0)!=0))
        throw std::runtime_error("Only file:// and RTSP source URIs are supported");
      o.sources.push_back(source);
    } else if(a=="--site-id")o.site=value();
    else if(a=="--tracker-config")o.tracker_config=value();
    else if(a=="--tracking-architecture")o.tracking_architecture=value();
    else if(a=="--local-tracker-config")o.local_tracker_config=value();
    else if(a=="--tracker-mode")o.tracker_mode=city::tracker_mode(value());
    else if(a=="--tracker-calibration-revision")o.tracker_calibration_revision=value();
    else if(a=="--tracker-diagnostics")o.tracker_diagnostics=true;
    else if(a=="--config-dir")o.config=value();
    else if(a=="--post-url")o.post=value();
    else if(a=="--preview-url")o.preview_url=value();
    else if(a=="--preview-transport")o.preview_transport=value();
    else if(a=="--video-rtsp-base")o.video_rtsp_base=value();
    else if(a=="--preview-fps")o.preview_fps=city::parse_preview_fps(value());
    else if(a=="--preview-stats-file")o.preview_stats_file=value();
    else if(a=="--output")o.output=value();
    else if(a=="--output-max-bytes")o.output_max_bytes=city::output_unsigned(value());
    else if(a=="--output-retained-files") {
      const auto retained=city::output_unsigned(value());
      if(retained>8)throw std::runtime_error("--output-retained-files must be 0..8 previous files");
      o.output_retained_files=unsigned(retained);
    }
    else if(a=="--analytics-config")o.analytics_config=value();
    else if(a=="--analytics-ack-file")o.ack_file=value();
    else if(a=="--cpu-decode")o.cpu_decode=true;
    else if(a=="--model-revision")o.model=value();
    else if(a=="--width")o.width=city::parse_unsigned_option(value(),"--width");
    else if(a=="--height")o.height=city::parse_unsigned_option(value(),"--height");
    else if(a=="--frames")o.frames=city::parse_unsigned_option(value(),"--frames");
    else if(a=="--publisher-queue-size")o.queue_limit=city::parse_unsigned_option(value(),"--publisher-queue-size");
    else if(a=="--mux-timeout-us")o.mux_timeout_us=city::parse_mux_timeout(value());
    else if(a=="--detector-cadence") {
      o.detector_cadence=city::parse_unsigned_option(value(),"--detector-cadence");
      if(o.detector_cadence<1||o.detector_cadence>3)throw std::runtime_error("--detector-cadence must be 1..3");
    }
    else if(a=="--decoder-extra-surfaces") {
      o.decoder_extra_surfaces=city::parse_unsigned_option(value(),"--decoder-extra-surfaces");
      if(o.decoder_extra_surfaces>8)throw std::runtime_error("--decoder-extra-surfaces must be 0..8");
    }
    else if(a=="--decoder-low-latency")o.decoder_low_latency=true;
    else if(a=="--source-clock-diagnostics")o.source_clock_diagnostics=true;
    else if(a=="--source-native-sei-clock")o.source_native_sei_clock=true;
    else if(a=="--recorded-native-sei-clock")o.recorded_native_sei_clock=true;
    else if(a=="--native-car-truck-family")o.native_car_truck_family=true;
    else if(a=="--native-tracker-sub-batches")o.native_tracker_sub_batches=true;
    else if(a=="--replay-second-source-delay-ms") {
      o.replay_second_source_delay_ms=city::parse_unsigned_option(value(),"--replay-second-source-delay-ms");
      if(o.replay_second_source_delay_ms>100)throw std::runtime_error("Replay source delay must be 0..100ms");
    }
    else if(a=="--mux-sync-inputs")o.mux_sync_inputs=true;
    else if(a=="--mux-max-latency-ns"||a=="--mux-sync-inputs-ntp-ns") {
      const auto ns=city::parse_unsigned_option(value(),a.c_str());
      if(ns>1000000000u)throw std::runtime_error(a+" must be 0..1000000000 nanoseconds");
      if(a=="--mux-max-latency-ns")o.mux_max_latency_ns=ns;else o.mux_sync_inputs_ntp_ns=ns;
    }
    else if(a=="--unpaced")o.realtime=false;
    else if(a=="--help") {
      std::cout<<"city-worker --source ID=file:///video.mp4 [--source ID=rtsp://...] --config-dir DIR "
        "[--site-id ID] [--post-url URL] [--output FILE] [--output-max-bytes N] [--output-retained-files 0..8] [--frames N] [--unpaced] "
        "[--mux-timeout-us 1000..1000000] [--detector-cadence 1..3] [--decoder-extra-surfaces 0..8] [--decoder-low-latency (I/P-only input)] [--model-revision REVISION] "
        "[--source-clock-diagnostics] [--source-native-sei-clock] [--recorded-native-sei-clock (files only; no HTTP/preview)] [--mux-sync-inputs] [--mux-max-latency-ns 0..1000000000] [--mux-sync-inputs-ntp-ns 0..1000000000] "
        "[--tracker-mode camera-local|mv3dt-diagnostic|mv3dt-demo] [--tracker-config FILE] [--tracking-architecture mv3dt-native-v1] [--native-car-truck-family] [--tracker-calibration-revision REVISION] [--tracker-diagnostics] [--local-tracker-config ORDINARY_NVDCF_FILE] "
        "[--preview-url http://HOST:9184/api/v1/city/preview] [--preview-fps 1..30] [--preview-stats-file FILE]\n";std::exit(0);
    } else throw std::runtime_error("Unknown argument "+a);
  }
  if(o.sources.empty()||o.sources.size()>2||!o.width||!o.height||!o.queue_limit||o.queue_limit>16384)
    throw std::runtime_error("One or two sources and positive geometry are required");
  if(o.post.empty()&&o.output.empty())throw std::runtime_error("Select --post-url and/or --output");
  if((o.output_max_bytes||o.output_retained_files)&&o.output.empty())throw std::runtime_error("Output rotation flags require --output");
  if(o.output_retained_files&&!o.output_max_bytes)throw std::runtime_error("--output-retained-files requires positive --output-max-bytes");
  if(o.sources.size()==2&&o.sources[0].id==o.sources[1].id)throw std::runtime_error("Source IDs must be distinct");
  if(o.recorded_native_sei_clock) {
    if(o.source_native_sei_clock||!o.post.empty()||!o.preview_url.empty()||
       std::any_of(o.sources.begin(),o.sources.end(),[](const Source& s){return !s.recorded;}))
      throw std::runtime_error("Recorded native SEI replay requires only files, no live clock flag, HTTP posting or preview");
    o.source_native_sei_clock=true;
    for(auto& source:o.sources)source.native_capture_clock.recorded_replay=true;
  }
  if(o.source_native_sei_clock&&!o.recorded_native_sei_clock&&std::any_of(o.sources.begin(),o.sources.end(),[](const Source& s){return s.recorded;}))
    throw std::runtime_error("Native SEI capture clock requires explicitly live Isaac sources");
  if(o.tracker_mode!="camera-local"&&(o.tracker_config.empty()||o.tracker_calibration_revision.empty()))
    throw std::runtime_error("MV3DT needs an explicit tracker configuration and calibration revision");
  if(!o.tracking_architecture.empty()&&(o.tracking_architecture!="mv3dt-native-v1"||
      o.tracker_mode!="mv3dt-demo"||!o.local_tracker_config.empty()))
    throw std::runtime_error("Native MV3DT requires exactly one tracker in mv3dt-demo mode");
  if(o.detector_cadence>1&&o.tracking_architecture!="mv3dt-native-v1")
    throw std::runtime_error("Detector cadence requires single native MV3DT");
  if(o.native_car_truck_family&&o.tracking_architecture!="mv3dt-native-v1")
    throw std::runtime_error("Car/truck association family requires one native MV3DT stage");
  if(o.native_tracker_sub_batches&&o.tracking_architecture!="mv3dt-native-v1")
    throw std::runtime_error("Per-camera sub-batches require one native MV3DT stage");
  if(o.native_tracker_sub_batches&&(!o.recorded_native_sei_clock||!o.post.empty()||!o.preview_url.empty()))
    throw std::runtime_error("Per-camera tracker sub-batches are an offline experiment; live identity qualification is required");
  if(o.replay_second_source_delay_ms&&(!o.recorded_native_sei_clock||o.sources.size()!=2||!o.realtime))
    throw std::runtime_error("Source pacing delay requires a paced, two-file recorded SEI experiment");
  if(o.detector_cadence>1&&(!o.post.empty()||!o.preview_url.empty()))
    throw std::runtime_error("Detector cadence above one is an offline quality trial; live consumers require fresh detector observations");
  if(o.cpu_decode&&(o.decoder_low_latency||o.decoder_extra_surfaces))
    throw std::runtime_error("Decoder surface and low-latency controls require hardware decoding");
  if(!o.local_tracker_config.empty()) {
    if(o.tracker_mode!="mv3dt-demo")throw std::runtime_error("--local-tracker-config requires explicit mv3dt-demo mode");
    city::validate_staged_local_config(o.local_tracker_config);
  }
  // The engine selection pins the weights; observations also identify the
  // compiled object-counting policy used by this worker/parser pair.
  o.model=city::tracking_model_revision(o.model);
  o.model+=";color=source-rgba-v1";
  if(o.native_car_truck_family)o.model+=";association=car-truck-family-v1";
  if(!o.preview_url.empty()) {
    if(o.preview_transport!="jpeg"&&o.preview_transport!="webrtc")throw std::runtime_error("--preview-transport must be jpeg or webrtc");
    const auto metadata_url=o.preview_transport=="webrtc"?o.preview_url.substr(0,o.preview_url.size()>12?o.preview_url.size()-12:0)+"/preview":o.preview_url;
    if(!city::preview_url_valid(metadata_url)||(o.preview_transport=="webrtc"&&o.preview_url.substr(o.preview_url.size()>12?o.preview_url.size()-12:0)!="/video/frame"))
      throw std::runtime_error("Preview URL must be the matching HTTP(S) city preview or video/frame endpoint");
    if(o.video_rtsp_base!="rtsp://127.0.0.1:18558/city")throw std::runtime_error("Video publisher must use the controlled loopback relay");
    if(!city::preview_header_valid(o.model))throw std::runtime_error("Preview model revision is not a safe bounded header value");
    for(const auto& source:o.sources)if(!city::preview_header_valid(source.id))throw std::runtime_error("Preview source ID is not a safe bounded header value");
    if(o.preview_stats_file.empty()&&!o.ack_file.empty())o.preview_stats_file=(std::filesystem::path(o.ack_file).parent_path()/"preview-stats.json").string();
    if(o.preview_stats_file.empty()&&!o.output.empty())o.preview_stats_file=o.output+".preview.json";
  }
  if(o.analytics_config.empty())o.analytics_config=o.config+"/analytics.ini";
  return o;
}
}
int main(int argc,char** argv) {
  App app;
  try {
    app.options=parse_options(argc,argv);gst_init(nullptr,nullptr);curl_global_init(CURL_GLOBAL_ALL);
    app.loop=g_main_loop_new(nullptr,FALSE);app.pipeline=gst_pipeline_new("city-pipeline");
    auto* mux=make("nvstreammux","mux");
    auto* convert=make("nvvideoconvert","rgba-convert");auto* rgba_caps=make("capsfilter","rgba");
    auto* preprocess=make("nvdspreprocess","city-preprocess");auto* infer=make("nvinfer","city-detection");
    auto* tracker=make("nvtracker","city-tracking");app.analytics=make("nvdsanalytics","city-analytics");
    auto* local_tracker=app.options.local_tracker_config.empty()?nullptr:make("nvtracker","city-local-tracking");
    auto* sink=make("fakesink","sink");
    bool live=false;for(const auto& s:app.options.sources)live|=!s.recorded;
    g_object_set(mux,"batch-size",guint(app.options.sources.size()),"width",app.options.width,
        "height",app.options.height,"batched-push-timeout",gint(app.options.mux_timeout_us),"live-source",live,
        "attach-sys-ts",FALSE,nullptr);
    if(app.options.source_clock_diagnostics||app.options.mux_sync_inputs||app.options.mux_max_latency_ns||app.options.mux_sync_inputs_ntp_ns) {
      app.mux_clock_settings=city::configure_mux_clock_settings(mux,app.options.mux_sync_inputs,
          app.options.mux_max_latency_ns,app.options.mux_sync_inputs_ntp_ns);
      std::cerr<<"Actual mux clock settings: syncInputs="<<app.mux_clock_settings.sync_inputs
          <<" maxLatencyNs="<<app.mux_clock_settings.max_latency_ns<<" syncInputsNtpNs="<<app.mux_clock_settings.sync_inputs_ntp_ns<<'\n';
    }
    // Spark has no VIC. Explicit GPU transform and CUDA device RGBA surfaces.
    g_object_set(convert,"compute-hw",1,"nvbuf-memory-type",2,nullptr);
    GstCaps* caps=gst_caps_from_string("video/x-raw(memory:NVMM),format=RGBA");
    g_object_set(rgba_caps,"caps",caps,nullptr);gst_caps_unref(caps);
    auto prep_path=app.options.config+"/preprocess.ini",infer_path=app.options.config+"/infer.ini";
    auto track_path=app.options.tracker_config.empty()?app.options.config+"/tracker.yml":app.options.tracker_config;
    g_object_set(preprocess,"config-file",prep_path.c_str(),nullptr);
    g_object_set(infer,"config-file-path",infer_path.c_str(),"batch-size",guint(app.options.sources.size()),"input-tensor-meta",TRUE,nullptr);
    g_object_set(tracker,"ll-lib-file","/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
        "ll-config-file",track_path.c_str(),"tracker-width",640u,"tracker-height",384u,
        "gpu-id",0u,"tracking-id-reset-mode",1u,nullptr);
    if(app.options.native_tracker_sub_batches) {
      g_object_set(tracker,"sub-batches",app.options.sources.size()==2?"0;1":"0",nullptr);
      std::cerr<<"Native MV3DT per-camera sub-batches enabled\n";
    }
    if(local_tracker)g_object_set(local_tracker,"ll-lib-file","/opt/nvidia/deepstream/deepstream/lib/libnvds_nvmultiobjecttracker.so",
        "ll-config-file",app.options.local_tracker_config.c_str(),"tracker-width",640u,"tracker-height",384u,"gpu-id",0u,"tracking-id-reset-mode",1u,nullptr);
    if(!reload_analytics(&app))throw std::runtime_error("Cannot load initial analytics configuration");
    apply_pending_analytics(&app);
    // Each recorded source is paced before batching. Batched mux PTS must not
    // impose a second clock wait on mixed-frame-rate source batches.
    g_object_set(sink,"sync",FALSE,"async",FALSE,nullptr);
    gst_bin_add_many(GST_BIN(app.pipeline),mux,convert,rgba_caps,preprocess,infer,tracker,app.analytics,sink,nullptr);
    if(local_tracker)gst_bin_add(GST_BIN(app.pipeline),local_tracker);
    if(!gst_element_link_many(mux,convert,rgba_caps,preprocess,infer,nullptr))
      throw std::runtime_error("Failed to link DeepStream analytics pipeline");
    auto* schedule_pad=gst_element_get_static_pad(preprocess,"sink");
    gst_pad_add_probe(schedule_pad,GST_PAD_PROBE_TYPE_BUFFER,detector_schedule_probe,&app,nullptr);
    gst_object_unref(schedule_pad);
    auto* completed_pad=gst_element_get_static_pad(infer,"src");
    gst_pad_add_probe(completed_pad,GST_PAD_PROBE_TYPE_BUFFER,detector_completion_probe,&app,nullptr);
    gst_object_unref(completed_pad);
    if(app.options.source_native_sei_clock) {
      auto* clock_pad=gst_element_get_static_pad(mux,"src");
      gst_pad_add_probe(clock_pad,GST_PAD_PROBE_TYPE_BUFFER,native_pretracker_clock_probe,&app,nullptr);gst_object_unref(clock_pad);
      std::cerr<<"Actual source clock mode: "<<(app.options.recorded_native_sei_clock?"recorded-native-sei":"source-native-sei")
          <<" (exact encoded AU capture handoff; not physical exposure)\n";
    }
    if(local_tracker) {
      // Native ROI counters consume the first camera-local handles as well.
      // Snapshot them before restoring current raw detections for MV3DT.
      if(!gst_element_link_many(infer,local_tracker,app.analytics,tracker,nullptr))
        throw std::runtime_error("Failed to link explicit staged tracking pipeline");
      auto* detector_pad=gst_element_get_static_pad(infer,"src");
      gst_pad_add_probe(detector_pad,GST_PAD_PROBE_TYPE_BUFFER,staged_detector_probe,&app,nullptr);gst_object_unref(detector_pad);
      auto* local_pad=gst_element_get_static_pad(app.analytics,"src");
      gst_pad_add_probe(local_pad,GST_PAD_PROBE_TYPE_BUFFER,staged_local_probe,&app,nullptr);gst_object_unref(local_pad);
    } else {
      if(!gst_element_link_many(infer,tracker,app.analytics,nullptr))
        throw std::runtime_error("Failed to link single tracking pipeline");
      auto* tracker_pad=gst_element_get_static_pad(tracker,"sink");
      gst_pad_add_probe(tracker_pad,GST_PAD_PROBE_TYPE_BUFFER,tracker_entry_probe,&app,nullptr);gst_object_unref(tracker_pad);
      if(app.options.tracking_architecture=="mv3dt-native-v1") {
        auto* detector_pad=gst_element_get_static_pad(infer,"src");
        gst_pad_add_probe(detector_pad,GST_PAD_PROBE_TYPE_BUFFER,staged_detector_probe,&app,nullptr);gst_object_unref(detector_pad);
        if(app.options.native_car_truck_family) {
          auto* restore_pad=gst_element_get_static_pad(tracker,"src");
          gst_pad_add_probe(restore_pad,GST_PAD_PROBE_TYPE_BUFFER,native_restore_class_probe,&app,nullptr);gst_object_unref(restore_pad);
        }
      }
    }
    app.tracker_stages=local_tracker?2:1;
    for(unsigned stage=0;stage<app.tracker_stages;++stage) {
      auto* stage_element=local_tracker&&stage==0?local_tracker:tracker;
      auto* stage_pad=gst_element_get_static_pad(stage_element,"src");
      gst_pad_add_probe(stage_pad,GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM,boundary_tracker_event,
          new BoundaryTrackerContext{&app,stage},[](gpointer p){delete static_cast<BoundaryTrackerContext*>(p);});
      gst_object_unref(stage_pad);
    }
    auto* boundary_pad=gst_element_get_static_pad(infer,"src");
    gst_pad_add_probe(boundary_pad,GST_PAD_PROBE_TYPE_BUFFER,apply_scenario_boundary,&app,nullptr);
    gst_object_unref(boundary_pad);
    auto* observation_output=local_tracker?tracker:app.analytics;
    if(app.options.preview_url.empty()) {
      if(!gst_element_link(observation_output,sink))throw std::runtime_error("Failed to link observation sink");
    } else {
      auto* tee=make("tee","after-analytics");auto* metadata_queue=make("queue","lossless-metadata-output");
      g_object_set(tee,"allow-not-linked",TRUE,nullptr);
      g_object_set(metadata_queue,"max-size-buffers",4u,"max-size-bytes",0u,"max-size-time",guint64(0),nullptr);
      gst_bin_add_many(GST_BIN(app.pipeline),tee,metadata_queue,nullptr);
      if(!gst_element_link_many(observation_output,tee,metadata_queue,sink,nullptr))throw std::runtime_error("Failed to link observation tee output");
      try {build_preview(&app,tee);}
      catch(const std::exception& error) {
        app.preview_failed=true;app.preview_error=error.what();
        if(app.preview_tee_pad) {
          if(auto* peer=gst_pad_get_peer(app.preview_tee_pad)){gst_pad_unlink(app.preview_tee_pad,peer);gst_object_unref(peer);}
          gst_element_release_request_pad(tee,app.preview_tee_pad);gst_object_unref(app.preview_tee_pad);app.preview_tee_pad=nullptr;
        }
        if(app.preview_bin) {
          if(GST_OBJECT_PARENT(app.preview_bin)==GST_OBJECT(app.pipeline))gst_bin_remove(GST_BIN(app.pipeline),app.preview_bin);
          else gst_object_unref(app.preview_bin);
          app.preview_bin=nullptr;
        }
        std::cerr<<"Optional preview unavailable: "<<error.what()<<'\n';
      }
      g_timeout_add(1000,preview_stats,&app);
    }
    for(size_t i=0;i<app.options.sources.size();i++) {
      const auto suffix=std::to_string(i);
      auto* decode=make("uridecodebin","source"+suffix);
      auto* queue=make("queue","queue"+suffix);
      auto* source_convert=make("nvvideoconvert","source-upload"+suffix);
      auto* source_caps=make("capsfilter","source-nvmm"+suffix);
      // Convert while each decoded source still carries its own YUV range and
      // matrix. NV12 batching loses that information for full-range Isaac
      // streams; RGBA here matches NVIDIA source-bin preprocessing exactly.
      GstCaps* upload_caps=gst_caps_from_string("video/x-raw(memory:NVMM),format=RGBA");
      g_object_set(source_caps,"caps",upload_caps,nullptr);gst_caps_unref(upload_caps);
      g_object_set(source_convert,"compute-hw",1,"nvbuf-memory-type",2,nullptr);
      auto* pace=make("identity","pace"+suffix);
      g_object_set(decode,"uri",app.options.sources[i].uri.c_str(),nullptr);
      configure_source_queue(queue,app.options.sources[i],app.options.source_native_sei_clock);
      g_object_set(pace,"sync",app.options.realtime&&app.options.sources[i].recorded,nullptr);
      // Change arrival scheduling only, preserving encoded capture evidence,
      // PTS, and images. This reproduces partial batches in offline tests.
      if(i==1&&app.options.replay_second_source_delay_ms)
        g_object_set(pace,"ts-offset",gint64(app.options.replay_second_source_delay_ms)*GST_MSECOND,nullptr);
      gst_bin_add_many(GST_BIN(app.pipeline),decode,queue,source_convert,source_caps,pace,nullptr);
      if(!gst_element_link_many(queue,source_convert,source_caps,pace,nullptr))throw std::runtime_error("Failed to link source queue");
      g_signal_connect(decode,"pad-added",G_CALLBACK(decoded_pad),queue);
      g_signal_connect(decode,"autoplug-select",G_CALLBACK(autoplug_select),&app);
      g_signal_connect(decode,"source-setup",G_CALLBACK(source_setup),&app);
      {
        auto* context=new SourcePadContext{&app,i};
        g_object_set_data_full(G_OBJECT(decode),"city-source-clock-context",context,[](gpointer p){delete static_cast<SourcePadContext*>(p);});
        g_signal_connect(decode,"deep-element-added",G_CALLBACK(clock_element_added),context);
      }
      GstPad* src=gst_element_get_static_pad(pace,"src");
      gst_pad_add_probe(src,GstPadProbeType(GST_PAD_PROBE_TYPE_BUFFER|GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM),
          source_clock_probe,new SourcePadContext{&app,i},[](gpointer p){delete static_cast<SourcePadContext*>(p);});
      const auto name="sink_"+suffix;
      GstPad* dst=gst_element_request_pad_simple(mux,name.c_str());
      if(!dst||gst_pad_link(src,dst)!=GST_PAD_LINK_OK)throw std::runtime_error("Failed to link source to mux");
      gst_object_unref(src);gst_object_unref(dst);
    }
    GstPad* pad=gst_element_get_static_pad(observation_output,"src");
    gst_pad_add_probe(pad,GST_PAD_PROBE_TYPE_BUFFER,observation_probe,&app,nullptr);gst_object_unref(pad);
    pad=gst_element_get_static_pad(app.analytics,"sink");
    gst_pad_add_probe(pad,GstPadProbeType(GST_PAD_PROBE_TYPE_BLOCK_DOWNSTREAM|GST_PAD_PROBE_TYPE_BUFFER),apply_analytics,&app,nullptr);gst_object_unref(pad);
    auto* bus=gst_pipeline_get_bus(GST_PIPELINE(app.pipeline));gst_bus_add_watch(bus,bus_message,&app);gst_object_unref(bus);
    g_unix_signal_add(SIGTERM,stop_signal,&app);g_unix_signal_add(SIGINT,stop_signal,&app);
    g_unix_signal_add(SIGHUP,reload_signal,&app);
    g_timeout_add(250,watch_analytics,&app);
    g_timeout_add(100,watch_scenario_boundary,&app);
    if(!app.options.output.empty()) {
      if(app.options.output_max_bytes)app.rolling_output=std::make_unique<city::RollingOutput>(app.options.output,app.options.output_max_bytes,app.options.output_retained_files);
      else {app.output.open(app.options.output);if(!app.output)throw std::runtime_error("Cannot open observation output");}
    }
    app.sender=std::thread(send_loop,&app);
    if(!app.options.preview_url.empty()&&!app.preview_failed)
      for(size_t i=0;i<app.options.sources.size();++i)app.preview_senders[i]=std::thread(preview_send_loop,&app,i);
    std::cerr<<"Starting city pipeline: model="<<app.options.model<<" trackingArchitecture="<<app.options.tracking_architecture<<" trackerMode="<<app.options.tracker_mode<<" source count="<<app.options.sources.size()<<'\n';
    if(gst_element_set_state(app.pipeline,GST_STATE_PLAYING)==GST_STATE_CHANGE_FAILURE)
      throw std::runtime_error("Cannot start pipeline");
    g_main_loop_run(app.loop);
  } catch(const std::exception& e) {std::cerr<<"city-worker: "<<e.what()<<'\n';app.failed=true;}
  app.stopping=true;app.changed.notify_all();app.preview_changed.notify_all();
  if(app.pipeline)gst_element_set_state(app.pipeline,GST_STATE_NULL);
  if(app.sender.joinable())app.sender.join();
  for(auto& sender:app.preview_senders)if(sender.joinable())sender.join();
  preview_stats(&app);
  if(app.preview_tee_pad)gst_object_unref(app.preview_tee_pad);
  if(app.pipeline)gst_object_unref(app.pipeline);
  if(app.loop)g_main_loop_unref(app.loop);
  std::cerr<<"City publisher summary: {\"enqueued\":"<<app.enqueued
      <<",\"published\":"<<app.published<<",\"peakQueue\":"<<app.peak_queue
      <<",\"backpressureWaits\":"<<app.backpressure_waits<<",\"failed\":"<<(app.failed?"true":"false")<<"}\n";
  if(app.options.tracker_mode=="mv3dt-demo")
    std::cerr<<"Demo SDK ID ambiguity summary: affectedFrames="<<app.ambiguous_demo_frames
        <<" omittedObjects="<<app.omitted_demo_objects<<'\n';
  curl_global_cleanup();return app.failed?1:0;
}
