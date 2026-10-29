> October 28 operator update: Spark uses its saved **5 GiB** reserve, with no additional startup allowance. Historical reserve/startup values below are superseded.

# Local segmentation evaluation

## Resident VSS service on Spark

The shared Defense and Smart City inspector uses a separate host service, `vss-spark-local-vision.service`, backed by the same staged Photon virtual environment. It fixes the model pair to Moondream2 + SAM 2.1 Tiny, warms both models once, and reuses them for subsequent requests. It listens only on `127.0.0.1:8026`; the Next.js server proxies authenticated requests. This does not replace Cosmos or change its settings.

Open **Local vision** in either workspace. Upload an image, or use a displayed camera image when that option is available. Choose **Segment**, **Detect**, **Point**, or **Describe**; provide an object prompt for the first three. Segmentation uses actual Moondream points followed by SAM 2.1 Tiny, with at most three returned objects. Teal shows the predicted mask; amber shows the model's point or box. An empty result does not establish that a scene is clear. This inspector processes one requested image at a time; it is not a continuous camera-analysis rule.

The resident profile explicitly fits the longest image side to **1024 pixels** and preserves aspect ratio. The browser prepares uploaded/displayed images before submission. The service independently accepts only PNG/JPEG/WebP bytes up to 2 MiB and 16 megapixels, applies EXIF orientation, then fits the image if needed. Its receipt records the oriented input and inference dimensions. Only one request enters GPU inference; a concurrent request receives HTTP 429. `/ready` remains unavailable until both models complete warmup.

Select automatic VSS startup with the Spark renderer's `--local-vision` flag. Omitted flags preserve `local_vision_enabled`; `--no-local-vision` deselects it. For an already rendered installation, this narrow configuration command changes only the saved selection and the private UI connection values:

```bash
python3 tools/spark/local_vision.py select --enabled
```

That command does not start or stop services. `tools/spark/bootstrap.py up` and the desktop **Start VSS** flow start the selected worker and wait for both models to be ready. A warm desktop start does this independently of existing model health; it does not cold-restart healthy models merely because the new worker is missing. If the UI's private connection values changed, only the UI is recreated. The worker has no login target and is not enabled for automatic login startup. VSS stop/down and desktop shutdown stop it, including when Docker shutdown fails.

The service token lives in `.spark/local-segmentation/service-token` with mode 0600. Only server-side `LOCAL_VISION_API_URL` and `LOCAL_VISION_API_TOKEN` are placed in the private 0600 Compose file. No `NEXT_PUBLIC_` token is used. The browser calls `/api/vision/local-model`; that server route supplies the private `X-VSS-Model-Token` header to `/infer`. The host service exposes cheap `/health` and `/ready` checks. `/infer` accepts image bytes and supported task options, never caller-provided file paths, model paths or URLs. Returned masks are actual binary PNGs; full runtime manifests and local checkpoint paths are omitted from browser responses.

The fixed resident service has a separate admission policy from the general diagnostic CLI below: saved reserve **at least 20 GiB + 12 GiB startup headroom**, then a reserve + 3 GiB watchdog. It keeps the active Spark user guard, stops if the guard exits, uses `Restart=no`, and has a 16 GiB service memory ceiling with no swap. The main guard also stops this host service during a low-memory trip independently of Compose, Docker enumeration and telemetry disk writes. The standalone CLI still requires **reserve + 30 GiB**: 50 GiB available with a 20 GiB reserve. Its admission is not changed by selecting the resident service. Concurrent-workload qualification is recorded separately from configuration and unit readiness.

```bash
python3 tools/spark/test_local_vision.py
python3 tools/spark/test_desktop.py
python3 tools/spark/test_bootstrap.py
```

## Local command-line inference

The recommended local configuration is **stock Moondream2 point grounding → SAM 2.1 Tiny**, with the optional presence query off. These are the CLI defaults. This provides a separate mask model; it **does not fix or call Moondream's unresolved native `segment` skill**. Model files and their source trees must already be staged locally in `.spark/moondream-photon` and `.spark/local-segmentation`; this command does not download them. Use the existing Photon virtual environment.

