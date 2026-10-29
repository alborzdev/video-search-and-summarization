// SPDX-License-Identifier: Apache-2.0
// Production payloader callback and CLI, without CUDA or a running source.
#define main unused_city_worker_entrypoint
#include "../src/city_worker.cpp"
#undef main
#include <cassert>
int main(int argc,char** argv) {
  gst_init(&argc,&argv);
  auto* internal=gst_element_factory_make("appsink",nullptr);assert(internal);
  preview_live_publish_element(nullptr,nullptr,internal,nullptr);
  gboolean synchronized=TRUE,asynchronous=TRUE;g_object_get(internal,"sync",&synchronized,"async",&asynchronous,nullptr);
  assert(!synchronized&&!asynchronous);gst_object_unref(internal);
  App app;app.options.preview_transport="webrtc";
  auto& source=app.previews[0];source.app=&app;source.index=0;
  city::PreviewProvenance provenance{"cam","epoch","model",17,123456,1280,480,steady_ns()};
  source.identities.reserve_at(1000000000ULL,provenance);
  auto* packet=gst_rtp_buffer_new_allocate(4,0,0);GST_BUFFER_PTS(packet)=1000000000ULL;
  GstRTPBuffer rtp=GST_RTP_BUFFER_INIT;assert(gst_rtp_buffer_map(packet,GST_MAP_WRITE,&rtp));
  gst_rtp_buffer_set_timestamp(&rtp,UINT32_MAX-8);gst_rtp_buffer_set_marker(&rtp,FALSE);gst_rtp_buffer_unmap(&rtp);
  preview_rtp_packet(&source,packet);assert(app.video_outbox.size()==0&&source.identities.size()==1);
  assert(gst_rtp_buffer_map(packet,GST_MAP_WRITE,&rtp));gst_rtp_buffer_set_marker(&rtp,TRUE);gst_rtp_buffer_unmap(&rtp);
  std::atomic<bool> returned{false};
  std::thread publication([&]{preview_rtp_packet(&source,packet);returned=true;});
  std::optional<city::PreviewPacket> posted;
  {std::unique_lock<std::mutex> lock(app.preview_mutex);
    assert(app.preview_changed.wait_for(lock,std::chrono::milliseconds(500),[&]{return app.video_outbox.has_source(0);}));
    posted=app.video_outbox.pop_source(0);}
  assert(posted&&posted->provenance.sequence==17&&posted->provenance.source_time_ns==123456);
  assert(posted->metadata_receipt&&!returned);
  posted->metadata_receipt->finish(true);publication.join();
  assert(returned&&source.metadata_ready==1&&source.metadata_unconfirmed==0);
  const std::string body(posted->jpeg.begin(),posted->jpeg.end());
  assert(body.find("\"rtpTimestamp\":4294967287")!=std::string::npos&&body.find("nvenc-h264")!=std::string::npos);
  preview_rtp_packet(&source,packet);assert(source.identity_missing==1&&app.video_outbox.size()==0);
  gst_buffer_unref(packet);
  city::PreviewMetadataReceipt failed;failed.finish(false);failed.finish(true);
  assert(!failed.wait(std::chrono::milliseconds(1))); // A rejection cannot turn into an admission.
  city::PreviewMetadataReceipt unavailable;
  assert(!unavailable.wait(std::chrono::milliseconds(1))); // Missing HTTP has a bounded wait.
  city::PreviewOutbox metadata(2,16);
  for(unsigned sequence=0;sequence<18;++sequence){city::PreviewPacket value;value.source_index=0;value.provenance.sequence=sequence;
    assert(metadata.push(std::move(value))==(sequence>=16));}
  assert(metadata.size()==16);
  for(unsigned sequence=2;sequence<18;++sequence)assert(metadata.pop_source(0)->provenance.sequence==sequence);
  std::vector<std::string> values{"worker","--source","cam=rtsp://localhost/camera","--output","/tmp/unused",
    "--preview-transport","webrtc","--preview-url","http://127.0.0.1:9184/api/v1/city/video/frame"};
  auto parse=[&](){std::vector<char*> args;for(auto& value:values)args.push_back(value.data());return parse_options(args.size(),args.data());};
  assert(parse().preview_transport=="webrtc");
  values.back()="http://127.0.0.1:9184/api/v1/city/preview";
  bool rejected=false;try{parse();}catch(...){rejected=true;}assert(rejected);
  std::cout<<"Exact emitted RTP timestamp, AU completion, stale identity and video CLI checks passed\n";
}
