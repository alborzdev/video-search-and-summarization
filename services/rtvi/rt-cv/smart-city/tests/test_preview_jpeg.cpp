// SPDX-License-Identifier: Apache-2.0
// CPU-only synthetic I420 -> installed jpegenc -> appsink correlation control.
#include "preview_core.hpp"
#include <gst/gst.h>
#include <gst/app/gstappsrc.h>
#include <gst/app/gstappsink.h>
#include <cassert>
#include <iostream>
int main(int argc,char** argv) {
  // Load exactly the three CPU plugins below. Do not scan GPU/RTSP plugins on
  // a workstation that happens to have them installed.
  g_setenv("GST_PLUGIN_SYSTEM_PATH_1_0","",TRUE);g_setenv("GST_PLUGIN_PATH_1_0","",TRUE);
  g_setenv("GST_REGISTRY","/tmp/city-preview-cpu-registry.bin",TRUE);
  gst_init(&argc,&argv);GError* error=nullptr;
  for(auto* name:{"libgstcoreelements.so","libgstapp.so","libgstjpeg.so"}) {
    const std::string path=std::string(TEST_GST_PLUGIN_DIR)+"/"+name;
    auto* plugin=gst_plugin_load_file(path.c_str(),&error);
    if(!plugin){std::cerr<<(error?error->message:"Missing CPU plugin")<<'\n';if(error)g_error_free(error);return 1;}
    gst_object_unref(plugin);
  }
  auto* pipeline=gst_parse_launch("appsrc name=raw format=time is-live=false block=true max-bytes=200000 "
      "caps=video/x-raw,format=I420,width=320,height=180,framerate=15/1 ! "
      "jpegenc quality=70 snapshot=false ! appsink name=jpeg sync=false async=false max-buffers=4 enable-last-sample=false wait-on-eos=false",&error);
  if(error){std::cerr<<error->message<<'\n';g_error_free(error);return 1;}
  assert(pipeline);auto* source=gst_bin_get_by_name(GST_BIN(pipeline),"raw");auto* sink=gst_bin_get_by_name(GST_BIN(pipeline),"jpeg");
  assert(gst_element_set_state(pipeline,GST_STATE_PLAYING)!=GST_STATE_CHANGE_FAILURE);
  city::PreviewIdentityMap identities;
  for(uint64_t sequence=7;sequence<11;sequence++) {
    city::PreviewProvenance p{"camera","same-epoch","model-sha",sequence,123456,320,180};
    auto* frame=gst_buffer_new_allocate(nullptr,320*180*3/2,nullptr);assert(frame);
    gst_buffer_memset(frame,0,sequence%2?255:0,320*180*3/2);
    GST_BUFFER_PTS(frame)=identities.reserve(p);GST_BUFFER_DTS(frame)=GST_CLOCK_TIME_NONE;GST_BUFFER_DURATION(frame)=GST_CLOCK_TIME_NONE;
    assert(gst_app_src_push_buffer(GST_APP_SRC(source),frame)==GST_FLOW_OK);
  }
  assert(gst_app_src_end_of_stream(GST_APP_SRC(source))==GST_FLOW_OK);
  for(uint64_t sequence=7;sequence<11;sequence++) {
    auto* sample=gst_app_sink_try_pull_sample(GST_APP_SINK(sink),GST_SECOND);assert(sample);
    auto* buffer=gst_sample_get_buffer(sample);auto provenance=identities.take(GST_BUFFER_PTS(buffer));
    assert(provenance&&provenance->sequence==sequence&&provenance->source_time_ns==123456);
    int width=0,height=0;auto* shape=gst_caps_get_structure(gst_sample_get_caps(sample),0);
    assert(gst_structure_get_int(shape,"width",&width)&&gst_structure_get_int(shape,"height",&height));
    assert(width==320&&height==180);assert(gst_buffer_get_size(buffer)<city::kMaxPreviewBytes);
    GstMapInfo map;assert(gst_buffer_map(buffer,&map,GST_MAP_READ));
    assert(map.size>4&&map.data[0]==0xff&&map.data[1]==0xd8&&map.data[map.size-2]==0xff&&map.data[map.size-1]==0xd9);
    gst_buffer_unmap(buffer,&map);gst_sample_unref(sample);
  }
  assert(identities.size()==0);gst_element_set_state(pipeline,GST_STATE_NULL);
  gst_object_unref(source);gst_object_unref(sink);gst_object_unref(pipeline);
  std::cout<<"Installed CPU jpegenc preserves four exact encoder-token identities, duplicate source timestamps, geometry and bounded JPEG bodies\n";
}