```bash
.spark/moondream-photon/venv/bin/python tools/segmentation/run.py \
  --task segment \
  --image /absolute/path/image.jpg \
  --object "person" \
  --model moondream2 \
  --segmenter sam2.1-tiny \
  --grounded-by point \
  --presence off \
  --output-dir /absolute/path/new-person-result
```

The command saves each binary `mask-000.png`, a teal overlay for each mask, a combined `overlay.png`, and an amber `grounding.png` showing the actual predicted boxes or points. `call-000/result.json` keeps the raw Moondream output, the prompts passed to the mask model, mask metadata, checkpoint/runtime receipts and per-stage times. No detections means no mask files; the overview is the unchanged source image. A normal exit does not imply correct detections or masks. Ground-truth accuracy is not calculated by this command.

`--segmenter edgetam` selects the other staged mask model in a fresh process. The default `--grounded-by point` uses actual Moondream positive-point predictions; `--grounded-by detect` uses predicted boxes. The adapter selects a point mask with its own predicted quality score; ground truth is never used to pick an output. `--presence query` adds a real Moondream yes/no query before grounding: only an exact affirmative answer proceeds. This is an optional filter, not calibrated absence detection. Its time and actual answer are saved. Up to three valid grounded objects are segmented; use `--max-objects 1` to lower this cap. The full raw grounding output remains in the receipt.

The completed Spark run `20261022T175936Z-bridge-moondream2-sam2.1-tiny` made 40 segmentation calls across ten cases, two presence modes and two repetitions. With presence off, the three annotated targets had mask IoU of 96.8% (person), 97.8% (cat) and 96.3% (airplane). All four negative cases returned no points and no masks on both repetitions without an extra presence query. These are a small diagnostic sample, not general accuracy or defense-scene qualification. Actual point-to-mask calls on the annotated images took approximately 0.5–0.9 seconds after model loading, including Moondream grounding; the first mask call also had startup overhead. The complete receipt is in [the local run](../../.spark/local-segmentation/runs/20261022T175936Z-bridge-moondream2-sam2.1-tiny/inference.jsonl).

The mask stage alone can be around 40 ms on the tested smaller images once a point or box is available. This excludes the time required to find the object. A future RF-DETR-to-mask integration could supply detector boxes directly, but that complete integration has not been measured here. The current text-to-mask CLI includes the actual Moondream grounding time and does not advertise the mask-stage latency as total latency.

The same CLI also supports Moondream's other local tasks; these do not load the mask model:

```bash
.spark/moondream-photon/venv/bin/python tools/segmentation/run.py \
  --task detect --image /absolute/path/image.jpg --object "vehicle" \
  --output-dir /absolute/path/new-detections

.spark/moondream-photon/venv/bin/python tools/segmentation/run.py \
  --task point --image /absolute/path/image.jpg --object "metal panel" \
  --output-dir /absolute/path/new-points

.spark/moondream-photon/venv/bin/python tools/segmentation/run.py \
  --task describe --image /absolute/path/image.jpg \
  --output-dir /absolute/path/new-description
```

`--model moondream3-preview --gb10-compat` or `--model moondream3.1-9B-A2B --gb10-compat` explicitly selects the experimental application-owned GB10 compatibility path. Moondream2 uses stock Photon and must omit `--gb10-compat`. These choices do not qualify the Moondream3 compatibility path for production.

Every invocation launches one supervised subprocess. With `--repeat 3`, that child makes three serial calls with one resident bridge; it does not reload models between calls. This is useful for separating the first call from subsequent reuse, not for measuring sustained streaming throughput. The first call includes lazy model loading. Each call records `model_load_ms`, the original stage timings, and `call_excluding_model_load_ms`; a later call can still include a segmenter load if earlier calls found no object. The top-level `result.json` lists all calls. `exit.json` measures the complete child lifetime, including process startup and artifact output. Loading, inference and overlay writing must not be presented as the same latency measurement. No HTTP service or VSS integration is started.

