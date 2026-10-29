// SPDX-License-Identifier: Apache-2.0
// CPU metadata/probe/serialization contract. No GPU tracker is executed.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>

struct Fixture {
  GstBuffer* buffer=gst_buffer_new();
  NvDsBatchMeta* batch=nvds_create_batch_meta(1);
  NvDsFrameMeta* frame=nvds_acquire_frame_meta_from_pool(batch);
  App app;
  Fixture() {
    app.loop=g_main_loop_new(nullptr,FALSE);app.options.width=960;app.options.height=540;
    app.options.tracker_mode="mv3dt-demo";app.options.local_tracker_config="explicit-fixture-only";
    app.options.tracker_calibration_revision="fixture-calibration";
    Source source;source.id="fixture-source";app.options.sources={source};
    frame->source_id=0;frame->pad_index=0;frame->frame_num=12345;frame->buf_pts=1000000000;
    frame->ntp_timestamp=1700000001000000000ULL;frame->bInferDone=true;
    frame->source_frame_width=960;frame->source_frame_height=540;
    nvds_add_frame_meta_to_batch(batch,frame);
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);
    assert(meta);meta->meta_type=NVDS_BATCH_GST_META;
  }
  ~Fixture(){gst_buffer_unref(buffer);g_main_loop_unref(app.loop);}
  NvDsObjectMeta* object(uint64_t id=UNTRACKED_OBJECT_ID,unsigned class_id=0) {
    auto* obj=nvds_acquire_obj_meta_from_pool(batch);assert(obj);obj->object_id=id;
    obj->class_id=class_id;obj->confidence=.9;obj->unique_component_id=1;obj->tracker_confidence=.8;
    obj->rect_params.left=10;obj->rect_params.top=20;obj->rect_params.width=30;obj->rect_params.height=40;
    obj->detector_bbox_info.org_bbox_coords={10,20,30,40};nvds_add_obj_meta_to_frame(frame,obj,nullptr);return obj;
  }
  std::string publish() {
    GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    observation_probe(nullptr,&info,&app);assert(!app.failed&&app.queue.size()==1);return app.queue.front();
  }
};
void add_float_meta(NvDsBatchMeta* batch,NvDsObjectMeta* object,NvDsMetaType type,float* value) {
  auto* user=nvds_acquire_user_meta_from_pool(batch);assert(user);
  user->base_meta.meta_type=type;user->user_meta_data=value;nvds_add_user_meta_to_obj(object,user);
}
void add_batch_meta(NvDsBatchMeta* batch,NvDsMetaType type) {
  auto* user=nvds_acquire_user_meta_from_pool(batch);assert(user);user->base_meta.meta_type=type;
  nvds_add_user_meta_to_batch(batch,user);
}
size_t list_size(GList* list){return g_list_length(list);}
int main(int argc,char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-staged-tracking-cpu-registry.bin",TRUE);gst_init(&argc,&argv);
  {
    Fixture f;auto* obj=f.object();assert(city::stamp_staged_detections(f.batch,f.frame,11));
    const uint64_t local_id=(1ULL<<63)+19;obj->object_id=local_id;obj->rect_params.left=12;
    auto* shadow=f.object(123);shadow->confidence=-1;
    static float first_world[]{90,90};add_float_meta(f.batch,obj,NVDS_OBJ_WORLD_FOOT_LOCATION,first_world);
    for(auto type:{NVDS_TRACKER_PAST_FRAME_META,NVDS_TRACKER_BATCH_REID_META,
        NVDS_TRACKER_TERMINATED_LIST_META,NVDS_TRACKER_SHADOW_LIST_META,NVDSINFER_TENSOR_OUTPUT_META})add_batch_meta(f.batch,type);
    assert(city::prepare_staged_second_input(f.batch,f.frame));city::remove_first_tracker_batch_meta(f.batch);
    assert(list_size(f.batch->batch_user_meta_list)==1);
    assert(static_cast<NvDsUserMeta*>(f.batch->batch_user_meta_list->data)->base_meta.meta_type==NVDSINFER_TENSOR_OUTPUT_META);
    auto* snapshot=city::staged_frame(f.frame);assert(snapshot->local.size()==2);
    const auto local=std::find_if(snapshot->local.begin(),snapshot->local.end(),[&](const auto& item){return item.local_id==local_id;});
    assert(local!=snapshot->local.end()&&local->rect.left==12&&local->observed);
    assert(std::count_if(snapshot->local.begin(),snapshot->local.end(),[](const auto& item){return !item.observed;})==1);
    assert(list_size(f.frame->obj_meta_list)==1);
    assert(obj->rect_params.left==10&&obj->object_id==UNTRACKED_OBJECT_ID&&obj->tracker_confidence==-1);
    assert(list_size(obj->obj_user_meta_list)==1); // only the application stamp, no first3D
    // Source-proven associatedObjectIn reuses this exact metadata. Simulate
    // native correction and SDK frame counter replacement; no GPU claim.
    obj->object_id=88;f.frame->frame_num=7;
    static float world[]{1.25f,2.5f},image[]{25,60},visibility[]{.8f};
    add_float_meta(f.batch,obj,NVDS_OBJ_WORLD_FOOT_LOCATION,world);
    add_float_meta(f.batch,obj,NVDS_OBJ_IMAGE_FOOT_LOCATION,image);
    add_float_meta(f.batch,obj,NVDS_OBJ_VISIBILITY,visibility);
    city::DemoTrackIdCounts counts;counts.observe(88);
    assert(city::staged_map_object(f.frame,*local,counts)==obj);
    auto output=f.publish();
    assert(output.find("\"sourceFrameId\":\"12345\"")!=std::string::npos);
    assert(output.find("\"localTrackId\":\"9223372036854775827\"")!=std::string::npos);
    assert(output.find("\"targetId\":\"88\"")!=std::string::npos);
    assert(output.find("\"localTrackingMethod\":\"nvidia-nvdcf-first-stage-9.2\"")!=std::string::npos);
    assert(output.find("\"bboxPx\":[12,20,30,40]")!=std::string::npos);
    std::cout<<output<<'\n';
  }
  {
    Fixture f;auto* obj=f.object();assert(city::stamp_staged_detections(f.batch,f.frame,12));
    obj->object_id=23;assert(city::prepare_staged_second_input(f.batch,f.frame));
    // Missing associatedObjectIn / newly predicted MV3DT object cannot borrow
    // an identity, even with the same box and a plausible SDK global ID.
    nvds_remove_obj_meta_from_frame(f.frame,obj);f.object(88);
    city::DemoTrackIdCounts counts;counts.observe(88);
    assert(!city::staged_map_object(f.frame,city::staged_frame(f.frame)->local[0],counts));
    auto output=f.publish();assert(output.find("\"localTrackId\":\"23\"")!=std::string::npos);
    assert(output.find("\"globalTrackId\":null")!=std::string::npos&&output.find("\"native3D\"")==std::string::npos);
  }
  {
    Fixture f;auto* obj=f.object();assert(city::stamp_staged_detections(f.batch,f.frame,13));
    obj->object_id=23;assert(city::prepare_staged_second_input(f.batch,f.frame));obj->object_id=88;
    auto* other=f.object(88);(void)other;city::DemoTrackIdCounts counts;counts.observe(88);counts.observe(88);
    assert(!city::staged_map_object(f.frame,city::staged_frame(f.frame)->local[0],counts));
    auto output=f.publish();assert(output.find("\"localTrackId\":\"23\"")!=std::string::npos);
  }
  {
    Fixture f;auto* obj=f.object();assert(city::stamp_staged_detections(f.batch,f.frame,14));obj->object_id=23;
    // Stamp from another frame must not reclassify a prediction as observed.
    city::staged_detection(obj)->key.token=13;
    assert(city::prepare_staged_second_input(f.batch,f.frame));
    assert(!city::staged_frame(f.frame)->local[0].observed&&f.frame->obj_meta_list==nullptr);
    assert(!city::prepare_staged_second_input(f.batch,f.frame));
  }
  {
    Fixture f;auto* obj=f.object();assert(city::stamp_staged_detections(f.batch,f.frame,15));obj->object_id=23;
    assert(city::prepare_staged_second_input(f.batch,f.frame));obj->object_id=88;
    city::DemoTrackIdCounts counts;counts.observe(88);
    ++f.frame->buf_pts;assert(!city::staged_map_object(f.frame,city::staged_frame(f.frame)->local[0],counts));
  }
  {
    Fixture f;auto* obj=f.object();assert(city::stamp_staged_detections(f.batch,f.frame,16));obj->object_id=23;
    assert(city::prepare_staged_second_input(f.batch,f.frame));obj->object_id=88;
    city::DemoTrackIdCounts counts;counts.observe(88);
    obj->class_id=2;assert(!city::staged_map_object(f.frame,city::staged_frame(f.frame)->local[0],counts));
    obj->class_id=0;++obj->unique_component_id;
    assert(!city::staged_map_object(f.frame,city::staged_frame(f.frame)->local[0],counts));
  }
  {
    Fixture f;auto* obj=f.object();assert(city::stamp_staged_detections(f.batch,f.frame,17));obj->object_id=23;
    assert(city::prepare_staged_second_input(f.batch,f.frame));
    auto* copy=nvds_acquire_obj_meta_from_pool(f.batch);assert(copy);nvds_add_obj_meta_to_frame(f.frame,copy,nullptr);
    nvds_copy_obj_meta(obj,copy);
    auto* original=city::staged_detection(obj);auto* cloned=city::staged_detection(copy);
    assert(original&&cloned&&original!=cloned&&cloned->local_id==23);
    original->local_id=24;assert(cloned->local_id==23);
    auto* copy_frame=nvds_acquire_frame_meta_from_pool(f.batch);assert(copy_frame);
    nvds_add_frame_meta_to_batch(f.batch,copy_frame);nvds_copy_frame_meta(f.frame,copy_frame);
    auto* first=city::staged_frame(f.frame);auto* second=city::staged_frame(copy_frame);
    assert(first&&second&&first!=second&&second->local.size()==1&&second->local[0].local_id==23);
    first->local[0].local_id=25;assert(second->local[0].local_id==23);
  }
  {
    Fixture f;f.frame->bInferDone=false;auto* obj=f.object();
    assert(city::stamp_staged_detections(f.batch,f.frame,18));assert(!city::staged_detection(obj));
    obj->object_id=23;assert(city::prepare_staged_second_input(f.batch,f.frame));
    assert(!city::staged_frame(f.frame)->local[0].observed&&f.frame->obj_meta_list==nullptr);
  }
  {
    const std::string path="/tmp/vss-city-staged-local-config-fixture.yml";
    const std::string valid="BaseConfig:\n  checkClassMatch: 1\nStateEstimator:\n  stateEstimatorType: 1\nVisualTracker:\n  visualTrackerType: 2\nReID:\n  reidType: 0\n";
    {std::ofstream out(path);out<<valid;}city::validate_staged_local_config(path);
    for(const auto& invalid:{std::string("stateEstimatorType: 3\n"),std::string("enableIDCorrection: 1\n"),
        std::string("enableLatePeerReAssoc: 1\n"),std::string("useBatchNumForFrameId: 1\n"),std::string("reidType: 2\n")}) {
      {std::ofstream out(path);out<<valid<<invalid;}
      bool rejected=false;try{city::validate_staged_local_config(path);}catch(const std::runtime_error&){rejected=true;}
      assert(rejected);
    }
    std::filesystem::remove(path);
  }
  std::cout<<"Staged tracking CPU contract passed (GPU trackers not executed)\n";
}
