// SPDX-License-Identifier: Apache-2.0
// Exercise the production observation callback with synthetic CPU NvDs metadata.
// No source, inference element, GPU surface or CUDA context is created.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>

GstBuffer* two_frame_batch(uint64_t generation) {
  auto* buffer=gst_buffer_new();auto* batch=nvds_create_batch_meta(2);assert(batch);
  for(unsigned i=0;i<2;i++) {
    auto* frame=nvds_acquire_frame_meta_from_pool(batch);assert(frame);
    frame->source_id=i;frame->frame_num=generation;frame->buf_pts=generation*100000000ULL+i;
    frame->ntp_timestamp=1700000000000000000ULL+frame->buf_pts;
    frame->source_frame_width=1920;frame->source_frame_height=1080;
    nvds_add_frame_meta_to_batch(batch,frame);
  }
  auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);
  assert(meta);meta->meta_type=NVDS_BATCH_GST_META;return buffer;
}
void check_budget(unsigned limit,unsigned expected,bool stopping=false) {
  App app;app.loop=g_main_loop_new(nullptr,FALSE);app.options.frames=limit;app.stopping=stopping;
  Source first;first.id="north";Source second;second.id="south";
  app.options.sources={first,second};
  for(uint64_t generation=0;generation<3;generation++) {
    auto* buffer=two_frame_batch(generation);GstPadProbeInfo probe{};
    probe.type=GST_PAD_PROBE_TYPE_BUFFER;probe.data=buffer;
    observation_probe(nullptr,&probe,&app);gst_buffer_unref(buffer);
  }
  assert(app.enqueued==expected&&app.queue.size()==expected);
  assert(app.options.sources[0].sequence+app.options.sources[1].sequence==expected);
  assert(!app.failed);g_main_loop_unref(app.loop);
}
void check_late_submission() {
  for(bool stopping:{false,true})for(bool realtime:{false,true}) {
    App app;app.options.realtime=realtime;app.stopping=stopping;app.failed=!stopping;
    Source source;source.id="north";app.options.sources={source};
    submit(&app,"late-observation");
    assert(app.enqueued==0&&app.queue.empty());
  }
}
int main(int argc,char** argv) {
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-frame-budget-cpu-registry.bin",TRUE);gst_init(&argc,&argv);
  check_budget(1,1);check_budget(3,3);check_budget(0,6);check_budget(0,0,true);
  check_late_submission();
  std::cout<<"Production observation callback enforces limits1/3 across two-frame batches, unlimited live mode and explicit stopping\n";
}
