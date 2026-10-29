// SPDX-License-Identifier: Apache-2.0
// CPU-only: real serialized Gst events/probes plus bounded request/ack handling.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>
struct Hop {GstPad* sink;GstPad* source;bool drop=false;unsigned reset=0;};
struct ClockBatch {
  GstBuffer* buffer=gst_buffer_new();NvDsBatchMeta* batch=nvds_create_batch_meta(2);GstPadProbeInfo info{};
  ClockBatch(App& app,uint64_t pts,const std::array<uint64_t,2>& captures,bool prepared=false) {
    for(unsigned i=0;i<2;++i) {
      auto* frame=nvds_acquire_frame_meta_from_pool(batch);frame->source_id=i;frame->pad_index=i;
      frame->source_frame_width=960;frame->source_frame_height=540;frame->buf_pts=pts;frame->ntp_timestamp=captures[i];
      nvds_add_frame_meta_to_batch(batch,frame);
      auto& clock=app.options.sources[i].native_capture_clock;
      // The AU was fresh at arrival, then can age in a blocked reset queue.
      clock.record(pts,{captures[i],pts,pts},captures[i],false);clock.decoded(pts);clock.before_mux(pts);
      if(prepared)clock.prepare(pts,captures[i],captures[i]);
    }
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);
    assert(meta);meta->meta_type=NVDS_BATCH_GST_META;info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
  }
  ~ClockBatch(){gst_buffer_unref(buffer);}
};
gboolean forward_event(GstPad* pad,GstObject*,GstEvent* event) {
  auto* hop=static_cast<Hop*>(gst_pad_get_element_private(pad));
  if(static_cast<GstNvEventType>(GST_EVENT_TYPE(event))==GST_NVEVENT_STREAM_RESET) {
    assert(GST_EVENT_IS_SERIALIZED(event));++hop->reset;
    if(hop->drop){gst_event_unref(event);return TRUE;}
  }
  if(hop->source)return gst_pad_push_event(hop->source,event);
  gst_event_unref(event);return TRUE;
}
int main(int argc,char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-scenario-boundary-cpu-registry.bin",TRUE);gst_init(&argc,&argv);
  App app;Source a,b;a.id="camera-a";b.id="camera-b";a.sequence=991;b.sequence=802;
  app.options.sources={a,b};app.tracker_stages=2;
  auto* input=gst_pad_new("inference-src",GST_PAD_SRC);gst_pad_set_active(input,TRUE);
  Hop first{gst_pad_new("first-sink",GST_PAD_SINK),gst_pad_new("first-src",GST_PAD_SRC)};
  Hop second{gst_pad_new("second-sink",GST_PAD_SINK),gst_pad_new("second-src",GST_PAD_SRC)};
  Hop output{gst_pad_new("output-sink",GST_PAD_SINK),nullptr};
  BoundaryTrackerContext context0{&app,0},context1{&app,1};
  for(auto* hop:{&first,&second,&output}) {
    gst_pad_set_element_private(hop->sink,hop);gst_pad_set_event_function(hop->sink,forward_event);
    gst_pad_set_active(hop->sink,TRUE);if(hop->source)gst_pad_set_active(hop->source,TRUE);
  }
  assert(gst_pad_link(input,first.sink)==GST_PAD_LINK_OK);
  assert(gst_pad_link(first.source,second.sink)==GST_PAD_LINK_OK);
  assert(gst_pad_link(second.source,output.sink)==GST_PAD_LINK_OK);
  gst_pad_add_probe(first.source,GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM,boundary_tracker_event,&context0,nullptr);
  gst_pad_add_probe(second.source,GST_PAD_PROBE_TYPE_EVENT_DOWNSTREAM,boundary_tracker_event,&context1,nullptr);
  assert(dispatch_scenario_reset(&app,input));
  assert(first.reset==2&&second.reset==2&&output.reset==2);
  assert(app.boundary_events[0]==2&&app.boundary_events[1]==2);
  assert(app.options.sources[0].session==a.session&&app.options.sources[1].session==b.session);
  assert(app.options.sources[0].sequence==991&&app.options.sources[1].sequence==802);
  second.drop=true;
  assert(!dispatch_scenario_reset(&app,input)); // never acknowledge one-stage delivery as a pair reset
  assert(app.boundary_events[0]==2&&app.boundary_events[1]==0);
  {
    App drain;drain.loop=g_main_loop_new(nullptr,FALSE);drain.options.source_native_sei_clock=true;
    drain.options.sources={a,b};drain.boundary_drain_deadline_ns=steady_ns()+kBoundaryDrainNs;
    drain.tracking_epoch="reset-epoch";const auto now=utc_ns();
    {
      ClockBatch queued(drain,100,{now-3000000000ULL,now});
      assert(native_pretracker_clock_probe(nullptr,&queued.info,&drain)==GST_PAD_PROBE_DROP);
      assert(!drain.failed&&drain.boundary_stale_mux_batches==1);
      for(auto& source:drain.options.sources)assert(source.native_capture_clock.frames.empty()&&source.native_capture_clock.applied==0);
    }
    {
      const auto fresh=utc_ns();ClockBatch next(drain,101,{fresh,fresh});
      assert(native_pretracker_clock_probe(nullptr,&next.info,&drain)==GST_PAD_PROBE_OK);
      assert(apply_scenario_boundary(input,&next.info,&drain)==GST_PAD_PROBE_OK);
      assert(drain.boundary_drain_deadline_ns&&!drain.failed); // admission is not tracker completion
      assert(observation_probe(nullptr,&next.info,&drain)==GST_PAD_PROBE_OK);
      for(auto& source:drain.options.sources)assert(source.native_capture_clock.frames.empty());
      assert(drain.boundary_drain_deadline_ns); // a single carrier cannot hide lazy SDK initialization
      assert(drain.queue.size()==2); // stale frames never seeded/emitted tracks
    }
    const auto deadline=drain.boundary_drain_deadline_ns.load();
    for(uint64_t pts=102;pts<=103;++pts) {
      std::this_thread::sleep_for(std::chrono::milliseconds(550));
      const auto fresh=utc_ns();ClockBatch next(drain,pts,{fresh,fresh});
      assert(native_pretracker_clock_probe(nullptr,&next.info,&drain)==GST_PAD_PROBE_OK);
      assert(apply_scenario_boundary(input,&next.info,&drain)==GST_PAD_PROBE_OK);
      assert(drain.boundary_drain_deadline_ns==deadline);
      assert(observation_probe(nullptr,&next.info,&drain)==GST_PAD_PROBE_OK);
      assert((drain.boundary_drain_deadline_ns==0)==(pts==103));
    }
    assert(drain.queue.size()==6&&!drain.failed);
    g_main_loop_unref(drain.loop);
  }
  {
    App drain;drain.options.source_native_sei_clock=true;drain.options.sources={a,b};
    drain.boundary_drain_deadline_ns=steady_ns()+kBoundaryDrainNs;drain.tracking_epoch="current-reset";
    note_boundary_output(&drain,0,"old-reset",utc_ns());
    note_boundary_output(&drain,1,"current-reset",utc_ns()-3000000000ULL);
    assert(drain.boundary_fresh_sources.empty()&&drain.boundary_drain_deadline_ns);
  }
  {
    // A carrier already qualified before inference can age during synchronous
    // tracker reset. It is consumed once at the final tracker admission gate.
    App drain;drain.loop=g_main_loop_new(nullptr,FALSE);drain.options.source_native_sei_clock=true;
    drain.options.sources={a,b};drain.boundary_drain_deadline_ns=steady_ns()+kBoundaryDrainNs;
    const auto now=utc_ns();ClockBatch carrier(drain,200,{now-3000000000ULL,now},true);
    assert(apply_scenario_boundary(input,&carrier.info,&drain)==GST_PAD_PROBE_DROP);
    assert(!drain.failed&&drain.boundary_stale_tracker_batches==1&&drain.queue.empty());
    for(auto& source:drain.options.sources)assert(source.native_capture_clock.frames.empty());
    g_main_loop_unref(drain.loop);
  }
  for(unsigned invalid=0;invalid<6;++invalid) {
    App drain;drain.loop=g_main_loop_new(nullptr,FALSE);drain.options.source_native_sei_clock=true;
    drain.options.sources={a,b};drain.boundary_drain_deadline_ns=steady_ns()+kBoundaryDrainNs;
    const auto now=utc_ns();ClockBatch queued(drain,300,{now-3000000000ULL,now});
    auto& other=drain.options.sources[1].native_capture_clock;
    if(invalid==0)other.frames.clear();
    if(invalid==1)other.frames.at(300).applied=true;
    if(invalid==2)other.frames.at(300).decoded=false;
    if(invalid==3)other.frames.at(300).before_mux=false;
    if(invalid==4)other.frames.at(300).sample.capture_ns=now+1000000000ULL;
    if(invalid==5)drain.boundary_drain_deadline_ns=steady_ns()-1;
    assert(native_pretracker_clock_probe(nullptr,&queued.info,&drain)==GST_PAD_PROBE_DROP);
    assert(drain.failed&&drain.boundary_stale_mux_batches==0&&drain.queue.empty());
    g_main_loop_unref(drain.loop);
  }
  {
    App normal;normal.loop=g_main_loop_new(nullptr,FALSE);normal.options.source_native_sei_clock=true;
    normal.options.sources={a,b};const auto now=utc_ns();ClockBatch stale(normal,400,{now-3000000000ULL,now});
    assert(native_pretracker_clock_probe(nullptr,&stale.info,&normal)==GST_PAD_PROBE_DROP);
    assert(normal.failed&&normal.boundary_stale_mux_batches==0); // unchanged strict normal policy
    g_main_loop_unref(normal.loop);
  }
  {
    auto* buffer=gst_buffer_new();auto* batch=nvds_create_batch_meta(1);
    auto* frame=nvds_acquire_frame_meta_from_pool(batch);frame->source_id=0;frame->pad_index=0;
    frame->source_frame_width=960;frame->source_frame_height=540;frame->frame_num=55;frame->buf_pts=42;
    const uint64_t floor=utc_ns();frame->ntp_timestamp=floor-1;
    nvds_add_frame_meta_to_batch(batch,frame);
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);
    assert(meta);meta->meta_type=NVDS_BATCH_GST_META;
    app.options.source_native_sei_clock=true;
    auto& clock=app.options.sources[0].native_capture_clock;
    clock.record(42,{floor-1,10,100},floor,false);clock.decoded(42);clock.before_mux(42);
    clock.prepare(42,floor-1,floor);
    GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    app.pending_boundary=App::ScenarioReset{uuid(),floor};
    const auto epoch_before=app.tracking_epoch;
    const auto prior_resets=first.reset;
    assert(apply_scenario_boundary(input,&info,&app)==GST_PAD_PROBE_DROP);
    assert(app.pending_boundary&&first.reset==prior_resets&&app.tracking_epoch==epoch_before);
    assert(clock.frames.empty()); // discarded exact proof consumed once, never reaches observation
    // Same fence remains active after a successful boundary, including late old batches.
    app.pending_boundary.reset();app.boundary_capture_floor_ns=floor;
    app.options.source_native_sei_clock=false;
    assert(apply_scenario_boundary(input,&info,&app)==GST_PAD_PROBE_DROP);
    assert(first.reset==prior_resets);
    frame->ntp_timestamp=floor;assert(boundary_batch_after_capture(batch,floor));
    // A frame keeps its own epoch even when output is delayed past a later reset.
    stamp_boundary_frame(batch,frame,{"captured-tracking-epoch","captured-fusion-epoch"});
    app.tracking_epoch="new-global-tracking-epoch";app.fusion_epoch="new-global-fusion-epoch";
    assert(observation_probe(nullptr,&info,&app)==GST_PAD_PROBE_OK);
    assert(app.queue.size()==1);
    assert(app.queue.front().find("\"trackingEpoch\":\"captured-tracking-epoch\"")!=std::string::npos);
    assert(app.queue.front().find("\"fusionEpoch\":\"captured-fusion-epoch\"")!=std::string::npos);
    assert(app.queue.front().find("new-global-")==std::string::npos);
    gst_buffer_unref(buffer);
  }
  gchar directory[]="/tmp/city-boundary-test-XXXXXX";assert(g_mkdtemp(directory));
  app.options.analytics_config=std::string(directory)+"/analytics.ini";
  auto write_request=[&](std::string text){std::ofstream out(boundary_path(&app,"scenario-boundary.ini"));out<<text;};
  auto epoch=uuid();
  write_request("[scenario-boundary]\nepoch="+epoch+"\nafter-capture-ns=1700000000000000000\n");
  watch_scenario_boundary(&app);assert(app.pending_boundary&&app.pending_boundary->epoch==epoch);
  const auto request=*app.pending_boundary;app.pending_boundary.reset();watch_scenario_boundary(&app);assert(!app.pending_boundary);
  write_request("[scenario-boundary]\nepoch=../../unsafe\nafter-capture-ns=1\n");
  watch_scenario_boundary(&app);assert(!app.pending_boundary);
  write_request(std::string(4097,'x'));watch_scenario_boundary(&app);assert(!app.pending_boundary);
  write_boundary_ack(&app,request,"applied");
  std::ifstream ack_file(boundary_path(&app,"scenario-boundary-ack.json"));
  std::string ack((std::istreambuf_iterator<char>(ack_file)),{});
  assert(ack.find(epoch)!=std::string::npos&&ack.find("\"trackerStages\":2")!=std::string::npos);
  assert(ack.find("\"sourceClockReset\":false")!=std::string::npos);
  std::filesystem::remove_all(directory);
  for(auto* pad:{input,first.sink,first.source,second.sink,second.source,output.sink}){gst_pad_set_active(pad,FALSE);gst_object_unref(pad);}
  std::cout<<"Scenario boundary CPU: serialized two-stage reset, missing-stage refusal, unchanged sessions/sequences, bounded/idempotent request and ack passed\n";
}