Admission requires the active **user** `vss-spark-guard.service`, a saved reserve of at least 20 GiB, and 30 GiB available above that reserve. The supervisor stops only its child if available memory falls below reserve + 3 GiB, the guard stops, or the default 600-second timeout expires. Higher saved reserves are honored, including increases during the run. Use `--timeout` to set a bounded lifetime of 1–3600 seconds. The CLI does not stop other services, lower reserves or change model budgets. It sets offline model-library flags and the staged environment's CUDA library paths. Existing nonempty output directories are refused.

The earlier standalone CLI tests temporarily stopped Cosmos because approximately 38 GiB available did not satisfy this 50 GiB admission rule. Keep that CLI rule unchanged. The resident 1024-pixel Moondream2/SAM2 service above is a separate runtime profile with its own startup and concurrent-workload checks.

Inputs are local images up to 16 megapixels. The original decoded pixel orientation is used without implicit EXIF rotation or resizing. Model-returned nonfinite coordinates, if rejected by the bridge, are preserved in JSON as explicit `{"nonfinite_float": "nan"}`/`"inf"` records rather than invalid JSON numbers.

```bash
CUDA_VISIBLE_DEVICES='' .spark/moondream-photon/venv/bin/python -m unittest tools.segmentation.test_run -v
```

## Existing Spark setup and pinned artifacts

This is the tested installation on this ARM64 DGX Spark, not a portable installer or a Thor qualification. Run commands from `/home/sparkdev/vss` with `.spark/moondream-photon/venv/bin/python`. The environment contains Python 3.12.3, Moondream 2.6.1, Kestrel 0.9.1, Kestrel kernels 0.7.4, PyTorch 2.13.0, torchvision 0.28.0, NumPy 2.5.4, Pillow 13.0.0, Hydra 1.3.2, OmegaConf 2.3.1, iopath 0.1.10 and timm 1.0.15. The supervisor sets this virtual environment's NVIDIA/NVPL library paths before loading Photon. Do not replace the tested wheels with unpinned upgrades as a setup step.

To use or restore the staged installation:

1. Preserve `.spark/settings.json` and the active user memory guard.
2. Keep the local Moondream2 checkpoint pointer `.spark/moondream-photon/md2-model-path.txt` and `tokenizer-path.txt` pointing to existing files. The tested Moondream2 checkpoint is `vikhyatk/moondream2`, revision `5d6c926f44e26b07957b0dd315bbedcb4c17a5fe`, `model.safetensors`. Preserve the snapshot filename extension rather than rewriting the pointer to an extensionless cache blob.
3. Use `.spark/local-segmentation/manifest.json` as the record of mask-model source files, revisions, checkpoint locations and SHA-256 values. The adapter verifies the staged source files and checkpoint against this manifest before load. SAM 2.1 Tiny uses source revision `2b90b9f5ceec907a1c18123530e92e794ad901a4` and checkpoint revision `de431c4043854a71d8101e17995dfe596bf101a5`; its checkpoint SHA-256 is `7402e0d864fa82708a20fbd15bc84245c2f26dff0eb43a4b5b93452deb34be69`.
4. Run the CPU tests, then use the guarded CLI above with a new output directory. Missing staged files cause an error; the command does not fetch replacements. Each mask-model family needs a fresh process because both official source trees use the `sam2` Python namespace.

For application integration inside an equivalent guarded worker, reuse the bridge and select point grounding explicitly. The bridge's low-level default remains box grounding for API compatibility; the CLI selects point grounding:

```python
from PIL import Image
from tools.segmentation.moondream_bridge import MoondreamBridge

image = Image.open("/absolute/path/image.jpg").convert("RGB")
with MoondreamBridge(model="moondream2", segmenter_name="sam2.1-tiny",
                     presence_mode="off", max_objects=3) as bridge:
    result = bridge.segment(image, "person", grounded_by="point")
    # result["objects"] contains the actual points and full-image Boolean masks.
    # Reuse this bridge for subsequent calls; preserve the supervisor and guard.
```

## Mask evaluation and fixtures

