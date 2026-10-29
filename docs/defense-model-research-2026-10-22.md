## Latest outcome: local vision is wired into VSS

The shared Moondream2/Photon + SAM 2.1 Tiny service is now running on Spark and
selected for automatic VSS startup/shutdown. Defense and Smart City both expose
**Local vision** for a displayed camera frame or uploaded image, with Segment,
Detect, Point and Describe actions. Actual browser segmentation took about
0.7 seconds in each checked workspace. Cosmos and segmentation completed
overlapping requests, the 20 GiB reserve stayed selected, and the minimum
observed memory available was 31.35 GiB. See the [deployment evidence and
screenshots](qa/local-segmentation-2026-10-22/vss-integration.md).

This is on-demand image analysis. RF-DETR remains the existing live detector.
Native Moondream segmentation is still unresolved; the separate SAM mask model
is the alternative authorized by the operator. The earlier no-UI/no-service
statements below describe preceding experiments.

## Previous outcome: a usable local Moondream + SAM 2.1 Tiny path

The operator now permits a separate fast segmentation model. We executed
**stock Photon Moondream 2 point → SAM 2.1 Tiny** on Spark: all three annotated
targets produced masks with 96–98% IoU, and four absent-object controls produced
no points/masks, each repeated twice. This small test establishes a working local
pipeline, not defense inspection accuracy or general absence reliability.
Moondream retains description, detection and pointing; SAM produces the mask.
The native Moondream segment skill remains unresolved. The older Moondream-only
constraint and statements that no separate segmenter exists below are historical.

See the [measured comparison and actual masks](qa/local-segmentation-2026-10-22/README.md)
and [local CLI/Python usage](../tools/segmentation/README.md). No VSS UI model route
or detector was changed; the new pipeline is available as a supervised CLI and
reusable Python API. Keep RF-DETR as the existing live detector. Its boxes can
also prompt the small mask adapter without running a language model each frame;
that specific live integration is not yet measured.

## Earlier diagnosis: upstream H100 test reports the same missing path

Moondream's [merged Photon 2.0 release PR](https://github.com/m87-labs/moondream-python/pull/15) records a supported-H100 segmentation smoke request returning a box without SVG tokens. This is upstream corroboration of the symptom, not proof that every H100 request fails. Publisher-wheel inspection shows that Kestrel 0.9.2 retains the same segmentation skill and checkpoint mapping as 0.9.1. The local quickstart advertises segmentation, while the engine README requires separate weights and the public 3.1 model-card maintainer explicitly removed that skill. The unresolved requirement is an exact, vendor-confirmed segmentation checkpoint/configuration and known-good example. See the [release audit and concrete next requirement](qa/moondream-spark-2026-10-22/advertised-segmentation/README.md). Local segmentation remains unfinished; the evidence no longer supports treating the failure as Spark-specific.

## Latest runtime test: non-Photon comparison completed on Spark

Moondream Preview also runs locally using its official PyTorch forward without Photon or our GB10 adapter. Description and detection controls worked. Switching runtimes **did not fix segmentation**: normal decoding produced zero masks on three positive cases. Experimental SVG-start conditioning produced incomplete worker and broad box-stack masks; the panel exhausted its token budget. The worker case took 7.21 seconds, with 18.40 GiB peak CUDA reservation across the run. This uses BF16 computation from the same cached FP8 weights, not pristine unquantized weights, and a custom diagnostic segment loop because the public reference has no segment API. See the [executed comparison, masks and limitations](qa/moondream-spark-2026-10-22/non-photon/README.md). No VSS capability was promoted.

## Current outcome after testing other Moondream models

**Moondream-only segmentation remains unfinished, but Preview and 3.1 have now emitted real coarse masks on GB10 under experimental decoding.** Normal calls still end after a box. A process-only diagnostic suppressed EOS at exactly the first post-box step; Preview's person/point case then produced an SVG path and stopped naturally. Conditioning that step on the observed SVG boundary token also produced paths for a narrow subset. Visual inspection found partial worker outlines and a box mask that covers a broader stack region. These are not dependable inspection masks. This changes the diagnosis: the public weights can generate paths, and complete absence of that ability cannot be inferred from their normal EOS output. See the [segmentation diagnosis](qa/moondream-spark-2026-10-22/segmentation-diagnosis/README.md).

