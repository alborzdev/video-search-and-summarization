// SPDX-License-Identifier: MIT
// Change the revision when replacing story imagery so already-open tabs request
// the new files, including tabs that previously received a missing-asset response.
const revision = "2026-10-28-reference-5";
export function cityStoryAsset(filename: string): string {
  return `/vision/smart-city-story/${filename}?v=${revision}`;
}
