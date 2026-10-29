// SPDX-License-Identifier: Apache-2.0
#include "preview_core.hpp"
#include <cassert>
#include <iostream>
int main() {
  city::PreviewIdentityMap tags(2);
  city::PreviewProvenance a{"north","epoch-one","model-sha",7,123456,1920,1080};
  auto b=a;b.sequence=8; // Duplicate camera PTS is deliberately not a key.
  auto ta=tags.reserve(a),tb=tags.reserve(b);assert(ta!=tb);
  assert(ta>=city::kPreviewTokenBase&&!tags.take(123456));
  auto rb=tags.take(tb);assert(rb&&rb->sequence==8&&rb->session=="epoch-one");
  auto ra=tags.take(ta);assert(ra&&ra->sequence==7&&ra->width==1920);
  assert(!tags.take(ta));
  auto old=tags.reserve(a);tags.reserve(b);auto epoch=b;epoch.session="epoch-two";epoch.sequence=0;
  auto latest=tags.reserve(epoch);assert(tags.evicted==1&&tags.size()==2&&!tags.take(old));
  assert(tags.take(latest)->session=="epoch-two");
  for(int i=0;i<100000;i++){auto tag=tags.reserve(a);assert(tags.take(tag));assert(tags.size()<=2);}
  city::PreviewSampler rate;assert(rate.select(0,15));assert(rate.select(10000000,15));
  assert(!rate.select(10000001,15));assert(rate.select(66666667,15));
  assert(!rate.select(60000000,15));assert(rate.select(133333334,15));
  city::PreviewSampler cadence;int selected=0;
  for(uint64_t i=0;i<900;i++)selected+=cadence.select(i*1000000000ULL/30,15);
  assert(selected==451); // Exact cadence + one bounded initial burst credit.
  assert(cadence.select(60000000000ULL,15));assert(cadence.select(60000000001ULL,15));
  assert(!cadence.select(60000000002ULL,15));
  city::PreviewSampler bursts;int burst_selected=0;
  // Six two-frame arrivals/s == 12FPS, below the30 cap. Preserve both current
  // frames even when demux arrivals are only1ms apart after upstream batching.
  for(uint64_t i=0;i<300;i++) {
    const auto at=i*166666667ULL;
    burst_selected+=bursts.select(at,30);
    burst_selected+=bursts.select(at+1000000ULL,30);
  }
  assert(burst_selected==600);
  city::PreviewSampler flood;uint64_t flood_count=0;
  for(uint64_t ns=0;ns<10000000000ULL;ns+=1000000ULL) {
    flood_count+=flood.select(ns,15);
    assert(flood_count<=2+(ns*15)/1000000000ULL);
  }
  assert(flood_count==151);
  city::PreviewSampler rollback;assert(rollback.select(100,30));
  assert(!rollback.select(99,30));assert(!rollback.select(99,30));
  assert(rollback.select(100,30));assert(!rollback.select(100,30));
  assert(rollback.select(UINT64_MAX,30));assert(rollback.select(UINT64_MAX,30));
  assert(!rollback.select(UINT64_MAX,30));
  city::PreviewOutbox queue(2);
  auto packet=[&](size_t index,uint64_t sequence){city::PreviewPacket p;p.source_index=index;p.provenance=a;p.provenance.sequence=sequence;p.jpeg={1,2,3};return p;};
  assert(!queue.push(packet(0,1)));assert(!queue.push(packet(1,2)));
  for(int i=3;i<100003;i++)assert(queue.push(packet(0,i)));
  assert(queue.size()==2);assert(queue.pop()->provenance.sequence==100002);
  assert(queue.pop()->source_index==1);assert(!queue.pop());
  assert(!queue.push(packet(0,1)));assert(!queue.push(packet(1,2)));
  assert(queue.has_source(1)&&queue.has_source(0));
  assert(!queue.pop_source(2));assert(queue.pop_source(1)->provenance.sequence==2);
  // Source0 can remain blocked/in flight while source1 serves its latest frame.
  assert(queue.has_source(0)&&!queue.has_source(1));assert(!queue.push(packet(1,3)));
  assert(queue.pop_source(1)->provenance.sequence==3);assert(queue.pop_source(0)->source_index==0);
  assert(!queue.has_source(0)&&queue.size()==0);
  city::PreviewTiming timings;
  assert(timings.snapshot().count==0);
  for(uint64_t i=1;i<=20;i++)timings.record(i*1000000);
  const auto measured=timings.snapshot();
  assert(measured.count==20&&measured.mean_ms==10.5&&measured.last_ms==20&&measured.max_ms==20);
  assert(measured.p50_upper_ms==10&&measured.p95_upper_ms==20);
  timings.record(9000000000ULL);
  assert(timings.snapshot().max_ms==9000); // Last bucket is bounded by actual max.
  bool invalid=false;try{queue.push(packet(2,0));}catch(const std::invalid_argument&){invalid=true;}assert(invalid);
  assert(city::parse_preview_fps("15")==15);
  for(auto value:{"0","31","1.5","15bad","-1"}){invalid=false;try{city::parse_preview_fps(value);}catch(...){invalid=true;}assert(invalid);}
  assert(city::preview_url_valid("http://127.0.0.1:9184/api/v1/city/preview"));
  assert(city::preview_url_valid("http://vss-city-analytics:9184/api/v1/city/preview"));
  assert(!city::preview_url_valid("file:///tmp/preview"));assert(!city::preview_url_valid("http://user:secret@host/api/v1/city/preview"));
  assert(!city::preview_url_valid("http://host/api/v1/city/preview?token=private"));
  assert(city::preview_header_valid("rfdetr-medium-fp16@sha256:abc"));assert(!city::preview_header_valid("id\r\nInjected: header"));
  std::cout<<"Preview exact identities, bounded dropped-display queues, FPS and CLI controls passed\n";
}