The final untraced Preview run reproduced the same worker path twice in **12.73 and 12.71 seconds**, a box-region path in **7.52 seconds**, and an empty blank control in **1.16 seconds**. Peak CUDA reservation was **17.35 GiB**, including startup. These are serial test durations including artifact rendering, not camera throughput. The GB10 MoE adapter remains experimental and unoptimized. MD2 produced no valid paths under equivalent conditioning. 3.1 produced coarse paths but also a false near-full-frame mask on the blank image, so it failed the negative control. No segmentation service or VSS feature is promoted from these results.

Public 2, 3 Preview and 3.1 were actually tested on GB10. MD2 image answers/detection run through stock Photon at about 4.45 GiB peak CUDA reserved, but its segment call is disabled; an explicit diagnostic prompt test also emitted no mask. Normal Preview and 3.1 segment calls emitted boxes followed by EOS without path tokens. This rules out the tested token cap, SVG parsing and optional refiner as the cause of those empty paths. Upstream documents separate segmentation weights, but that is not a complete explanation of the newly observed path generation. No other segmentation model is substituted.

See the [complete comparison and reproduction evidence](qa/moondream-spark-2026-10-22/alternate-models/README.md), including checkpoint hashes, timings, raw tokens, memory, access checks and Cosmos recovery. The user's report that MD2/Preview segmentation previously worked is retained; website, cloud and downloadable-checkpoint capabilities cannot be assumed identical. The historical sections below are superseded where they describe work still in progress.

## Follow-up: segmentation checkpoint access and raw output (October 22)