`evaluate.py` uses NumPy and Pillow only. It does not load a model, initialize CUDA, contact a service or download data. The existing Moondream Photon virtual environment has both dependencies.

Prepared fixtures are in `/home/sparkdev/vss/.spark/local-segmentation/fixtures/fixtures.json`. This is a list of cases with absolute `image` and optional `gt_mask` paths, an `expression`, and `oracle_box`/`oracle_point` in normalized coordinates. Oracle boxes come from the decoded target mask; they are not the dataset's older COCO annotation boxes. The adjacent provenance file records the dataset revision, HTTP response hashes and the bounded download ledger.

The three annotated RefCOCO-M cases are `person on left`, `real cat`, and `plane in front`, from revision `45686f0eb7980ed4b70d3d5480a198775a26b4c1`. The public dataset supplies the masks; these were not manually drawn for this test. There is one uniform-white synthetic negative with an empty mask. Warehouse person, warehouse box and metal-panel images have no ground truth and must not receive an IoU score. Three chosen images are a diagnostic sample, not a representative accuracy benchmark.

## Prompt provenance

Keep each regime separate:

- `oracle_ground_truth`: point or box derived from the true target mask. This measures segmentation given correct localization.
- `moondream_predicted`: the actual point or box returned by Moondream. Save that output and include its latency when reporting the whole pipeline.
- `manual`: a user-supplied point/box. Existing warehouse/panel hints use this label.
- `none`: no localization prompt. A promptable segmenter may not support this mode.

Do not select the best of several returned masks using ground truth. Use the model's own quality score or a predetermined output index and record that choice. Report box, positive point, and positive-plus-negative point runs separately. A foreground prompt on a blank image is a deliberate incorrect-prompt test; omitting the prompt is not an equivalent absence test.

`oracle_prompts_from_mask(mask)` returns both normalized and pixel coordinates, with one positive point guaranteed inside the target and a negative point outside it. A negative point can be on a different object. Points use pixel centres; boxes use exclusive maximum corners. The oracle record explicitly marks `end_to_end: false`.

## Python API

```python
from tools.segmentation.evaluate import evaluate_mask, load_mask, save_overlay

prediction = load_mask("prediction.png")
gt = load_mask(case["gt_mask"]) if case["gt_mask"] else None
scores = evaluate_mask(prediction, gt, prompt_source="oracle_ground_truth")
save_overlay(case["image"], prediction, "overlay.png", gt)
```

Binary masks must have the original image dimensions. The evaluator deliberately refuses implicit resizing. It accepts Boolean arrays, integer masks containing only 0/1 or 0/255, and floating probabilities in [0,1]. Convert logits explicitly in the model harness. Probability threshold defaults to 0.5; binary PNG masks retain their binary values.

Overlays show true positives in green, false positives in orange, and missed ground truth in blue. Without ground truth, the prediction is teal. Optional `points_xy_pixels` and `point_labels` draw the actual prompts. Overlay generation and file writes belong outside inference-only latency measurements.

```bash
CUDA_VISIBLE_DEVICES='' .spark/moondream-photon/venv/bin/python -m unittest tools.segmentation.test_evaluate -v

CUDA_VISIBLE_DEVICES='' .spark/moondream-photon/venv/bin/python tools/segmentation/evaluate.py \
  --prediction /absolute/path/prediction.png \
  --ground-truth /absolute/path/target.gt.png \
  --prompt-source oracle_ground_truth \
  --image /absolute/path/image.jpg \
  --overlay /absolute/path/overlay.png \
  --output /absolute/path/scores.json
```

The empty/empty IoU convention is 1.0; also inspect `negative_image_false_positive_fraction`. Prompt consistency is not an accuracy metric. `end_to_end_validated` remains false in this low-level scorer because it cannot verify how a model produced its prompt or prediction.

Format references: [COCO RLE implementation](https://github.com/cocodataset/cocoapi/blob/master/common/maskApi.c), [RefCOCO-M dataset card](https://huggingface.co/datasets/moondream/refcoco-m/tree/45686f0eb7980ed4b70d3d5480a198775a26b4c1).
