import { THOR_LIVE_CAPTION_PROFILE } from '../../../server/vision/liveCaptionProfile';

describe('bounded live history producer', () => {
  it('keeps the established sampling and token budget without audio or hidden reasoning', () => {
    expect(THOR_LIVE_CAPTION_PROFILE).toEqual({
      chunk_duration: 30,
      enable_audio: false,
      enable_reasoning: false,
      max_tokens: 256,
      num_frames_per_second_or_fixed_frames_chunk: 4,
      use_fps_for_chunking: false,
      vlm_input_height: 512,
      vlm_input_width: 512,
    });
  });
});