The local segmentation goal remains unfinished. The [Kestrel engine README](https://github.com/m87-labs/kestrel#segment) explicitly says segmentation requires Moondream 3 and **separate model weights**, with access from Moondream. The saved Hugging Face account receives HTTP 403 for both `vikhyatk/moondream-next/seg-model.pt` and `moondream/SegHeadRefiner/model.pt`. No access request was submitted. Compatibility of the gated checkpoint with the present FP8 loader is unverified.

A new raw-engine test of public 3.1 used a metal-panel illustration, a warehouse person frame, and a blank control. Each segment request emitted four tokens (location, size, then EOS); its text token list was `[0]`, its SVG token list was empty, and its finish reason was `stop`. Thus these empty masks were not token-limit truncation or an SVG parse failure. A refiner cannot help: it is only called after a valid coarse path already exists.

Public Preview FP8 was tested separately, pinned to revision `5112966d1a723413b1c9a1e8bea272b72e647b35`, SHA256 `699bd3876f9e105440d60a5fe30c26bc33fbdf008f5bd611a3557663b24bd371`, and returned boxes followed by EOS without paths. Moondream 2's actual runtime template disables segmentation, despite the shared advertised skill list; its diagnostic segment prompt also produced no mask. The user requires Moondream segmentation and explicitly rejected a separate segmenter. Public `moondream/moondream-next/model.safetensors` is byte-identical to public 3.1 and is not a new candidate.

The bounded harness now records raw segment diagnostics, multiple test cases, and fails when masks are empty. `mask_artifacts.py` renders actual SVG paths with the correct bbox-relative transform; boxes alone cannot become masks. Its five CPU tests pass. No mask result or deployment is claimed by these changes.

# Defense models: independent selection review

Research date: 2026-10-22. Scope: the approved site security, drone inspection and vehicle awareness demonstrations for Connect Tech. This is a source-backed engineering recommendation, not a completed model benchmark. The initial review changed no runtime services. The subsequent operator-authorized Moondream deployment experiment and Cosmos stop/restore are recorded below; model budgets and UI remain unchanged.

## Latest result: Photon inference now runs on GB10 with our adapter

The earlier stock-package failure below remains reproducible, but it does **not** describe the final compatibility prototype. User-authorized engineering work added an application-owned MoE runtime through Kestrel's existing layer extension point. No installed vendor package was modified and no GPU identity was spoofed.

**Verified:** Moondream 3.1 loaded on Spark and returned a coherent description and a sensible bounding box for the generated metal-panel demo image. Independent component tests passed: seven CPU checks and GB10 checks at H2048/I1024, four experts/top-two routing, 1/8/64 tokens, with relative L2 error below 0.00067 against a dequantized CPU reference. This is not full-model accuracy qualification or bitwise parity with native W8A8 kernels.

The adapter preserves FP8 weight storage, processes one expert at a time in BF16 with FP32 accumulation, and respects per-channel scales, eight-row gate/up interleaving, residual GELU and routing probabilities. Photon still loads the model and handles requests; other missing SM121 operations use upstream PyTorch fallbacks. It is not optimized or vendor-qualified Photon support. LoRA and CUDA graphs are disabled; batch size is one, cache pages 4096, prefix cache off, native decode selected. Package versions are pinned and the adapter refuses unqualified versions.

| Observed measurement | Result |
| --- | --- |
| Cold load and warm-up | 70.8 seconds on positive-image run |
| Positive-image description | 7.12 seconds |
| Positive-image detection | 1.39 seconds |
| Blank-image description | 3.13 seconds |
| CUDA allocated at idle | 11.87 GiB |
| CUDA reserved during requests | 14.05 GiB |
| Peak CUDA allocation during startup | 17.28 GiB |
| Peak CUDA reservation (second run) | 17.35 GiB |
| Minimum host memory available | 42.36 GiB; saved reserve remained 20 GiB |

**Failed capability controls:** the blank-image query correctly reported no objects, but requesting detection of a metal panel returned a false near-full-frame box. The positive-image segment call returned a box with an empty SVG path. Detection cannot be promoted on this evidence; segmentation is not usable on this tested checkpoint/prompt. Keep RF-DETR as the primary detector. No VSS model or UI feature has been switched to Moondream.

The two images are one generated illustration and one blank negative control, not an inspection benchmark. Timings are single-request observations, not sustained camera throughput. No concurrent Cosmos/Moondream residency is qualified. Hugging Face offline mode prevents model downloads, not all network access: upstream Photon has usage telemetry, so a fully air-gapped claim requires separate network isolation testing.

Cosmos was stopped with user authorization for these bounded runs and restarted afterward. Moondream runs in a supervised process on demand; no HTTP service has been left running. [Reproduction instructions](../tools/moondream/README.md), [structured successful-runtime and failed-capability receipt](qa/moondream-spark-2026-10-22/gb10-compat/result.json), and raw positive/blank test logs are saved.

## Operator decision and Moondream follow-up

The user selected **RF-DETR** for the detector. Do not add PeopleNet for this iteration. The comparisons below are historical research alternatives, not the current implementation plan.

The user requested local Photon inference on DGX Spark, initially with `moondream3-preview`, then identified `moondream3.1-9B-A2B` as the newer target. Segmentation is a required capability to verify, not an assumed feature of either downloadable checkpoint.

- The [3.1 model card](https://huggingface.co/moondream/moondream3.1-9B-A2B) lists query, detect, point and caption. The maintainer explicitly [removed segment from that list](https://huggingface.co/moondream/moondream3.1-9B-A2B/commit/1da27e6c2d2f9118de14560df456881dc62d91f3) on July 8. Treat local 3.1 segmentation as unqualified.
- The [cloud segment API](https://docs.moondream.ai/skills/segment/) lists both 3.1 and 3 Preview. Cloud availability does not establish downloadable weight parity.
- [Photon's August 3 release notes](https://moondream.ai/photon/updates) advertise local Moondream 3 segmentation. Its [current local guide](https://docs.moondream.ai/running-locally/) shows a segment call with 3.1. This conflicts with the checkpoint card and must be resolved by executing the exact pinned checkpoint. The segment marketing FAQ still says cloud-only; do not treat that page alone as current runtime evidence.
- Inspected SDK `moondream==2.6.1` / engine `kestrel==0.9.1`: both Moondream 3 variants share a registry which advertises segment before loading weights. `supports("segment")` alone cannot verify the learned capability. The segment implementation decodes SVG path tokens; optional refinement is separate.
- The refinement implementation references `moondream/SegHeadRefiner/model.pt`. Hugging Face metadata reports a manual access gate, and an anonymous weight request returned HTTP 401 on October 22. Do not bypass this gate or claim cloud-equivalent refined masks from an unrefined path.
- Photon has ARM64 packages and broad Blackwell support, but GB10 SM121 is not explicitly listed in its tested hardware table. Several inspected kernel dispatch lists include SM120 but omit SM121. Actual Spark execution is required before claiming support or speed.

Deployment staging is isolated under `.spark/moondream-photon/`. No app model or sidebar has been changed. Preserve the saved 20 GiB Spark reserve and running guard. The 3.1 checkpoint file is 10,505,269,576 bytes (mixed precision, not a blanket 18 GB BF16 estimate); peak runtime memory is still unmeasured. Two billion active parameters is a compute property, not a total resident-memory figure.

### Spark package probe result

Installed an isolated Python 3.12 environment with `moondream==2.6.1`, `kestrel==0.9.1`, `kestrel-kernels==0.7.4`, `kestrel-native==0.1.8` and `torch==2.13.0` (CUDA 13.0). GPU identification returned NVIDIA GB10, compute capability 12.1. A tiny CUDA matrix multiplication passed. Photon imported and registered both Moondream 3 variants. An RMSNorm call returned finite values **using a warned PyTorch fallback**, so this does not verify native Photon acceleration or whole-model inference. No model weights were loaded by the probe.

Probe: `tools/moondream/probe.py`. Raw results: `.spark/moondream-photon/probe.json` and `probe.stderr`. Installed dependency lock: `.spark/moondream-photon/requirements.lock.txt`. The user subsequently authorized stopping Cosmos for memory measurement. Cosmos was stopped for the bounded test and restarted afterward; the Spark guard stayed active. See the failed warm-up result below.

### Full-model Spark result: blocked at FP8 MoE warm-up

The exact 3.1 checkpoint was downloaded and its SHA256 verified. A local attempt with batch size 1, 4096 cache pages, graphs disabled, prefix caching disabled and Hugging Face offline mode reached GPU warm-up, then failed with:

> FP8 MoE is not supported by the padded compatibility runtime; CUDA FP8 requires a tuned compact or warpgemv CuTe config.

GPU usage was observed at **14,458 MiB (14.12 GiB)** during startup; this was one sample, not a measured maximum. Host MemAvailable fell from 60.46 to a minimum of 41.76 GiB (18.70 GiB decrease across concurrent system activity). The 20 GiB reserve was preserved. There is **no successful idle, inference, latency or segmentation result**. Do not present these numbers as a qualified working model footprint. Spark uses shared CPU/GPU memory; the host decrease includes more than model GPU tensors.

Newer `kestrel==0.9.2` / `kestrel-kernels==0.7.5` wheels were inspected separately, not installed over the SDK-pinned versions. No GB10/SM121 config was found in their Python/JSON sources. Do not claim those versions were tested, that all possible Photon builds fail, or that architecture spoofing is a verified remedy. A supported GB10 FP8 kernel/config path or a separately qualified alternative runtime/checkpoint is needed. Thor has a vendor-listed Photon path but has not been tested here.

A first launch failed because resolving the Hugging Face snapshot symlink removed the `.safetensors` suffix; Photon then selected the wrong weight loader. The launcher now preserves the snapshot filename. That local path issue was corrected before the above FP8 failure.

[Saved execution receipts](qa/moondream-spark-2026-10-22/result.json) and `tools/moondream/measure.py` make the test reproducible. No Moondream service is running or wired into VSS. RF-DETR remains unchanged.

### Follow-up: the failed Photon test does not rule out Spark

The installed `kestrel/models/moondream/weights.py` explicitly rejects non-FP8 MoE checkpoints for MD3 because its expert layout requires FP8 scales and interleaved gate/up weights. Merely setting `dtype=bfloat16` or dequantizing the downloaded checkpoint is **not** a supported Photon workaround in this release.

Two distinct avenues remain untested:

1. Add and validate actual GB10/SM121 MoE kernel/config support in Photon, retaining the requested 3.1 model. This is runtime engineering, not an established configuration switch. The [upstream engine](https://github.com/m87-labs/kestrel) lists SM120 but not SM121 among optimized targets.
2. Use the vendor's [Moondream 3 Preview BF16 Transformers implementation](https://huggingface.co/moondream/moondream3-preview), which avoids Photon's particular FP8 runtime. This changes both model version and runtime; it is not evidence that 3.1 or segmentation works on Spark. Its published skills are query, caption, point and detect. Spark latency and memory need separate measurement.

No additional GPU test or VSS service change was made for this follow-up. Segmentation checkpoint availability remains a separate question from GPU execution compatibility.

## Original review decision

The previous implementation plan leaned too heavily on what Smart City already runs. Reusing ingestion, recording, exact-frame overlays and evidence storage remains sensible. Reusing the same trained weights for all three stories does not.

Build three separately qualified perception profiles. Select by sensor modality, object size, viewpoint, temporal behaviour and output requirements. A military-looking environment does not make COCO performance evidence of performance in that environment.

| Story | Recommended first evaluation | Independent alternative | Observable result |
| --- | --- | --- | --- |
| Site boundary entry, RGB fixed camera | Existing RF-DETR Medium as a baseline, adapted to actual site footage; NvDCF and explicit zone rules | NVIDIA PeopleNet Transformer v2 for the person-only task | Entry event, local track, exact clip and acknowledgement |
| Site/vehicle operation in darkness | A separately trained thermal detector, evaluated on actual thermal imagery | Teledyne FLIR Prism AI / Prism AI Auto vendor evaluation | Thermal evidence and alerts with sensor identity and health |
| Drone apron inspection | Custom debris-trained RF-DETR plus full-resolution tiled inference; compare custom-trained RT-DETRv4 | EfficientAD/PatchCore as an additional anomaly proposal path, only if scene variability permits | Small-object candidate, close-view evidence, optional mask and unresolved/confirmed review state |
| Vehicle surroundings | Person/object detector plus calibrated stereo depth using Isaac ROS ESS/Light ESS | Commercial FoundationStereo for slower depth review; C-Fast-FoundationStereo is conditional on resolving published terms | Camera view plus measured depth where valid, with unknown regions preserved |
| Select an unfamiliar inspection object | Grounding DINO Swin-T on demand, followed by SAM 2.1 Tiny/Small when a mask helps | Custom segmentation head for frequently used classes | Prompt-to-candidate box, operator-selected mask and evidence crop |
| Explain and report | Existing Cosmos3 Nano endpoint as baseline; evaluate Cosmos3-Edge 4B | Qwen3-VL-4B-Instruct as a second compact comparison | Short evidence-linked answer, not the real-time detection loop |

These are evaluation priorities, not declarations that a new candidate is faster or more accurate on the Anvil-T5. Keep RGB-only booth scope if suitable thermal data or hardware is unavailable.

## 1. Site security: specialize the domain before changing the backbone

[PeopleNet Transformer v2's model card](https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/peoplenet_transformer_v2/trainable_v1.0) describes person, face and bag detection, with a DINO/FAN-Small architecture. It also warns about dark/IR imagery, moving cameras, fisheye distortion and very small objects. This makes it a credible fixed-RGB-camera challenger, not a universal Defense upgrade. Its face/bag quality is not equivalent to its person quality.

**Decision:** compare it against the current RF-DETR using the exact intended view. Test distant people, protective clothing, partial visibility, glare, shadows and person-sized negative objects. Fine-tune the winner if needed. Include a lower-cost model only when it preserves event recall at the required stream count. Keep NvDCF as the local tracker until tests identify a failure that another tracker solves.

An entry detector needs a policy boundary and track history. It cannot determine permission from a uniform or appearance. If the demo must distinguish authorized entry, integrate a gate/access event and time-scoped rule. The UI should say "person entered zone" unless that additional evidence exists.

For optional cross-camera handoff, NVIDIA's [Re-Identification Transformer](https://catalog.ngc.nvidia.com/orgs/nvidia/tao/models/reidentificationnet_transformer/) supplies appearance embeddings. This is a separate evaluation: similar uniforms and occlusion can confuse association. Do not equate an embedding match with a verified identity. Add synchronized camera geometry and retain uncertainty before showing a global track.

## 2. Thermal: a meaningful new branch, not a colour filter

[Teledyne FLIR Prism AI](https://oem.flir.com/products/prism-ai/?model=110-0200-20&segment=oem&vertical=ai) offers thermal/visible detection and tracking with application-specific models. Its public hardware list explicitly names Xavier and Orin; other hardware is on request. This is a relevant vendor route for perimeter awareness. [Prism AI Auto](https://oem.flir.com/en-gb/products/prism-ai-auto/?model=110-0133-40&segment=oem&vertical=ai) adds a driver-perception route and visible/thermal fusion. These are vendor capability claims, not our performance measurements.

**Decision:** shortlist Prism for a possible Connect Tech hardware/software partner demonstration. Before scheduling it, establish Thor/BSP support, access to a local SDK, offline inference behaviour, exact model classes, camera formats, commercial demonstration rights and concurrent memory use. No contact or purchase was made.

The self-managed alternative is thermal-domain training. The [FLIR ADAS dataset](https://oem.flir.com/en-150/solutions/automotive/adas-dataset-form/) includes labelled thermal and RGB frames, including paired video and raw thermal formats. It is an automotive starting point, not a complete test for elevated perimeter cameras. Check the downloaded dataset terms independently of its "free" description.

A grayscale or false-colour version of a Gaussian RGB rendering does not reproduce thermal radiation. It cannot validate a thermal detector. Use rights-cleared real thermal replay, an appropriate camera, or a separately validated thermal simulator. Keep sensor timestamps and registration explicit if fusing RGB and thermal. Thermal sensing also has limits; do not promise visibility through every obstruction or weather condition.

## 3. Drone: object scale and inspection data are the central decisions

The [FOD-A paper](https://arxiv.org/abs/2110.03072) supplies an airfield-specific starting point with 31 debris categories and lighting/weather annotations. The [authors' repository](https://github.com/FOD-UNOmaha/FOD-data) currently links 300×300 and 400×400 versions. These are useful object/background examples, not proof of detection from our eventual drone altitude. Its repository has an MIT licence; confirm the downloaded image bundle's applicable terms before commercial redistribution.

**Recommended primary path:** custom-trained RF-DETR, with [RT-DETRv4](https://github.com/RT-DETRs/RT-DETRv4) as an independent detector comparison. RF-DETR remains a candidate because the deployed inference path is understood, not because road-user weights detect arbitrary debris. The local [challenger record](../tools/smart-city/CHALLENGERS.md) says RT-DETRv4 weights were previously unavailable through the approved download route; it is still an untested candidate here.

Use [SAHI](https://github.com/obss/sahi) to prototype overlapping tiled inference on high-resolution stills. It supports slicing, detection merging and evaluation; it is not another detector. Compare full-frame and tiled processing under the same latency budget. If tiles win, implement a bounded crop/batch/merge stage for the deployed TensorRT pipeline. Preserve original pixel coordinates and avoid duplicate findings across tile boundaries.

Illustrative engineering calculation: a 12-pixel-wide object in a 3840-pixel image becomes about 1.8 pixels wide after resizing that full image to 576 pixels. Changing detector brands does not recover information discarded by resizing. Camera geometry, capture sharpness, object size and tile scale must be chosen together.

**Masks:** use [SAM 2.1 Tiny/Small](https://github.com/facebookresearch/sam2) on a selected candidate when outlining its shape improves review. The repository publishes checkpoints and an Apache-2.0 licence. A mask identifies pixels; it does not establish the object's material, dimensions or hazard. Do not propagate a video mask across two unrelated viewpoints and assume the object association is solved.

**Unknown objects:** evaluate [EfficientAD](https://arxiv.org/abs/2303.14535) and [PatchCore](https://arxiv.org/abs/2106.08265) through [Anomalib](https://github.com/open-edge-platform/anomalib). Their anomaly-learning approach is relevant to departures from normal appearance. Outdoor shadows, wet pavement and viewpoint changes may dominate those departures; that limitation is an engineering inference to test, not a published apron result. Use an anomaly heatmap to propose a review, not to certify an aircraft operating area. Jetson export and memory behaviour require actual qualification; an Anomalib/OpenVINO example is not a TensorRT deployment receipt.

## 4. Vehicle: depth is the substantive addition

[Isaac ROS stereo-depth documentation](https://nvidia-isaac-ros.github.io/v/release-4.6/repositories_and_packages/isaac_ros_dnn_stereo_depth/index.html) provides ESS/Light ESS and FoundationStereo options. ESS supplies disparity and confidence; FoundationStereo prioritizes depth quality with a heavier compute cost. Both need properly calibrated stereo input to obtain metric depth. The documented platform matrix includes Thor and Spark, but that does not qualify our installed runtime or simultaneous VSS load.

**Decision:** evaluate ESS/Light ESS first for the continuous vehicle view. Filter unreliable depth and show unknown space. Associate a person's image region with valid depth rather than putting a guessed distance beside every box. Evaluate near-field error, temporal stability and boundary behaviour under glare, low texture and motion. Use simulator depth only as evaluation truth, unless the UI explicitly says it is a simulated depth sensor.

There is a material documentation conflict around the fast alternative. The [Fast-FoundationStereo repository](https://github.com/NVlabs/Fast-FoundationStereo) now links a commercial C-Fast variant and TAO code. The [C-Fast model card](https://huggingface.co/nvidia/c-fast-foundationstereo) names the NVIDIA Open Model Agreement but also retains research/evaluation-only wording. The Isaac ROS page describes the research Fast variant as non-commercial. Treat these as distinct artifacts and resolve the exact code/checkpoint terms before product selection. Do not silently use research weights in a commercial booth stack.

Add cuVSLAM/nvblox only if accumulated 3D mapping is part of the story. A per-frame depth warning does not require a full mapping stack. Multiple independent monocular cameras also do not automatically form calibrated stereo pairs.

## 5. On-demand visual tools and answers

[Grounding DINO](https://github.com/IDEA-Research/GroundingDINO) publishes local weights and prompt-based object detection. Test it on selected stills for requests such as locating a loose panel. It is an on-demand proposal/annotation tool here, not a replacement for the continuous event detector. Its ability to accept a phrase does not guarantee reliable recognition of that phrase. By contrast, the reviewed [DINO-X API repository](https://github.com/IDEA-Research/DINO-X-API) supplies examples for a hosted service; that alone does not provide an offline model suitable for this booth.

Do not automatically choose SAM 3 because it is newer. Its [custom licence](https://github.com/facebookresearch/sam3/blob/main/LICENSE) contains ITAR and trade-control end-use language that explicitly mentions military/warfare purposes. This warrants review of the exact proposed use; it is not a blanket legal conclusion about every Defense demonstration. SAM 2.1 is the lower-friction candidate for the limited mask task in this shortlist.

For answers, compare our installed Cosmos3 Nano with the **reasoner** path of [Cosmos3-Edge 4B](https://huggingface.co/nvidia/Cosmos3-Edge). Its card lists image/video understanding, Thor/Spark test hardware and BF16 as the officially tested precision. Do not assume our Nano NVFP4 serving recipe transfers. [Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct) is a second compact local candidate, subject to the customer's component-origin requirements. Neither is a specialized military checkpoint.

Evaluate factual support, source citations, abstention, temporal ordering, response time and concurrent memory use on the same clips. Avoid ranking by fluent prose alone. Keep immediate alerts in the detector/rule path and answers in a separate bounded request queue. Current local Nano receipts already document counting and description errors; see [as-built evidence](smart-city-as-built.md).

## Controlled selection experiment

This review changes the shortlist; it does not justify an unmeasured model switch. Use the following experiment before declaring winners:

1. Define one required outcome per story: boundary-entry event, visible debris finding, or person/obstacle near a vehicle. Define the sensor, smallest object and acceptable delay before selecting resolution.
2. Make a fixed training/validation/test manifest. Split by scene, capture session and object instance where appropriate; do not leak adjacent video frames into the test set. Keep public data, synthetic data and real target-camera results separate.
3. Compare a small number of candidates on identical data and thresholds selected only on validation. Record recall at a fixed false-alarm burden, event delay, missed small objects, track switches and unknown outputs. Add distance error for depth and unsupported statements for VLMs.
4. Run the actual exported engine on Anvil-T5. Include decode, resize/tiles, tracker, depth, display and concurrent questions in timing and memory measurements. Keep the saved 10 GiB Thor reserve and separate 20 GiB Spark reserve. Published A100/3090/Thor component numbers are not our combined booth result.
5. Preserve model/checkpoint hashes, code and weight terms, calibration, data manifest and exported engine receipt. Promote only a profile that meets the agreed task criteria. Maintain separate profiles for site RGB, thermal, drone inspection and vehicle depth.

## Consequences for the UI and demo

- Site: sensor choice and evidence quality matter more than adding extra boxes. Show a boundary event and the exact evidence; keep authorization unknown unless supplied by another system.
- Drone: add a close-up inspection step, a selected-object outline and a distinct review state. Show captured, reviewable and unresolved areas separately. Do not equate capture coverage with clearance.
- Vehicle: add a depth layer with valid/unknown regions when the stereo pipeline is ready. Add RGB/thermal comparison only with authentic modality data. Keep the operator's camera view primary.
- Shared: expose processing location, source age and model/profile identity in an evidence/details view. Demonstrate offline operation by testing loss of the external connection while local capture and inference continue; preserve the local camera network.

**Recommended commitment now:** retain shared VSS plumbing; create distinct task profiles; prioritize custom debris detection plus tiling and vehicle stereo depth; evaluate PeopleNet rather than assuming it wins; investigate Prism as a thermal partner option; compare a compact local reasoner without replacing the working Nano service yet.
