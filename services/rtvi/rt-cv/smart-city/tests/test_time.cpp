// SPDX-License-Identifier: Apache-2.0
#include "media_clock.hpp"
#include <cassert>
#include <iostream>
int main() {
  GstSegment segment;gst_segment_init(&segment,GST_FORMAT_TIME);
  // Actual MP4 edit-list segment offsets from the provided test recordings.
  segment.start=66666666;segment.time=0;
  auto first=city::media_clock(segment,66666666);assert(first&&first->stream_time==0);
  auto next=city::media_clock(segment,100000000);assert(next&&next->stream_time==33333334);
  segment.start=200000000;
  assert(city::media_clock(segment,200000000)->stream_time==0);
  assert(city::media_clock(segment,300000000)->stream_time==100000000);
  // A seek segment can have a nonzero media timeline. Subtracting the first
  // decoded PTS would incorrectly erase this explicit media-time offset.
  segment.start=12*GST_SECOND;segment.time=8*GST_SECOND;
  assert(city::media_clock(segment,12*GST_SECOND)->stream_time==8*GST_SECOND);
  assert(city::media_clock(segment,13*GST_SECOND)->stream_time==9*GST_SECOND);
  assert(!city::media_clock(segment,GST_CLOCK_TIME_NONE));
  segment.format=GST_FORMAT_BYTES;assert(!city::media_clock(segment,1));
  std::cout<<"GStreamer MP4 edit-list and seek-segment stream-time controls passed\n";
}
