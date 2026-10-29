// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <gst/gst.h>
#include <optional>
namespace city {
struct MediaClock {
  GstClockTime raw_pts,stream_time,segment_start,segment_time;
};
inline std::optional<MediaClock> media_clock(const GstSegment& segment,GstClockTime pts) {
  if(segment.format!=GST_FORMAT_TIME||pts==GST_CLOCK_TIME_NONE)return std::nullopt;
  const auto stream=gst_segment_to_stream_time(&segment,GST_FORMAT_TIME,pts);
  if(stream==GST_CLOCK_TIME_NONE)return std::nullopt;
  return MediaClock{pts,stream,segment.start,segment.time};
}
}
