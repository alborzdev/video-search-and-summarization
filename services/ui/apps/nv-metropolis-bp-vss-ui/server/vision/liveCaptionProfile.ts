// SPDX-License-Identifier: MIT

/**
 * Continuous captioning has to keep pace with the wall clock on one Thor.
 * Four fixed frames retain useful scene changes across each thirty-second
 * window. On one Thor, a structured Cosmos response can take longer than ten
 * seconds, so a ten-second producer interval creates an unbounded queue and
 * eventually delays live results by minutes. Semantic search still indexes
 * five-second RT-Embed chunks; this profile is the lower-frequency narrative
 * layer used by history and GraphRAG. The explicit spatial and token limits
 * also leave capacity for live alerts and ad-hoc visual inspection.
 */
export const THOR_LIVE_CAPTION_PROFILE = {
  chunk_duration: 30,
  max_tokens: 256,
  num_frames_per_second_or_fixed_frames_chunk: 4,
  use_fps_for_chunking: false,
  vlm_input_height: 512,
  vlm_input_width: 512,
} as const;

/**
 * Continuous alerts get the same bounded visual sampling cadence as history,
 * but a shorter answer budget because Alert Bridge needs a verdict rather
 * than a narrative. Keeping this explicit at the UI orchestration boundary
 * also makes the safe Thor contract survive misconfigured service defaults.
 */
export const THOR_LIVE_ALERT_PROFILE = {
  chunk_duration: 30,
  chunk_overlap_duration: 2,
  enable_audio: false,
  enable_reasoning: false,
  max_tokens: 128,
  num_frames_per_second_or_fixed_frames_chunk: 4,
  use_fps_for_chunking: false,
  vlm_input_height: 512,
  vlm_input_width: 512,
} as const;
