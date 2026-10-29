// SPDX-License-Identifier: Apache-2.0
#pragma once
#include <algorithm>
#include <cmath>
#include <cstddef>
#include <stdexcept>
#include <string>
#include <vector>

namespace city {
inline constexpr const char* kTrackingPostprocessRevision = "one-city-class-per-query-v1";
inline std::string tracking_model_revision(const std::string& model) {
  const std::string suffix = std::string(";postprocess=") +
      (model.rfind("trafficcamnet", 0) == 0 ? "nvidia-tao-top200-city-traffic-v1" : kTrackingPostprocessRevision);
  if (model.empty()) throw std::invalid_argument("Model revision is required");
  if (model.size() >= suffix.size() && model.compare(model.size()-suffix.size(), suffix.size(), suffix) == 0)
    return model;
  return model + suffix;
}
struct Detection { unsigned int class_id; float score, x, y, width, height; std::size_t query_index=0; };
inline float sigmoid(float x) {
  if (x >= 0) return 1.0f / (1.0f + std::exp(-x));
  const float e = std::exp(x); return e / (1.0f + e);
}
// Pretrained RF-DETR uses sparse COCO category IDs, including slot zero.
inline int city_class(unsigned int slot) {
  switch(slot) { case 1:return 0; case 2:return 1; case 3:return 2;
    case 4:return 3; case 6:return 4; case 8:return 5; default:return -1; }
}
inline const char* class_name(unsigned int slot) {
  static const char* names[] = {"person", "bicycle", "car", "motorcycle", "bus", "truck", "two-wheeler"};
  return slot < 7 ? names[slot] : "unknown";
}
// Reference RF-DETR selection is global query x class top-k, not softmax or
// one argmax per query. Restricting classes before top-k changes that contract.
inline std::vector<Detection> decode(const float* boxes, const float* logits,
    std::size_t queries, std::size_t classes, unsigned width, unsigned height,
    float threshold, std::size_t top_k = 300) {
  if (!boxes || !logits || classes < 91 || !queries || !width || !height)
    throw std::invalid_argument("RF-DETR sparse COCO tensor contract invalid");
  struct Candidate { float score; std::size_t index; };
  std::vector<Candidate> ranked; ranked.reserve(queries * classes);
  for (std::size_t i = 0; i < queries * classes; ++i) {
    if (std::isfinite(logits[i])) ranked.push_back({sigmoid(logits[i]), i});
  }
  top_k = std::min(top_k, ranked.size());
  std::partial_sort(ranked.begin(), ranked.begin() + top_k, ranked.end(),
      [](const Candidate& a, const Candidate& b) {
        return a.score == b.score ? a.index < b.index : a.score > b.score;
      });
  std::vector<Detection> result;
  for (std::size_t i = 0; i < top_k; ++i) {
    const auto& c = ranked[i]; if (c.score < threshold) continue;
    const int cls = city_class(c.index % classes); if (cls < 0) continue;
    const float* b = boxes + (c.index / classes) * 4;
    if (!std::isfinite(b[0]) || !std::isfinite(b[1]) ||
        !std::isfinite(b[2]) || !std::isfinite(b[3]) || b[2] <= 0 || b[3] <= 0) continue;
    const float x1 = std::clamp((b[0] - b[2]/2) * width, 0.0f, float(width));
    const float y1 = std::clamp((b[1] - b[3]/2) * height, 0.0f, float(height));
    const float x2 = std::clamp((b[0] + b[2]/2) * width, 0.0f, float(width));
    const float y2 = std::clamp((b[1] + b[3]/2) * height, 0.0f, float(height));
    if (x2 > x1 && y2 > y1) result.push_back({unsigned(cls), c.score, x1, y1, x2-x1, y2-y1, c.index / classes});
  }
  return result;
}
// A tracker consumes objects, not competing labels for one RF-DETR query.
// Preserve the reference top-k/capability filtering, then retain its highest
// scoring city label per query. This is an operational counting policy, not the
// reference multi-label benchmark decoder. Distinct queries are never merged by
// box overlap: two real objects can overlap or even have identical rounded boxes.
inline std::vector<Detection> decode_for_tracking(const float* boxes, const float* logits,
    std::size_t queries, std::size_t classes, unsigned width, unsigned height,
    float threshold, std::size_t top_k = 300) {
  auto candidates = decode(boxes, logits, queries, classes, width, height, threshold, top_k);
  std::vector<bool> retained(queries, false);
  candidates.erase(std::remove_if(candidates.begin(), candidates.end(), [&](const Detection& detection) {
    if (retained[detection.query_index]) return true;
    retained[detection.query_index] = true; return false;
  }), candidates.end());
  return candidates;
}
inline float normalize_rgb(float pixel, unsigned channel) {
  constexpr float mean[3] = {.485f,.456f,.406f};
  constexpr float stddev[3] = {.229f,.224f,.225f};
  return (pixel / 255.0f - mean[channel]) / stddev[channel];
}
}
