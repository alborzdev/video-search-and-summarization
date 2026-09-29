# Live input diagnosis: capture seam and controlled comparison

September 28, after seeded runtime recovery. Source inspection, not a new live trial.

## What existing instrumentation actually provides

- `video_file_frame_getter.py:add_to_cache` clones decoded GPU frames before
  releasing the DeepStream buffer. Live selectors append frames whose PTS occur
  in their selected timestamp lists. This is in-memory storage.
- `_process_finished_chunks` preprocesses the selected frames and passes both
  frames and `fs_data.cached_pts` to the chunk callback. It derives NTP bounds
  from stream/SEI time; those bounds need comparison with actual input timestamps.
- `rtvi_stream_handler.py:_build_frame_messages` publishes frame IDs/timestamps,
  not pixel payloads. Its cached-frame directory cleanup is not proof that
  images are exported by the active video pipeline.
- `vllm_compatible_model.py:generate` may cap frames, changes temporal metadata,
  and prepares the prompt. `process_async_vllm` copies the selected raw tensors
  to NumPy immediately before passing them to the engine. That engine boundary
  is the useful capture point: decoder previews alone are weaker evidence.
- No existing opt-in persistent raw-input export found in these active paths.
  Debug prompt logs and generation parameters do not capture visual content.

## Ranked, falsifiable hypotheses

1. Input mismatch: actual live samples differ from reconstructed retained frames.
   Capture exact engine-bound arrays/times and compare them with the saved interval.
   Prediction: the discrepant frame or timing is visible in that comparison.
2. Prompt/metadata difference: same pixels are interpreted differently with live
   timestamps or metadata. Replay captured pixels with the captured prompt and
   sampling parameters before changing one metadata variable at a time.
3. Model judgment: the actual pixels include the box but the model answers NO.
   Repeat exactly captured inputs with seeded parameters; score against manual
   review. A repeatable NO supports this hypothesis, not a sampling defect.

## Instrumentation requirements before another trial

Implement opt-in, disabled-by-default capture at the engine boundary. Bound total
bytes and request count; record array shape/dtype/hash, exact frame times and
metadata, prompt, model identity and SamplingParams. Capture the corresponding
response under the same request ID. Avoid another image decode, resizing or
resampling in the evidence path. Report capture overhead separately from normal
latency. Failures to export must not change inference output or disable safeguards.

No change to the current runtime was made in this inspection. Any new loaded
model code requires a documented restart; do not pretend a source mount hot reloads
workers. Existing seed tests and fixed-file observations remain valid within scope.

## Trial preparation

Discover the current URL for sensor `6776f3a6-446f-4da8-832e-cfcf4507de8c` from
VIOS `/v1/live/streams`. Recovery changed the usable diagnostic proxy from30556
to the API-returned30557. Confirm video with ffprobe before registering the same
source. Do not construct a port from a historical trial. The app forwards its
selected source URL and has no hardcoded30556/30557 in the inspected alert paths.
Keep guard48GiB, stopped detectors, single bounded rule, watchdog cleanup and
post-run zero-stream/rule verification. Reconstructed clips are supporting evidence,
not substitutes for captured model input.

## Capture implemented; runtime validation pending

Added `src/utils/input_capture.py` and a guarded engine-boundary call in the vLLM
adapter. `RTVI_CAPTURE_INPUTS_DIR` must be nonempty; Compose defaults it to empty
and mounts the helper read-only. Current running workers are unchanged.

Capture accepts only contiguous uint8 video arrays (NHWC, RGB/RGBA), at most4MiB
per array. It writes lossless `frames.npy`, original token IDs, video metadata,
frame times, chunk timing fields and effective sampling arguments to `input.json`.
No source URL or credentials are captured. Pixels have SHA256. Successful raw
engine responses are linked by request ID in `response.json`; failed inference may
leave an input-only capture. Prompt token IDs require the same tokenizer for
human-readable decoding; they preserve the effective token sequence.

Limits:12request directories,64MiB total with conservative JSON/header reserves,
512KiB per JSON file. A filesystem lock coordinates exporters sharing a directory.
No overwrite of duplicate IDs. Unsupported input or full budget skips capture;
exceptions are logged and inference proceeds. `capture-seconds.txt` measures export
overhead before inference. This is raw engine input, not the model processor's
final resized/normalized tensor. Disabling capture does not remove saved evidence.

Seven standard-library/NumPy tests pass, including execution of the real adapter
method against a recording engine to verify disabled/error paths leave inputs,
sampling parameters and answer unchanged. Seed constructor regression also passes.
These are CPU tests, not proof of active GPU capture or live performance. New
worker startup and an opt-in directory are required before a bounded live test.

## Source isolation and expiry verified before loading

Both `RTVI_CAPTURE_INPUTS_DIR` and `RTVI_CAPTURE_SOURCE_URL` are required. The
source must begin with `rtsp://` and match `chunk.file` exactly. Warmup files,
recorded questions, missing chunk sources and other cameras do not export inputs.
The live decoder assigns its stream URL to `chunk.file`; this is the source gate
used by the adapter, rather than a guessed sensor identifier.

The capture directory records its first eligible capture time in `.started`.
Further inputs are rejected at 120 seconds, including after worker restarts using
that same directory. A new trial needs a new directory. This bounds the export
window, not the lifetime of inference; a separate trial watchdog must still remove
the stream and rule. Saved evidence is retained.

Source inspection confirms the dynamic loader selects uint8 frames, disables
decoder normalization by default, and stacks frames before passing them onward.
The adapter copies the tensor to NumPy before the hook. The CPU integration test
now executes that asynchronous conversion with a tensor stand-in, asserting that
the capture and engine receive the identical resulting array. It also covers the
exact-source gate, disabled capture and export failure without changing the answer.
All seven tests passed in 0.048 seconds. This does not prove the running decoder's
dimensions/strides, GPU behavior or capture overhead; inspect those in the first
bounded live run. Four 512×512 RGB uint8 frames fit the 4 MiB array limit.
