// SPDX-License-Identifier: Apache-2.0
// Real observation serialization with synthetic CPU SDK metadata, no GPU.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>

std::string diagnostic_observation(bool enabled,const std::string& mode) {
  App app;app.loop=g_main_loop_new(nullptr,FALSE);app.options.width=960;app.options.height=540;
  app.options.tracker_diagnostics=enabled;app.options.tracker_mode=mode;
  app.options.tracker_calibration_revision="fixture-calibration";
  Source source;source.id="fixture-source";app.options.sources={source};
  auto* buffer=gst_buffer_new();auto* batch=nvds_create_batch_meta(1);assert(batch);
  auto* frame=nvds_acquire_frame_meta_from_pool(batch);assert(frame);
  frame->source_id=0;frame->frame_num=7;frame->buf_pts=1000000000ULL;
  frame->ntp_timestamp=1700000001000000000ULL;
  frame->source_frame_width=1920;frame->source_frame_height=1080;
  static float world[]{1.25f,2.5f},image[]{15.f,25.f},visibility[]{.8f};
  for(unsigned i=0;i<3;++i) {
    auto* object=nvds_acquire_obj_meta_from_pool(batch);assert(object);
    object->object_id=i<2?9ULL:9007199254740993ULL;object->class_id=i==0?0:(i==1?2:4);
    object->confidence=.9;object->tracker_confidence=.8;
    object->detector_bbox_info.org_bbox_coords={10,20,30,40};
    object->tracker_bbox_info.org_bbox_coords={11,21,31,41};
    object->rect_params.left=12;object->rect_params.top=22;
    object->rect_params.width=32;object->rect_params.height=42;
    for(const auto& pair:std::array<std::pair<NvDsMetaType,float*>,3>{{
        {NVDS_OBJ_WORLD_FOOT_LOCATION,world},{NVDS_OBJ_IMAGE_FOOT_LOCATION,image},{NVDS_OBJ_VISIBILITY,visibility}}}) {
      auto* user=nvds_acquire_user_meta_from_pool(batch);assert(user);
      user->base_meta.meta_type=pair.first;user->user_meta_data=pair.second;
      nvds_add_user_meta_to_obj(object,user);
    }
    nvds_add_obj_meta_to_frame(frame,object,nullptr);
  }
  nvds_add_frame_meta_to_batch(batch,frame);
  auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);
  assert(meta);meta->meta_type=NVDS_BATCH_GST_META;
  GstPadProbeInfo probe{};probe.type=GST_PAD_PROBE_TYPE_BUFFER;probe.data=buffer;
  observation_probe(nullptr,&probe,&app);assert(app.queue.size()==1&&!app.failed);
  const auto result=app.queue.front();gst_buffer_unref(buffer);g_main_loop_unref(app.loop);return result;
}
int main(int argc,char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-tracker-diagnostics-cpu-registry.bin",TRUE);gst_init(&argc,&argv);
  std::cout<<diagnostic_observation(false,"mv3dt-demo")<<'\n';
  std::cout<<diagnostic_observation(true,"mv3dt-demo")<<'\n';
  std::cout<<diagnostic_observation(false,"mv3dt-diagnostic")<<'\n';
  city::TrackerObjectDiagnostic invalid;invalid.sdk_target_id=18446744073709551615ULL;
  invalid.detector_observed=false;invalid.detector_box=city::diagnostic_box(-1,2,3,4,2,2);
  invalid.rect_box=city::diagnostic_box(1,2,-3,4,2,2);assert(!invalid.rect_box);
  invalid.world_foot=std::array<double,2>{NAN,INFINITY};invalid.visibility=NAN;
  std::vector<city::TrackerObjectDiagnostic> oversized(city::kTrackerDiagnosticObjectLimit+1,invalid);
  city::write_tracker_frame_diagnostics(std::cout,1,0,3,960,540,960,540,oversized.size(),oversized);std::cout<<'\n';
}
