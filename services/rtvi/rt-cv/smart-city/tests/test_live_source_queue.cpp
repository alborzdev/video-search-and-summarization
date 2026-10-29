// SPDX-License-Identifier: Apache-2.0
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>
#include <chrono>
#include <future>
#include <gst/app/gstappsrc.h>
struct StalledConsumer {
  std::mutex mutex;std::condition_variable changed;bool entered=false,release=false;
  std::vector<uint64_t> seen;
};
void stalled_handoff(GstElement*,GstBuffer* buffer,GstPad*,gpointer data) {
  auto& state=*static_cast<StalledConsumer*>(data);std::unique_lock<std::mutex> lock(state.mutex);
  state.seen.push_back(GST_BUFFER_PTS(buffer));
  if(!state.entered){state.entered=true;state.changed.notify_all();state.changed.wait(lock,[&]{return state.release;});}
  state.changed.notify_all();
}
int main(int argc,char** argv) {
  gst_init(&argc,&argv);
  auto* pipeline=gst_pipeline_new(nullptr);auto* input=gst_element_factory_make("appsrc",nullptr);
  auto* queue=gst_element_factory_make("queue",nullptr);auto* sink=gst_element_factory_make("fakesink",nullptr);
  assert(pipeline&&input&&queue&&sink);Source live;live.recorded=false;
  configure_source_queue(queue,live,true);
  g_object_set(input,"format",GST_FORMAT_TIME,"is-live",TRUE,"block",TRUE,"max-buffers",guint64(1),nullptr);
  g_object_set(sink,"sync",FALSE,"async",FALSE,"signal-handoffs",TRUE,nullptr);
  StalledConsumer state;g_signal_connect(sink,"handoff",G_CALLBACK(stalled_handoff),&state);
  gst_bin_add_many(GST_BIN(pipeline),input,queue,sink,nullptr);assert(gst_element_link_many(input,queue,sink,nullptr));
  assert(gst_element_set_state(pipeline,GST_STATE_PLAYING)!=GST_STATE_CHANGE_FAILURE);
  auto push=[&](uint64_t n){auto* b=gst_buffer_new_allocate(nullptr,1,nullptr);GST_BUFFER_PTS(b)=n;assert(gst_app_src_push_buffer(GST_APP_SRC(input),b)==GST_FLOW_OK);};
  push(0);{std::unique_lock<std::mutex> lock(state.mutex);assert(state.changed.wait_for(lock,std::chrono::seconds(2),[&]{return state.entered;}));}
  auto producer=std::async(std::launch::async,[&]{for(uint64_t n=1;n<=100;++n)push(n);});
  // No upstream backpressure while the downstream tracker is completely blocked.
  assert(producer.wait_for(std::chrono::seconds(2))==std::future_status::ready);producer.get();
  guint level=0;for(unsigned i=0;i<200;++i){g_object_get(queue,"current-level-buffers",&level,nullptr);if(level==4)break;std::this_thread::sleep_for(std::chrono::milliseconds(2));}
  assert(level==4);
  {std::lock_guard<std::mutex> lock(state.mutex);state.release=true;}state.changed.notify_all();
  {std::unique_lock<std::mutex> lock(state.mutex);assert(state.changed.wait_for(lock,std::chrono::seconds(2),[&]{return !state.seen.empty()&&state.seen.back()==100;}));assert(state.seen.size()<=5&&state.seen.front()==0);}
  gst_element_set_state(pipeline,GST_STATE_NULL);gst_object_unref(pipeline);
  auto* recorded_queue=gst_element_factory_make("queue",nullptr);Source recorded;recorded.recorded=true;
  configure_source_queue(recorded_queue,recorded,true);gint leaky=-1;g_object_get(recorded_queue,"leaky",&leaky,nullptr);assert(leaky==0);
  configure_source_queue(recorded_queue,live,false);g_object_get(recorded_queue,"leaky",&leaky,nullptr);assert(leaky==0);gst_object_unref(recorded_queue);
  std::cout<<"Live native decoded queue drains producer during a blocked tracker, retains latest four frames; recorded and other clocks remain lossless\n";
}
