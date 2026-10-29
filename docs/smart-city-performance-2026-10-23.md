# Two-camera FPS work — October 23, 2026

The target is a smooth, useful two-camera demo with detection, tracking and city measurements active. Thirty FPS is an aspiration, not an acceptance threshold. The prepared camera profile is now **960 × 540**. Camera poses and field of view are unchanged. The profile requests up to 30 FPS. This requested rate is not a measured delivery rate.

## Changes retained

- Use the existing NVIDIA native H.264 camera path and packet relay. No external CPU camera encoder was restored.
- Reduce each source from 1280 × 720 to 960 × 540: 43.75% fewer source pixels. Keep RF-DETR Medium's 576 × 576 input and the tracker's calibrated 640 × 384 processing size.
- Pass 960 × 540 to the DeepStream mux. The previous launcher omitted dimensions. This caused 1920 × 1080 processing surfaces even for 720p video. Boxes still map back to source coordinates.
- Reduce only the separate GUI viewport to 640 × 360 with a 0.5 scale. Keep its updates on. The normal pre-stream helper rejects active camera products and leaves camera geometry unchanged.
- Disable the unused virtual gantry UI/runtime through the normal Kit manager before camera streaming. CLI flags alone were ineffective because the full experience re-enabled its dependency. Its stage scans consumed 0.895 seconds across 20 calls in the 15-second instrumented baseline. Keep shared schema and physics dependencies.
- Allow the exact-image preview worker and browser to use a ceiling up to 30 FPS. The browser accepts this cap only when native health is fresh and enabled. Each camera keeps only one fetch/decode in progress. Frame identity, ETag and bitmap cleanup rules stay in force.
- Keep every-frame RF-DETR inference and the existing experimental MV3DT map profile. Counts and rules remain camera-local.

## Calibration and city configuration

Resolution is part of calibration. The new package revision is `isaac-live-1769960ebf2c79c5`. Intrinsics and pixel projection rows scale by 0.75. Homographies scale inversely. The 640 × 384 tracker projection stays byte-exact. See [migration source controls](qa/smart-city-2026-10-23/fps/resolution-migration-source-controls.json).

The reviewed migration preserved both source UUIDs, the static map, all 14 rules, three turning movements, one queue, two pedestrian crossings, one curb area and mobility configuration revision 3. The MV3DT topic, `SeeThrough0` setting, image pin and gateway calibration allowlist were retained. The old configuration and the 720p profile are saved in the same QA directory and runtime backup. Generic preset regeneration was not used to replace those edits.

## Measurements and scope

The [instrumented 720p baseline](qa/smart-city-2026-10-23/fps/720p-instrumented-baseline-summary.json) measured about 9.51–9.52 native handoffs per second per camera. Python profiling adds overhead. GPU root scopes had a median near 33.6 ms in the separate GPU-only instrumentation sample. This is not a pure per-camera render time.

The valid [540p source-only window](qa/smart-city-2026-10-23/fps/540p-valid-native-no-analysis.json) measured 16.78 handoffs/s per camera over 15 seconds with analysis paused. [Two real decoder checks](qa/smart-city-2026-10-23/fps/540p-valid-decoded-no-analysis.json) confirmed nonblack 960 × 540 images, 48 distinct images per camera and media time progressing with received time. Extra decoder readers were present during the latter check.

With every-frame inference, the first [combined CPU-decode sample](qa/smart-city-2026-10-23/fps/540p-cpu-interval0-preview30.json) measured 12.84 native handoffs/s and 12.89–12.94 observations/s per camera over 20 seconds. Preview publishes were 10.84–11.09/s. Final 60-second receipts are saved separately. These short live windows show performance in a changing traffic scene. They do not establish a controlled speedup from resolution alone or a full-day endurance result.

## Final deployed check

The final settings keep normal RTPT bounce limits at 3, synchronous rendering, CPU decode and every-frame inference. The unused gantry UI/runtime are confirmed off. The startup helper checks for gantry geometry, requests UI-then-runtime shutdown, and waits for a later Kit update with both readbacks false before starting the cameras. The final helper was CPU-tested; the same viewport scale and ordinary manager shutdown were verified live. A complete fresh startup was not repeated after that last hook edit.

| Measure | Final result per camera |
| --- | --- |
| Native camera delivery, 60 seconds | 11.89 FPS |
| Accepted analyzed observations | 11.83 FPS over the 58.81-second sampled span |
| Exact preview publishes, 60 seconds | 10.39 / 10.41 FPS |
| Browser display | About 9–11 FPS in sampled windows; both overlays aligned |

The [rotation-aware integrated check](qa/smart-city-2026-10-23/fps/final-pipeline-60s.json) passed with 696 new observations and 12 exact-preview reads per source, no duplicate/backward timestamps, sequence gaps, source-session changes or monitored restarts/OOM events. It handled one NDJSON rotation. The separate one-off sampler held a retired inode and counted only 449 observations; its observation-rate fields are explicitly invalid. Use the [rotation-aware rate derivation](qa/smart-city-2026-10-23/fps/final-observation-rate.json), not that partial count.

The [simulator and recording check](qa/smart-city-2026-10-23/fps/final-isaac-60s.json) also passed. Minimum rolling native delivery was 11.85 FPS per source, with both recent five-second recordings ready. Minimum available memory was 21.56 GiB; the saved 20-GiB reserve and guard remain active. No VLM question was run. [Deployed identities](qa/smart-city-2026-10-23/fps/final-deployed.json) pin the model image, current source files, effective settings, camera calibration, preserved 14 rules and unchanged mobility setup.

