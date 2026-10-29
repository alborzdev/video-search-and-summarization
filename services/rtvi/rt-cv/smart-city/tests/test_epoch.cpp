// SPDX-License-Identifier: Apache-2.0
#include "source_epoch.hpp"
#include <cassert>
#include <iostream>
int main() {
  city::SourceEpochClock clock;
  assert(clock.observe(100,1000,"arrival-pts-unsynchronized").empty());
  assert(clock.observe(200,1100,"arrival-pts-unsynchronized").empty());
  // A delayed first RTCP sender report can jump either direction while PTS
  // remains monotonic. Neither transition may inherit an existing dwell.
  assert(clock.observe(300,1000000,"source-rtcp")=="source-clock-basis-changed");
  assert(clock.observe(400,1000100,"source-rtcp").empty());
  assert(clock.observe(500,1400,"arrival-pts-unsynchronized")=="source-clock-basis-changed");
  assert(clock.observe(600,1200,"source-rtcp")=="source-clock-basis-changed");
  assert(clock.observe(700,1199,"source-rtcp")=="source-time-rewound");
  assert(clock.observe(800,1300,"source-rtcp").empty());
  assert(clock.observe(1,1400,"source-rtcp")=="source-pts-rewound");
  assert(clock.observe(2,1401,"source-rtcp").empty());
  // Recorded edit-list/seek time can rewind independently of monotonic PTS.
  city::SourceEpochClock recorded;
  assert(recorded.observe(100,8000,"recorded-pts").empty());
  assert(recorded.observe(200,4000,"recorded-pts")=="source-time-rewound");
  std::cout<<"Source clock basis, RTCP transition and rollback epoch controls passed\n";
}
