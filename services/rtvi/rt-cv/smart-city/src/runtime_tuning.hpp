// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <charconv>
#include <cstdint>
#include <stdexcept>
#include <string>
namespace city {
constexpr uint32_t kDefaultMuxTimeoutUs=40000;
inline unsigned parse_unsigned_option(const std::string& text, const char* option) {
  unsigned value=0;
  const auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
  if(parsed.ec!=std::errc() || parsed.ptr!=text.data()+text.size())
    throw std::runtime_error(std::string(option)+" must be a complete in-range unsigned integer");
  return value;
}
inline uint32_t parse_mux_timeout(const std::string& text) {
  uint32_t value=0;
  const auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
  if(parsed.ec!=std::errc() || parsed.ptr!=text.data()+text.size() || value<1000 || value>1000000)
    throw std::runtime_error("--mux-timeout-us must be an integer from 1000 to 1000000");
  return value;
}
}
