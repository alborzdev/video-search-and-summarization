// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <cstdint>
#include <optional>
#include <string>

namespace city {
// Source timestamps may switch from a local approximation to RTCP after the
// first sender report. That is a new clock epoch even when raw PTS increases.
struct SourceEpochClock {
  std::optional<uint64_t> last_pts,last_source_time;
  std::string last_basis;
  std::string observe(uint64_t pts,uint64_t source_time,const std::string& basis) {
    std::string reason;
    if(last_pts) {
      if(basis!=last_basis)reason="source-clock-basis-changed";
      else if(pts<*last_pts)reason="source-pts-rewound";
      else if(source_time<*last_source_time)reason="source-time-rewound";
    }
    last_pts=pts;last_source_time=source_time;last_basis=basis;
    return reason;
  }
};
}