The [browser receipt](qa/smart-city-2026-10-23/fps/final-browser.json) confirms two 960×540 image/overlay pairs, moving sequence counters, no relevant console warnings/errors, and working map zoom/reset controls. The screenshot uses the existing narrow app panel; desktop layout and long Firefox memory behavior were not retested in this pass.

Final focused validation: 167 VSS CPU tests, 12 city helper tests, 54 UI tests and TypeScript checks passed. No native worker image, TensorRT engine or production UI build was performed. This remains a short operational check, not full-day endurance or a labelled accuracy study.

## Trials rejected or not promoted

**Ray-bounce reduction:** setting both RTPT bounce limits to 1 produced fully black native camera images. Counts still advanced. Restoring both to 3 while running recovered the same 540p camera. The startup overrides were removed. All black-image rate receipts are marked invalid as working-demo benchmarks. Async mode was tested in the failed bundle, but it was not isolated as the cause. It remains off. See [failure and diagnosis correction](qa/smart-city-2026-10-23/fps/async-rendering-black-frame-failure.json).

**Two-bounce control:** reducing both limits to 2 delivered a valid but darker image and 11.64 FPS in a 20-second window. That did not establish enough gain to retain the image change; both limits returned to 3. See [the bounded control](qa/smart-city-2026-10-23/fps/two-bounce-control.json).

**Live viewport-off and native CPU profiler:** each stalled this Kit build. The failed probes and recovery receipts remain saved. Do not repeat them as performance controls. The active smaller viewport is the retained alternative. Rebinding the normal interactive viewport to a protected camera product was rejected because resizing and camera controls can alter that product/camera and shared rendering is not guaranteed.

**Hardware decode:** GB10 has NVDEC. The controlled worker loaded the NVIDIA decoder plugin and driver, delivered images, tracks and exact previews, and reached readiness. Its short [combined sample](qa/smart-city-2026-10-23/fps/540p-hardware-interval0-preview30.json) measured 11.10 handoffs/s per camera. It did not establish an advantage in this shared-GPU scene. CPU decode remains selected. This does not prove that CPU decode is always faster: object load and scene phase changed. The first hardware request was refused at cold-start admission before decoding. This is a separate failure, not a decoder failure.

**Inference interval:** the attempted interval 1 overlay did not reduce detection cadence. Installed DeepStream 9.2 source confirms that preprocessed tensor input uses `process_tensor_input`. This bypasses the interval counter in `process_full_frame`. The ineffective launch option and helper were removed. [Rejection evidence](qa/smart-city-2026-10-23/fps/inference-interval-rejected.json) preserves source hashes and the real trial. Separately, a [synthetic CPU proof](qa/smart-city-2026-10-23/fps/inference-interval-map-limit.json) shows that true alternating predictions would currently remove map hints and break adjacent-observation speed calculation. A future detector scheduler must fix those contracts and explicitly label predicted positions before it can be promoted.

## Remaining costs

| Area | Evidence and implication |
| --- | --- |
| Isaac rendering/native work | Source-only delivery remains below 30 FPS before analytics. Scene, render submission and the third GUI view still cost time. Lower geometry, material and light complexity, and a separate render machine, are the next larger controls. |
| Shared GPU | Rendering, 576 × 576 inference, per-object tracking and transforms share GB10. Source delivery falls when the full pipeline runs. This is an observed workload effect, not a complete GPU kernel attribution. |
| Tracker | The 640 × 384 processing size and per-object work remain. Keep calibration consistent if changing that size. Shrinking source video does not shrink this stage automatically. |
| Preview | GPU download, CPU JPEG, HTTP transfer and browser decode remain. Native rate limiting can skip bursts; latest-frame delivery avoids accumulating stale footage. Distinguish analyzed FPS from displayed FPS. |
| Transport | Native encoder Python handoff used only about 0.03 seconds per 15-second baseline. Publisher summaries showed bounded queues and no backpressure waits. Neither verifies every internal native encoder queue or all transport latency. |
| Detection detail | Smaller source images have less detail for distant people/bicycles. No labelled final-scene accuracy study was run in this fast pass. |

## Operator controls

Use the normal existing commands from `/home/sparkdev/vss`:

```sh
python3 tools/smart-city/isaac_demo.py status
python3 tools/smart-city/isaac_demo.py start
```

Open the [Smart City workspace](http://127.0.0.1:7782/?workspace=smart-city). The prepared tuning is:

```json
{"muxTimeoutUs":10000,"previewFps":30,"decoder":"cpu"}
```

Change tuning only while the owned analysis sessions are paused. Then resume through the normal Agent controls. Hardware decode can be explicitly trialled with `decoder: "hardware"`. Remove it or use `cpu` to restore Spark's established path. No `inferenceInterval` option is supported. A plain Start preserves the map, rules and calibration. Do not use generic refresh presets to overwrite the reviewed migration.

For a quick visual test, confirm that both cameras show moving images and stable boxes. Select a person or vehicle and follow it on the map. Check a line or area event and a recent five-second recording. Exact image/metadata pairing and spatial calibration do not prove cross-camera identity accuracy. Experimental person joins remain unqualified.
