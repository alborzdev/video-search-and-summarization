// SPDX-License-Identifier: Apache-2.0
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>
int main(int argc,char** argv) {
  gst_init(&argc,&argv);
  city::DetectorCadence cadence;
  assert(cadence.select(0,100,2));assert(!cadence.select(0,200,2));
  assert(cadence.select(1,100,2));assert(cadence.select(0,300,2));
  assert(!cadence.select(1,200,2));assert(cadence.select(0,50,2));
  assert(!cadence.select(2,100,2));
  App app;app.loop=g_main_loop_new(nullptr,FALSE);app.options.sources.resize(2);
  app.options.detector_cadence=2;app.options.tracker_diagnostics=true;
  for(unsigned n=0;n<6;++n) {
    auto* buffer=gst_buffer_new();auto* batch=nvds_create_batch_meta(2);
    // Alternating single-source partial batches must each get a 1/2 schedule.
    auto* frame=nvds_acquire_frame_meta_from_pool(batch);
    frame->source_id=n%2;frame->buf_pts=100+n*100;frame->frame_num=n;
    nvds_add_frame_meta_to_batch(batch,frame);
    auto* meta=gst_buffer_add_nvds_meta(buffer,batch,nullptr,nvds_batch_meta_copy_func,nvds_batch_meta_release_func);
    meta->meta_type=NVDS_BATCH_GST_META;
    GstPadProbeInfo info{};info.type=GST_PAD_PROBE_TYPE_BUFFER;info.data=buffer;
    assert(detector_schedule_probe(nullptr,&info,&app)==GST_PAD_PROBE_OK);
    auto* schedule=city::detector_schedule(frame);assert(schedule);
    assert(schedule->selected==(n<2||n>=4));assert(schedule->batch_size==1);
    assert(!frame->bInferDone);
    frame->bInferDone=schedule->selected;
    assert(detector_completion_probe(nullptr,&info,&app)==GST_PAD_PROBE_OK);
    assert(staged_detector_probe(nullptr,&info,&app)==GST_PAD_PROBE_OK);
    assert(city::staged_frame(frame));assert(schedule->detector_done_ns>=schedule->entered_ns);
    gst_buffer_unref(buffer);
  }
  assert(!app.failed);g_main_loop_unref(app.loop);
  const char* args[]{"city-worker","--source","camera=rtsp://example/camera","--output","/tmp/unused",
    "--decoder-extra-surfaces","4"};
  assert(parse_options(sizeof(args)/sizeof(*args),const_cast<char**>(args)).decoder_extra_surfaces==4);
  for(auto* invalid:{"-1","9","4junk","4294967296"}) {
    args[6]=invalid;bool rejected=false;
    try{parse_options(sizeof(args)/sizeof(*args),const_cast<char**>(args));}catch(...){rejected=true;}
    assert(rejected);
  }
  std::cout<<"Per-source partial batches, rewind, exact schedule and inference completion passed\n";
}
