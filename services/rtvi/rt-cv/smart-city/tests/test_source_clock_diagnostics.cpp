// SPDX-License-Identifier: Apache-2.0
// CPU GstReferenceTimestampMeta + exact source-PTS evidence. No GPU execution.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>

GstBuffer* reference_buffer(uint64_t pts,uint64_t unix_ns,const char* type="timestamp/x-ntp") {
  auto* buffer=gst_buffer_new();GST_BUFFER_PTS(buffer)=pts;
  auto* caps=gst_caps_new_empty_simple(type);
  assert(gst_buffer_add_reference_timestamp_meta(buffer,caps,
      unix_ns+(std::string(type)=="timestamp/x-ntp"?city::kNtpUnixEpochDifferenceNs:0),GST_CLOCK_TIME_NONE));
  gst_caps_unref(caps);return buffer;
}
int main(int argc,char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-source-clock-cpu-registry.bin",TRUE);gst_init(&argc,&argv);
  const uint64_t unix_ns=1700000000000000000ULL;
  {
    auto* buffer=reference_buffer(42,unix_ns);auto sample=city::reference_clock_sample(buffer,unix_ns+20000000);
    assert(sample.meta_count==1&&sample.unix_ns==unix_ns&&sample.state=="reference-present");
    auto* copied=gst_buffer_copy_deep(buffer);assert(city::reference_clock_sample(copied,1).unix_ns==unix_ns);
    auto* caps=gst_caps_new_empty_simple("timestamp/x-unix");
    assert(gst_buffer_add_reference_timestamp_meta(buffer,caps,unix_ns,1));gst_caps_unref(caps);
    sample=city::reference_clock_sample(buffer,1);assert(sample.meta_count==2&&!sample.unix_ns&&sample.state=="multiple-references");
    gst_buffer_unref(buffer);gst_buffer_unref(copied);
  }
  {
    for(const auto* type:{"timestamp/x-unix","timestamp/x-unknown"}) {
      auto* buffer=reference_buffer(42,unix_ns,type);auto sample=city::reference_clock_sample(buffer,1);
      assert(sample.unix_ns.has_value()==(std::string(type)=="timestamp/x-unix"));gst_buffer_unref(buffer);
    }
    auto* buffer=gst_buffer_new();auto sample=city::reference_clock_sample(buffer,1);
    assert(sample.present&&sample.meta_count==0&&!sample.unix_ns&&sample.state=="missing");gst_buffer_unref(buffer);
  }
  {
    city::SourceClockEvidence evidence;auto* buffer=reference_buffer(42,unix_ns);
    const auto sample=city::reference_clock_sample(buffer,1);
    evidence.record(42,city::ClockProbeStage::Decoded,sample);
    evidence.record(42,city::ClockProbeStage::BeforeMux,sample);
    assert(!evidence.take(43)); // no nearest-PTS alias
    auto exact=evidence.take(42);assert(exact&&exact->stages[2].unix_ns==unix_ns&&exact->stages[3].unix_ns==unix_ns);
    assert(!evidence.take(42)); // observations consume evidence once
    evidence.record(44,city::ClockProbeStage::Decoded,sample);
    evidence.record(44,city::ClockProbeStage::Decoded,sample);
    auto duplicate=evidence.take(44);assert(duplicate->stages[2].duplicate_pts&&!duplicate->stages[2].unix_ns);
    for(unsigned i=0;i<city::kSourceClockEvidenceLimit+20;++i)evidence.record(100+i,city::ClockProbeStage::Parsed,sample);
    assert(evidence.frames.size()<=city::kSourceClockEvidenceLimit&&evidence.order.size()<=city::kSourceClockEvidenceLimit&&evidence.counters.evicted>0);
    evidence.segment(100);assert(evidence.frames.empty());
    evidence.record(42,city::ClockProbeStage::Depay,sample);
    evidence.segment(100);assert(evidence.frames.size()==1); // same segment forwarded
    evidence.segment(101);assert(evidence.frames.empty());
    evidence.record(100,city::ClockProbeStage::Decoded,sample);
    evidence.record(99,city::ClockProbeStage::Decoded,sample);assert(!evidence.take(100));
    auto discont=sample;discont.discontinuity=true;
    evidence.record(110,city::ClockProbeStage::Decoded,discont);assert(!evidence.take(99));
    const auto epoch=evidence.counters.retired_epochs;
    evidence.record(110,city::ClockProbeStage::BeforeMux,discont);
    assert(evidence.counters.retired_epochs==epoch&&evidence.take(110)->evidence_epoch==epoch);
    gst_buffer_unref(buffer);
  }
  {
    App app;app.loop=g_main_loop_new(nullptr,FALSE);app.options.source_clock_diagnostics=true;
    Source source;source.id="clock-fixture";app.options.sources={source};
    auto* buffer=reference_buffer(42,unix_ns);GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    SourceClockProbeContext decoded{&app,0,city::ClockProbeStage::Decoded};reference_clock_probe(nullptr,&info,&decoded);
    SourcePadContext before_mux{&app,0};source_clock_probe(nullptr,&info,&before_mux);
    auto* batch=nvds_create_batch_meta(1);auto* frame=nvds_acquire_frame_meta_from_pool(batch);assert(frame);
    frame->source_id=0;frame->buf_pts=42;frame->ntp_timestamp=unix_ns+450000000;frame->source_frame_width=960;frame->source_frame_height=540;
    nvds_add_frame_meta_to_batch(batch,frame);
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);assert(meta);meta->meta_type=NVDS_BATCH_GST_META;
    observation_probe(nullptr,&info,&app);assert(!app.failed&&app.queue.size()==1);
    const auto& out=app.queue.front();
    assert(out.find("\"sourceTimeNs\":\"1700000000450000000\"")!=std::string::npos); // observe only
    assert(out.find("\"timestampBasis\":\"source-rtcp\"")!=std::string::npos);
    assert(out.find("\"sdkMinusReferenceNs\":\"450000000\"")!=std::string::npos);
    assert(out.find("\"exactSourcePtsEvidenceMatched\":true")!=std::string::npos);
    assert(out.find("\"decoded\":{\"state\":\"reference-present\"")!=std::string::npos);
    assert(out.find("\"beforeMux\":{\"state\":\"reference-present\"")!=std::string::npos);
    gst_buffer_unref(buffer);g_main_loop_unref(app.loop);
  }
  {
    std::vector<std::string> args={"city-worker","--source","a=rtsp://127.0.0.1/a","--output","/tmp/not-opened-clock-fixture",
      "--source-clock-diagnostics","--mux-sync-inputs","--mux-max-latency-ns","200000000","--mux-sync-inputs-ntp-ns","50000000"};
    std::vector<char*> pointers;for(auto& arg:args)pointers.push_back(arg.data());
    auto options=parse_options(int(pointers.size()),pointers.data());
    assert(options.source_clock_diagnostics&&options.mux_sync_inputs&&options.mux_max_latency_ns==200000000u&&options.mux_sync_inputs_ntp_ns==50000000u);
    args.back()="1000000001";pointers.clear();for(auto& arg:args)pointers.push_back(arg.data());
    bool rejected=false;try{parse_options(int(pointers.size()),pointers.data());}catch(const std::runtime_error&){rejected=true;}
    assert(rejected);
    auto* object=GST_ELEMENT(g_object_new(GST_TYPE_PIPELINE,nullptr));
    rejected=false;try{city::configure_mux_clock_settings(object,true,1,1);}catch(const std::runtime_error&){rejected=true;}
    assert(rejected);gst_object_unref(object);
  }
  std::cout<<"Source reference-clock metadata, bounded exact-PTS correlation, observe-only serialization and mux CLI contract passed (no GPU)\n";
}
