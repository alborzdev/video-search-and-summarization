// SPDX-License-Identifier: Apache-2.0
#include "runtime_tuning.hpp"
#include <cassert>
#include <iostream>
#include <limits>
int main() {
  assert(city::parse_unsigned_option("0","--frames")==0); // explicit unlimited remains supported
  assert(city::parse_unsigned_option("480","--frames")==480);
  assert(city::parse_unsigned_option(std::to_string(std::numeric_limits<unsigned>::max()),"--frames")==std::numeric_limits<unsigned>::max());
  for(const auto* invalid:{"","4294967296","-1","+1","10junk","1.5"," 10","10 ","99999999999999999999999999"}) {
    bool rejected=false;
    try {city::parse_unsigned_option(invalid,"--frames");}catch(const std::runtime_error& error) {
      rejected=std::string(error.what()).find("--frames")!=std::string::npos;
    }
    assert(rejected);
  }
  assert(city::kDefaultMuxTimeoutUs==40000);
  assert(city::parse_mux_timeout("40000")==40000);
  assert(city::parse_mux_timeout("10000")==10000);
  assert(city::parse_mux_timeout("1000")==1000);
  assert(city::parse_mux_timeout("1000000")==1000000);
  for(const auto* invalid:{"","0","999","1000001","-1","+1000","12.5","10000junk","99999999999999999999999999"," 10000"}) {
    bool rejected=false;
    try {city::parse_mux_timeout(invalid);}catch(const std::runtime_error&) {rejected=true;}
    assert(rejected);
  }
  std::cout<<"Strict unsigned CLI and mux timeout parsing, overflow rejection and preserved explicit defaults passed\n";
}
