# First live engine-input capture — bounded positive-sample result

September 28, 23:07–23:09 EDT. This is recorded simulation replay over RTSP,
not the user's current Spark scene and not sustained monitoring qualification.

## Runtime and cleanup

The original staged startup session 86552 completed with exit1 because the first
UI request exceeded its five-second probe while Turbopack compiled the page.
UI log: compilation 7.3s, first HTTP200 8.549s. A separate core check passed all
31 roles without another restart. Restored the existing NvStreamer publisher;
VIOS-returned source port30557 passed an H2641920×1080 ffprobe. Boot ID unchanged.

Trial script session 96645 completed successfully. Rule
`5fdc4b08-758a-4fae-836d-1e868f53cb2c` was removed at the 90-second limit.
Cleanup confirmed zero rules and zero RT-VLM streams. Minimum available memory
was 54.413 GiB across 97 samples; final core check passed at54.41GiB. The48GiB
guard and stopped-detector configuration were preserved.

## What was actually captured

Nine exact engine-bound uint8 RGB arrays, each4×512×512×3, with matching input
metadata and raw engine responses. SHA256 and shape/dtype verification passed
for all arrays. Effective sampling: temperature0.4, seed1, top_p0.8, top_k20,
max_tokens128, min_tokens0, ignore_eosfalse, repetition_penalty1.1.

Each request used the explicit any-frame box-presence prompt from the trial
script. Input captures arrived9.968–10.004seconds apart. This is input submission
cadence, **not** response latency. Export overhead was7.3–15.8milliseconds.
Frame PTS start at0.75s and continue to88.28s in the final captured window.

All nine responses wereYES. Manual review of all36 captured frames found a
visible box in every four-frame input. Window2 contains a crumpled box only in
its final sampled frame and correctly returnedYES; window3 includes that box
partially exiting in its first frame. No fully box-free input was captured.

## Interpretation and next discriminating check

The capture hook works on the real GPU/live path and preserves inspectable input
evidence. These nine positive inputs match their model responses. This does not
reproduce or explain the historical NO miss, establish false-positive behavior,
qualify damage recognition, or justify changing the app's30-second default.

The next run needs reviewed positive **and** fully negative sampled windows,
with captured input and response latency. Preserve this run before creating a
fresh capture directory. The configured directory's120-second capture window is
expired; leaving its environment enabled does not permit further exports there.
The trial rule and AI stream are removed. Browser review remains pending the
user's reopen of the policy-blocked error tab.

## Evidence

- [Trial and memory samples](live-input-capture-trial.json)
- [Trial script](live-input-capture-trial.py)
- [Runtime reload](capture-hook-runtime-reload.md)
- Engine arrays, metadata, responses, previews and manually annotated index:
  `artifacts/live-input-capture-20260929/` at the repository root.
- Contact sheets: `review-0.png`, `review-3.png`, `review-6.png` in that directory.
- Startup, stop and trial logs are preserved alongside this receipt.

## Response timing and second bounded sample

The first run's nine response log timestamps were0.558–0.709s after their
last-frame NTP timestamps. This excludes waiting for the sampling window and
event/UI delivery. Raw extracted timing is in
`live-input-capture-response-timing.json`.

A second90-second run used the identical condition and generation profile, after
preserving the first container capture directory as a separate run. It completed
and removed rule `9efe4c33-37d2-46f6-adc8-1b7c8156433d`, leaving zero rules and
AI streams with unchanged boot ID. All nine pixel hashes and response links
verified; manual review again found a box in every sampled input, with allYES
answers. Export overhead remained below15.6ms. Evidence is in
`artifacts/live-input-capture-20260929-run2/`, with trial receipt
`live-input-capture-trial-2.json` and timing `live-input-capture-response-timing-2.json`.

This adds positive-sample repeatability but still no negative-input score. Do not
run repeated random-start trials to obtain a desired result. Next, use a deliberately
timed empty interval or controlled replay sequence that supplies reviewed negative
inputs while preserving the distinction between diagnostic footage and the demo.
The trial script now requires `--output PATH` and refuses existing receipt paths.
