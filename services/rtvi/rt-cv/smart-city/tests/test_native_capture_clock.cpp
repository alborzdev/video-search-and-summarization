// SPDX-License-Identifier: Apache-2.0
// CPU-only H264 parsing, exact AU/decoded/mux identity and SDK frame stamping.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>

namespace {
constexpr uint64_t wall=1793008203937180464ULL;
std::string metadata(uint64_t timestamp=wall,uint64_t frame=10,uint64_t sim=123,
    const std::string& iso="2026-10-26T09:50:03.937181+00:00") {
  return "{\"publish_sim_time_ns\":"+std::to_string(sim)+",\"timestamp_iso8601\":\""+iso+"\",\"timestamp\":"+
      std::to_string(timestamp)+",\"frame_num\":"+std::to_string(frame)+",\"timestamp_basis\":\"wall-capture\"}";
}
std::vector<uint8_t> sei(std::string json=metadata(),bool uuid=true) {
  std::vector<uint8_t> payload(city::kNativeCaptureUuid.begin(),city::kNativeCaptureUuid.end());
  if(!uuid)payload[0]^=1;
  payload.insert(payload.end(),json.begin(),json.end());
  std::vector<uint8_t> rbsp{5};size_t size=payload.size();
  while(size>=255){rbsp.push_back(255);size-=255;}rbsp.push_back(uint8_t(size));
  rbsp.insert(rbsp.end(),payload.begin(),payload.end());rbsp.push_back(0x80);
  std::vector<uint8_t> nal{6};unsigned zeros=0;
  for(auto byte:rbsp){if(zeros>=2&&byte<=3){nal.push_back(3);zeros=0;}nal.push_back(byte);zeros=byte==0?zeros+1:0;}
  return nal;
}
std::vector<uint8_t> au(std::vector<std::vector<uint8_t>> nals,bool annex=false) {
  std::vector<uint8_t> bytes;
  for(auto& nal:nals){if(annex)bytes.insert(bytes.end(),{0,0,0,1});else for(int i=3;i>=0;--i)bytes.push_back(uint8_t(nal.size()>>(8*i)));
    bytes.insert(bytes.end(),nal.begin(),nal.end());}return bytes;
}
template<class F> void refused(F f) {bool failed=false;try{f();}catch(const std::exception&){failed=true;}assert(failed);}
template<class F> void refused_with(F f,const std::string& expected) {
  bool failed=false;try{f();}catch(const std::exception& e){failed=true;assert(std::string(e.what()).find(expected)!=std::string::npos);}assert(failed);
}
city::NativeAuSample parse(const std::vector<uint8_t>& bytes,bool annex=false) {return city::native_capture_au(bytes.data(),bytes.size(),annex);}
void qualify(city::NativeCaptureClock& clock,uint64_t pts=42) {
  clock.record(pts,{wall,10,123},wall+1000000,false);clock.decoded(pts);clock.before_mux(pts);
}
}
int main(int argc,char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-native-capture-cpu-registry.bin",TRUE);gst_init(&argc,&argv);
  unsigned controls=0;
  {
    for(bool annex:{false,true}) {
      const auto result=parse(au({sei(),{0x65,1,2,3}},annex),annex);
      assert(result.has_picture&&result.capture&&result.capture->capture_ns==wall&&result.capture->frame_counter==10);
    }
    ++controls;
    assert(!parse(au({{0x67,1,2,3},{0x68,1,2}})).has_picture);++controls;
    refused_with([&]{parse(au({sei(),sei(),{0x65,1}}));},"same-fields=true same-nal=false first-frame=10 second-frame=10");
    refused_with([&]{parse(au({sei(),sei(metadata(wall,11,124)),{0x65,1}}));},"same-fields=false same-nal=false first-frame=10 second-frame=11");
    auto combined=sei();combined.pop_back();const auto second=sei();combined.insert(combined.end(),second.begin()+1,second.end());
    refused_with([&]{parse(au({combined,{0x65,1}}));},"same-fields=true same-nal=true");++controls;
    for(bool annex:{false,true}) {
      const auto sample=parse(au({sei(),{9,0x10},sei(metadata(wall+1,11,124)),{9,0x10},
          sei(metadata(wall+2,12,125)),{9,0x10},{0x65,1}},annex),annex);
      assert(sample.has_picture&&sample.capture&&sample.capture->frame_counter==12);
      assert(sample.capture->capture_ns==wall+2&&sample.discarded_prefix_units==2);
      // No explicit next delimiter, repeated clocks, or two pictured units
      // can be mistaken for the measured pictureless-prefix condition.
      refused([&]{parse(au({sei(),{9,0x10},sei(metadata(wall+1,11,124)),{0x65,1}},annex),annex);});
      refused([&]{parse(au({sei(),{9,0x10},sei(),{9,0x10},{0x65,1}},annex),annex);});
      refused([&]{parse(au({sei(),{9,0x10},{0x41,1},sei(metadata(wall+1,11,124)),{9,0x10},{0x65,1}},annex),annex);});
      refused([&]{parse(au({sei(),{9,0x10},sei(metadata(wall+1,11,124)),{9,0x10}},annex),annex);});
    }
    ++controls;
    refused([&]{parse(au({sei(metadata(),false),{0x65,1}}));});++controls;
    refused([&]{parse(au({sei()}));});++controls;
    for(const auto& bad:std::vector<std::vector<uint8_t>>{{0,0},{0,0,0,20,6},{0,0,0,0},{0,0,0,1,0xe5}}) {
      refused([&]{parse(bad);});
    }++controls;
    auto bad=sei();bad.push_back(1);refused([&]{parse(au({bad,{0x65,1}}));});++controls;
    for(const auto& bad_sei:std::vector<std::vector<uint8_t>>{{6,5,255},{6,5,32,1,0x80},{6,0,0,0,3,9,0x80}}) {
      refused([&]{parse(au({bad_sei,{0x65,1}}));});
    }++controls;
    for(const auto& replacement:std::vector<std::pair<std::string,std::string>>{
        {"\"frame_num\":10","\"frame_num\":true"},{"\"frame_num\":10","\"frame_num\":1.5"},
        {"\"frame_num\":10","\"frame_num\":-1"},{"\"wall-capture\"","\"simulation\""},
        {"\"frame_num\":10","\"frame_num\":10,\"frame_num\":10"}}) {
      auto json=metadata();json.replace(json.find(replacement.first),replacement.first.size(),replacement.second);
      refused([&]{parse(au({sei(json),{0x65,1}}));});
    }++controls;
    auto json=metadata();json.insert(json.size()-1,",\"schemaVersion\":\"invented\"");
    refused([&]{parse(au({sei(json),{0x65,1}}));});++controls;
    assert(city::native_capture_fresh(wall,wall+city::kNativeCaptureMaxAgeNs));
    assert(!city::native_capture_fresh(wall,wall+city::kNativeCaptureMaxAgeNs+1));
    assert(!city::native_capture_fresh(wall+city::kNativeCaptureFutureNs+1,wall));++controls;
  }
  {
    city::NativeCaptureClock clock;qualify(clock);
    auto frame=clock.prepare(42,wall+600000000,wall+1000000);
    assert(frame.sample.capture_ns==wall&&frame.sdk_ntp_ns==wall+600000000);
    auto consumed=clock.take(42,wall);assert(consumed.sample.frame_counter==10&&clock.frames.empty());
    refused([&]{clock.record(42,{wall+1,11,124},wall+1000000,false);});assert(clock.failed);++controls;
  }
  {
    for(unsigned mode=0;mode<8;++mode) {
      city::NativeCaptureClock clock;clock.record(42,{wall,10,123},wall,false);
      refused([&]{switch(mode) {
        case 0:clock.decoded(43);break;
        case 1:clock.before_mux(42);break;
        case 2:clock.prepare(42,wall,wall);break;
        case 3:clock.decoded(42);clock.decoded(42);break;
        case 4:clock.decoded(42);clock.before_mux(42);clock.before_mux(42);break;
        case 5:clock.decoded(42);clock.before_mux(42);clock.prepare(42,wall,wall);clock.take(42,wall+1);break;
        case 6:clock.decoded(42);clock.before_mux(42);clock.prepare(42,wall,wall+city::kNativeCaptureMaxAgeNs+1);break;
        case 7:clock.decoded(42);clock.before_mux(42);clock.prepare(42,wall,wall);clock.prepare(42,wall,wall);break;
      }});assert(clock.failed&&clock.frames.empty());
    }++controls;
  }
  {
    for(unsigned mode=0;mode<6;++mode) {
      city::NativeCaptureClock clock;clock.segment(1);clock.record(42,{wall,10,123},wall,false);
      refused([&]{switch(mode) {
        case 0:clock.segment(2);break;
        case 1:clock.record(41,{wall+1,11,124},wall,false);break;
        case 2:clock.record(43,{wall,11,124},wall,false);break;
        case 3:clock.record(43,{wall+1,10,124},wall,false);break;
        case 4:clock.record(43,{wall+1,11,122},wall,false);break;
        case 5:clock.record(43,{wall+1,11,124},wall,true);break;
      }});assert(clock.failed&&clock.epoch==1&&clock.frames.empty());
    }++controls;
    city::NativeCaptureClock clock;
    for(uint64_t i=0;i<city::kNativeClockFrames+10;++i)clock.record(1000+i,{wall+i,1000+i,i},wall+10000,false);
    assert(clock.frames.size()==city::kNativeClockFrames&&clock.order.size()==city::kNativeClockFrames&&clock.evicted==10);++controls;
  }
  {
    App app;app.loop=g_main_loop_new(nullptr,FALSE);app.options.source_native_sei_clock=true;
    Source source;source.id="actual-gst-probe-fixture";app.options.sources={source};SourcePadContext context{&app,0};
    const auto now=utc_ns();auto* seconds=g_date_time_new_from_unix_utc(now/1000000000ULL);
    auto* date=g_date_time_add(seconds,(now%1000000000ULL)/1000);g_date_time_unref(seconds);
    auto* iso=g_date_time_format_iso8601(date);g_date_time_unref(date);
    auto bytes=au({sei(metadata(now-1,0,122,iso)),{9,0x10},
                  sei(metadata(now,1,123,iso)),{9,0x10},{0x65,1,2}},true);g_free(iso);
    auto* buffer=gst_buffer_new_allocate(nullptr,bytes.size(),nullptr);gst_buffer_fill(buffer,0,bytes.data(),bytes.size());GST_BUFFER_PTS(buffer)=42;
    auto* caps=gst_caps_from_string("video/x-h264,stream-format=byte-stream,alignment=au");
    auto* pad=gst_pad_new("native-clock-encoded-fixture",GST_PAD_SRC);gst_pad_set_active(pad,TRUE);assert(gst_pad_set_caps(pad,caps));gst_caps_unref(caps);
    GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    assert(native_au_clock_probe(pad,&info,&context)==GST_PAD_PROBE_OK);
    assert(app.options.sources[0].native_capture_clock.exact(42).sample.capture_ns==now);
    assert(app.options.sources[0].native_capture_clock.exact(42).sample.frame_counter==1);
    assert(native_decoded_clock_probe(nullptr,&info,&context)==GST_PAD_PROBE_OK);
    assert(source_clock_probe(nullptr,&info,&context)==GST_PAD_PROBE_OK);
    assert(!app.failed&&app.options.sources[0].native_capture_clock.exact(42).before_mux);
    // The exact parser-probe evidence cannot qualify the next/nearest image.
    GST_BUFFER_PTS(buffer)=43;
    assert(native_decoded_clock_probe(nullptr,&info,&context)==GST_PAD_PROBE_DROP&&app.failed);
    assert(app.options.sources[0].native_capture_clock.frames.empty());
    gst_pad_set_active(pad,FALSE);gst_object_unref(pad);gst_buffer_unref(buffer);g_main_loop_unref(app.loop);++controls;
  }
  {
    App app;app.loop=g_main_loop_new(nullptr,FALSE);app.options.source_native_sei_clock=true;
    app.options.local_tracker_config="staged-fixture";app.options.tracker_mode="mv3dt-demo";
    app.options.tracker_calibration_revision="fixture";app.options.preview_url="http://fixture/preview";
    Source source;source.id="native-clock-fixture";app.options.sources={source};
    const auto now=utc_ns();auto& clock=app.options.sources[0].native_capture_clock;
    clock.record(42,{now,100,123},now,false);clock.decoded(42);clock.before_mux(42);
    auto* buffer=gst_buffer_new();auto* batch=nvds_create_batch_meta(1);auto* frame=nvds_acquire_frame_meta_from_pool(batch);
    frame->source_id=0;frame->pad_index=0;frame->buf_pts=42;frame->frame_num=12345;frame->ntp_timestamp=now+600000000;frame->bInferDone=true;
    frame->source_frame_width=960;frame->source_frame_height=540;nvds_add_frame_meta_to_batch(batch,frame);
    auto* object=nvds_acquire_obj_meta_from_pool(batch);assert(object);
    object->class_id=0;object->confidence=.9;object->unique_component_id=1;object->object_id=UNTRACKED_OBJECT_ID;
    object->rect_params={};object->rect_params.left=10;object->rect_params.top=20;object->rect_params.width=30;object->rect_params.height=40;
    object->detector_bbox_info.org_bbox_coords={10,20,30,40};nvds_add_obj_meta_to_frame(frame,object,nullptr);
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);assert(meta);meta->meta_type=NVDS_BATCH_GST_META;
    GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    assert(native_pretracker_clock_probe(nullptr,&info,&app)==GST_PAD_PROBE_OK);
    assert(frame->ntp_timestamp==now&&frame->buf_pts==42); // actual NvMOT input is nonzero ntp_timestamp
    assert(city::stamp_staged_detections(batch,frame,11));
    object->object_id=123;object->tracker_confidence=.8;
    assert(city::prepare_staged_second_input(batch,frame));
    assert(city::staged_frame(frame)->key.ntp==now);frame->frame_num=7; // SDK second-stage counter rewrite
    object->object_id=55;
    static float world_foot[]{1,2},image_foot[]{25,60},visibility[]{.8};
    for(auto pair:{std::make_pair(NVDS_OBJ_WORLD_FOOT_LOCATION,world_foot),std::make_pair(NVDS_OBJ_IMAGE_FOOT_LOCATION,image_foot),std::make_pair(NVDS_OBJ_VISIBILITY,visibility)}) {
      auto* user=nvds_acquire_user_meta_from_pool(batch);assert(user);user->base_meta.meta_type=pair.first;user->user_meta_data=pair.second;
      nvds_add_user_meta_to_obj(object,user);
    }
    observation_probe(nullptr,&info,&app);assert(!app.failed&&app.queue.size()==1);
    const auto out=nlohmann::json::parse(app.queue.front());
    assert(out["timestampBasis"]=="source-native-sei"&&out["sourceTimeNs"]==std::to_string(now));
    assert(out["sourceClockEvidence"]["captureTimeNs"]==out["sourceTimeNs"]&&out["sourceClockEvidence"]["auPtsNs"]=="42");
    assert(out["sourceClockEvidence"]["frameCounter"]=="100");
    assert(out["sourceFrameId"]=="12345");
    assert(out["objects"].size()==1&&out["objects"][0]["localTrackId"]=="123");
    assert(out["objects"][0]["globalTrackId"]=="mv3dt-demo:"+app.fusion_epoch+":55");
    assert(out["objects"][0]["associationMethod"]=="mv3dt-demo");
    bool preview_matched=false;
    for(auto* link=frame->frame_user_meta_list;link;link=link->next) {
      auto* user=static_cast<NvDsUserMeta*>(link->data);
      if(user->base_meta.meta_type==preview_meta_type()) {
        preview_matched=static_cast<city::PreviewProvenance*>(user->user_meta_data)->source_time_ns==now;
      }
    }
    assert(preview_matched);
    gst_buffer_unref(buffer);g_main_loop_unref(app.loop);++controls;
  }
  {
    App app;app.loop=g_main_loop_new(nullptr,FALSE);app.options.source_native_sei_clock=true;
    Source source;source.id="missing-must-not-fallback";app.options.sources={source};
    auto* buffer=gst_buffer_new();auto* batch=nvds_create_batch_meta(1);auto* frame=nvds_acquire_frame_meta_from_pool(batch);
    frame->source_id=0;frame->pad_index=0;frame->buf_pts=42;frame->ntp_timestamp=wall;nvds_add_frame_meta_to_batch(batch,frame);
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);meta->meta_type=NVDS_BATCH_GST_META;
    GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    assert(native_pretracker_clock_probe(nullptr,&info,&app)==GST_PAD_PROBE_DROP&&app.failed&&app.queue.empty());
    gst_buffer_unref(buffer);g_main_loop_unref(app.loop);++controls;
  }
  {
    const std::optional<std::array<double,2>> world_foot=std::array<double,2>{1,2},image_foot=std::array<double,2>{25,60};
    const std::optional<double> visibility=.8;
    assert(!city::demo_global_identity("mv3dt-demo",0,true,"source-native-sei",world_foot,image_foot,visibility,"epoch",55));
    assert(city::demo_global_identity("mv3dt-demo",0,true,"source-native-sei",world_foot,image_foot,visibility,"epoch",55,true));
    for(const auto* bad:{"arrival-pts-unsynchronized","recorded-pts","unknown"})
      assert(!city::demo_global_identity("mv3dt-demo",0,true,bad,world_foot,image_foot,visibility,"epoch",55,true));
    assert(!city::demo_global_identity("camera-local",0,true,"source-native-sei",world_foot,image_foot,visibility,"epoch",55,true));
    assert(!city::demo_global_identity("mv3dt-demo",1,true,"source-native-sei",world_foot,image_foot,visibility,"epoch",55,true));
    assert(!city::demo_global_identity("mv3dt-demo",0,false,"source-native-sei",world_foot,image_foot,visibility,"epoch",55,true));
    ++controls;
  }
  {
    city::NativeCaptureClock historical;historical.recorded_replay=true;
    historical.record(42,{wall,10,123},wall+1000000000000ULL,false);
    historical.decoded(42);historical.before_mux(42);
    historical.prepare(42,0,wall+1000000000000ULL);
    assert(historical.take(42,wall).sample.capture_ns==wall);
    refused([&]{historical.record(43,{wall,10,123},wall+1000000000000ULL,false);});
    city::NativeCaptureClock live;
    refused([&]{live.record(42,{wall,10,123},wall+1000000000000ULL,false);});++controls;
  }
  {
    std::vector<std::string> args={"city-worker","--source","camera=rtsp://127.0.0.1/live","--output","/tmp/not-opened","--source-native-sei-clock"};
    std::vector<char*> values;for(auto& arg:args)values.push_back(arg.data());
    assert(parse_options(int(values.size()),values.data()).source_native_sei_clock);
    args.pop_back();values.clear();for(auto& arg:args)values.push_back(arg.data());
    assert(!parse_options(int(values.size()),values.data()).source_native_sei_clock);
    args.push_back("--source-native-sei-clock");args[2]="camera=file:///recorded.mp4";values.clear();for(auto& arg:args)values.push_back(arg.data());
    refused([&]{parse_options(int(values.size()),values.data());});++controls;
  }
  {
    auto options=[](std::vector<std::string> args) {
      std::vector<char*> values;for(auto& arg:args)values.push_back(arg.data());
      return parse_options(int(values.size()),values.data());
    };
    const std::vector<std::string> base={"city-worker","--source","camera=file:///recorded.mkv","--output","/tmp/not-opened","--recorded-native-sei-clock"};
    auto replay=options(base);
    assert(replay.recorded_native_sei_clock&&replay.source_native_sei_clock&&replay.sources[0].native_capture_clock.recorded_replay);
    for(const auto& flag:{"--post-url","--preview-url"}) {
      auto invalid=base;invalid.push_back(flag);invalid.push_back("http://127.0.0.1/forbidden");
      refused([&]{options(invalid);});
    }
    auto invalid=base;invalid[2]="camera=rtsp://127.0.0.1/live";refused([&]{options(invalid);});
    invalid=base;invalid.push_back("--source-native-sei-clock");refused([&]{options(invalid);});++controls;
  }
  size_t actual=0;
  {
    city::NativeCaptureClock startup;
    assert(startup.discard_unproven_startup(10));
    assert(startup.frames.empty()&&startup.parsed==0&&!startup.failed);
    startup.record(42,{wall,10,123},wall,false);
    assert(!startup.discard_unproven_startup(20));
    city::NativeCaptureClock recording;recording.recorded_replay=true;
    assert(!recording.discard_unproven_startup(10));
    city::NativeCaptureClock bounded;
    for(int i=0;i<8;++i)assert(bounded.discard_unproven_startup(10+i));
    assert(!bounded.discard_unproven_startup(19));
    city::NativeCaptureClock expired;assert(expired.discard_unproven_startup(10));
    assert(!expired.discard_unproven_startup(2000000011ULL));
    ++controls;
  }
  if(argc==2)for(const auto& entry:std::filesystem::directory_iterator(argv[1])) {
    if(entry.path().extension()!=".au")continue;
    std::ifstream file(entry.path(),std::ios::binary);std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(file)),{});
    const auto sample=parse(bytes);assert(sample.has_picture&&sample.capture);++actual;
  }
  std::cout<<"Native capture clock "<<controls<<" CPU control groups passed; actual wire AUs accepted="<<actual<<"; no decode/GPU\n";
}
