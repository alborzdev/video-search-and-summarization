// SPDX-License-Identifier: Apache-2.0
// Actual observation callback and metadata API, with no GPU/model execution.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>

int main(int argc,char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-native-mv3dt-cpu-registry.bin",TRUE);gst_init(&argc,&argv);
  for(unsigned cls=0;cls<6;++cls)for(bool observed:{true,false}) {
    App app;app.loop=g_main_loop_new(nullptr,FALSE);
    app.options.tracking_architecture="mv3dt-native-v1";app.options.tracker_mode="mv3dt-demo";
    app.options.tracker_diagnostics=true;
    app.options.tracker_calibration_revision="calibration";
    Source source;source.id="camera";app.options.sources={source};
    auto* buffer=gst_buffer_new();auto* batch=nvds_create_batch_meta(1);
    auto* frame=nvds_acquire_frame_meta_from_pool(batch);
    frame->source_id=0;frame->pad_index=0;frame->frame_num=12345;frame->buf_pts=1000000000;
    frame->ntp_timestamp=1700000001000000000ULL;frame->bInferDone=true;
    frame->source_frame_width=1920;frame->source_frame_height=1080;
    nvds_add_frame_meta_to_batch(batch,frame);
    auto make_object=[&](){
      auto* obj=nvds_acquire_obj_meta_from_pool(batch);obj->class_id=cls;obj->unique_component_id=1;
      obj->confidence=.9;obj->rect_params.left=10;obj->rect_params.top=20;
      obj->rect_params.width=30;obj->rect_params.height=40;
      nvds_add_obj_meta_to_frame(frame,obj,nullptr);return obj;
    };
    auto* object=observed?make_object():nullptr;
    auto* removed=observed?make_object():nullptr;
    assert(city::stamp_staged_detections(batch,frame,1,true));
    if(removed)nvds_remove_obj_meta_from_frame(frame,removed); // SDK may omit tentative inputs.
    if(!observed)object=make_object(); // SDK peer/shadow output has no input stamp
    object->object_id=9223372036854775809ULL;
    frame->frame_num=7; // SDK batch counter must not replace the original source ID
    static float world[]{1.25f,2.5f},image[]{25,60},visibility[]{.8f};
    for(auto pair:{std::make_pair(NVDS_OBJ_WORLD_FOOT_LOCATION,world),
        std::make_pair(NVDS_OBJ_IMAGE_FOOT_LOCATION,image),std::make_pair(NVDS_OBJ_VISIBILITY,visibility)}) {
      auto* user=nvds_acquire_user_meta_from_pool(batch);user->base_meta.meta_type=pair.first;
      // The removed synthetic detector returned stamped metadata to this pool.
      // These borrowed static values do not own a StagedDetection allocation.
      user->base_meta.copy_func=nullptr;user->base_meta.release_func=nullptr;
      user->user_meta_data=pair.second;nvds_add_user_meta_to_obj(object,user);
    }
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);
    meta->meta_type=NVDS_BATCH_GST_META;
    GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    observation_probe(nullptr,&info,&app);
    assert(!app.failed&&app.queue.size()==1);
    const auto& output=app.queue.front();
    assert(output.find("\"trackingArchitecture\":\"mv3dt-native-v1\"")!=std::string::npos);
    assert(output.find("\"sourceFrameId\":\"12345\"")!=std::string::npos);
    assert(output.find("\"localTrackId\":\"9223372036854775809\"")!=std::string::npos);
    assert(output.find("localTrackingMethod")==std::string::npos);
    assert(output.find(observed?"\"observedThisFrame\":true":"\"observedThisFrame\":false")!=std::string::npos);
    assert(output.find("\"detectorTrackerAudit\":{")!=std::string::npos);
    assert(output.find(observed?"\"inputDetectionCount\":2":"\"inputDetectionCount\":0")!=std::string::npos);
    assert(output.find("\"inputSnapshotComplete\":true")!=std::string::npos);
    assert(output.find("\"rawSdkOutputCount\":1")!=std::string::npos);
    assert(output.find(observed?"\"currentDetectorStamp\":true":"\"currentDetectorStamp\":false")!=std::string::npos);
    // A positive SDK confidence without a current stamp must not become a
    // detector observation in the diagnostic or production object list.
    assert(output.find("\"sdkDetectorConfidencePresent\":true")!=std::string::npos);
    assert(output.find(observed?"\"detectorObservedThisFrame\":true":"\"detectorObservedThisFrame\":false")!=std::string::npos);
    assert((output.find("\"globalTrackId\":null")==std::string::npos)==observed);
    gst_buffer_unref(buffer);g_main_loop_unref(app.loop);
  }
  const char* arguments[]{"city-worker","--source","camera=rtsp://example/camera","--output","/tmp/unused",
    "--tracker-mode","mv3dt-demo","--tracker-config","/tmp/unused.yml","--tracker-calibration-revision","cal",
    "--tracking-architecture","mv3dt-native-v1","--local-tracker-config","/tmp/local.yml"};
  bool rejected=false;
  try{parse_options(sizeof(arguments)/sizeof(*arguments),const_cast<char**>(arguments));}
  catch(const std::runtime_error&){rejected=true;}
  assert(rejected);
  {
    std::vector<std::string> values{"city-worker","--source","a=file:///a.mkv","--source","b=file:///b.mkv",
      "--output","/tmp/unused","--recorded-native-sei-clock","--tracker-mode","mv3dt-demo",
      "--tracker-config","/tmp/unused.yml","--tracker-calibration-revision","cal",
      "--tracking-architecture","mv3dt-native-v1","--native-tracker-sub-batches",
      "--replay-second-source-delay-ms","35"};
    auto parse=[&](){std::vector<char*> args;for(auto& value:values)args.push_back(value.data());
      return parse_options(args.size(),args.data());};
    auto trial=parse();assert(trial.native_tracker_sub_batches&&trial.replay_second_source_delay_ms==35);
    assert(trial.model.find(";color=source-rgba-v1")!=std::string::npos);
    values.back()="101";rejected=false;
    try{parse();}catch(const std::runtime_error&){rejected=true;}assert(rejected);
    values.back()="35";values.push_back("--unpaced");rejected=false;
    try{parse();}catch(const std::runtime_error&){rejected=true;}assert(rejected);
  }
  {
    std::vector<std::string> values{"city-worker","--source","a=rtsp://example/a","--output","/tmp/unused",
      "--tracker-mode","mv3dt-demo","--tracker-config","/tmp/unused.yml","--tracker-calibration-revision","cal",
      "--tracking-architecture","mv3dt-native-v1","--native-tracker-sub-batches"};
    std::vector<char*> args;for(auto& value:values)args.push_back(value.data());
    rejected=false;try{parse_options(args.size(),args.data());}catch(const std::runtime_error&){rejected=true;}
    assert(rejected); // Experimental scheduling cannot leak into the live identity pipeline.
  }
  // A car/truck flip must share one SDK input class without rewriting raw
  // detector evidence or attaching it to an SDK-created peer/prediction.
  auto* batch=nvds_create_batch_meta(1);
  auto* frame=nvds_acquire_frame_meta_from_pool(batch);
  frame->source_id=0;frame->pad_index=0;frame->frame_num=4;
  frame->buf_pts=100;frame->ntp_timestamp=200;frame->bInferDone=true;
  nvds_add_frame_meta_to_batch(batch,frame);
  std::vector<NvDsObjectMeta*> objects;
  for(int cls=0;cls<7;++cls) {
    auto* object=nvds_acquire_obj_meta_from_pool(batch);
    object->class_id=cls;object->unique_component_id=1;object->confidence=.9;
    nvds_add_obj_meta_to_frame(frame,object,nullptr);objects.push_back(object);
  }
  assert(city::stamp_staged_detections(batch,frame,91,true,true));
  for(int cls=0;cls<7;++cls) {
    assert(objects[cls]->class_id==(cls==5?2:cls));
    assert(city::staged_detection(objects[cls])->raw_class==cls);
    assert(city::staged_detection_current(city::staged_detection(objects[cls]),city::staged_frame(frame),frame,objects[cls]));
  }
  auto* peer=nvds_acquire_obj_meta_from_pool(batch);peer->class_id=2;peer->confidence=.9;
  nvds_add_obj_meta_to_frame(frame,peer,nullptr);
  assert(city::restore_native_detector_classes(frame));
  assert(peer->class_id==2&&!city::staged_detection(peer));
  for(int cls=0;cls<7;++cls) {
    assert(objects[cls]->class_id==cls);
    assert(city::staged_detection_current(city::staged_detection(objects[cls]),city::staged_frame(frame),frame,objects[cls]));
  }
  // A changed class or stale clock cannot borrow a raw class restoration.
  objects[5]->class_id=0;assert(city::restore_native_detector_classes(frame));assert(objects[5]->class_id==0);
  frame->buf_pts=101;assert(!city::restore_native_detector_classes(frame));
  nvds_destroy_batch_meta(batch);
  std::cout<<"Single native MV3DT: six classes, exact observations, source frame, uint64 ID and no local stage passed\n";
}
