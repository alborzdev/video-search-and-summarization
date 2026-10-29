# Moondream Photon on Spark: native segmentation diagnosis

**Latest usable path:** the user now permits a separate fast mask model. Stock
Photon Moondream 2 pointing plus SAM 2.1 Tiny has been tested locally on Spark.
Use the [segmentation CLI and Python API](../segmentation/README.md) and consult
the [actual quality/latency results](../../docs/qa/local-segmentation-2026-10-22/README.md).
The native Moondream segment skill itself remains unresolved. Moondream-only
requirements and no-alternative statements in the historical tests below have
been superseded by the user's latest instruction.

**Upstream corroboration:** the maintainer's Photon 2.0 release test reports the
same box-without-SVG symptom on H100. Kestrel 0.9.2 retains 0.9.1's segmentation
skill and checkpoint mapping. Official local instructions conflict with separate
weight requirements and public model-card capabilities. See the
[release/entrypoint audit](../../docs/qa/moondream-spark-2026-10-22/advertised-segmentation/README.md)
before assuming another runtime upgrade supplies working segmentation.

**Non-Photon comparison:** `measure_reference.py` now runs the pinned official
Preview PyTorch forward directly on GB10, with independently loaded BF16 weights
dequantized from the cached FP8 checkpoint. Query/detection controls work, but
normal segmentation still produced 0/3 masks. Explicit SVG-start conditioning
produced two incomplete/coarse masks; no usable segmentation was established.
The worker case took 7.21 s and peak CUDA reservation was 18.40 GiB. The reference
has no public segment API, so `reference_decode.py` is a diagnostic extension.
See [results, limitations and reproduction](../../docs/qa/moondream-spark-2026-10-22/non-photon/README.md).

**Continuation diagnostic:** public Preview produced a real coarse SVG mask for
the person/point case when EOS was suppressed at exactly the first post-box step.
The outline is incomplete and not quality validated. Normal calls still end
after a box. This is evidence of latent path generation, not a completed
segmentation deployment. See the [new trace and diagnosis](../../docs/qa/moondream-spark-2026-10-22/segmentation-diagnosis/README.md).

The final untraced Preview repeat produced the identical worker path twice at
12.73/12.71 seconds, and a box-region path at 7.52 seconds; the blank stayed empty.
Peak CUDA reservation was 17.35 GiB including startup. These serial durations
include mask artifact rendering. Quality remains visibly limited. Equivalent
3.1 conditioning also generated paths, but falsely masked the blank image;
MD2 produced no valid path. Keep these diagnostics separate from a qualified
segmentation service.

The bounded baseline tests cover Moondream 2, 3 Preview and 3.1 on the actual GB10.
Moondream 2 runs through stock Photon using its vendor PyTorch kernel fallbacks;
3 Preview and 3.1 require our MoE compatibility adapter. None of the tested
public checkpoints produced a usable segmentation mask under normal decoding. This is not a completed
segmentation deployment. The user requires Moondream only; no other segmentation
model is integrated or running.

See the [alternative-model test report](../../docs/qa/moondream-spark-2026-10-22/alternate-models/README.md).
Moondream 2 used 4.45 GiB peak CUDA-reserved memory, with positive-image detection
at 0.48–0.99 seconds and answers at 1.90–2.05 seconds. Its blank-image detector
returned a false full-frame box. Preview's detector passed that blank control,
but segmentation returned only boxes followed by EOS on both positive images.
The engine documents separate segmentation weights; the saved account cannot
currently download the known gated artifacts. That does not establish that the
user's prior working Moondream setup lacked the skill.

2026-10-22: Moondream 3.1 query and detection execute on GB10 through Photon
with our opt-in PyTorch MoE adapter. The stock installation still fails FP8 MoE
warm-up. This is **not** vendor-qualified or optimized Photon support.
The blank-image query correctly reported no visible objects, but detection
returned a false full-frame box. RF-DETR remains the selected detector.
Segmentation returned a bounding box but an empty SVG path on the test image;
do not enable a segmentation feature based on the advertised runtime skill list.

See [research and results](../../docs/defense-model-research-2026-10-22.md)
and [compatibility receipts](../../docs/qa/moondream-spark-2026-10-22/gb10-compat/).
The isolated environment, downloaded weights and package audit files live
under `.spark/moondream-photon/`; these are ignored local artifacts. Installed
package versions are pinned in the parent execution receipt. No installed
vendor package is edited and no GPU identity is overridden.

## Run the bounded image test

From the VSS repository, after arranging workload headroom:

```sh
.spark/moondream-photon/venv/bin/python tools/moondream/measure.py --compat --tasks query,detect
```

Model comparison (cached files are selected by model name):

```sh
.spark/moondream-photon/venv/bin/python tools/moondream/measure.py --model moondream2 --tasks query,detect
.spark/moondream-photon/venv/bin/python tools/moondream/measure.py --model moondream3-preview --compat --tasks query,detect,segment --cases .spark/moondream-photon/segment-cases.json
```

The second command is an expected segmentation failure with the tested public
checkpoint. `--model-path` accepts an explicitly supplied matching checkpoint.
Case lists contain `id`, `image`, `object`, and optionally `prompt` and
`expect_present` (false for negative controls). Raw engine results retain path
tokens, EOS/length reason and parsing errors. `mask_artifacts.py` records actual
renderable SVG masks; it does not substitute bounding boxes.

`--probe-md2-segment` is an unsupported diagnostic that tests the shared
tokenizer's MD3 segment prompt against MD2 weights. It changes only the test
process configuration, not installed files. This test also produced boxes and
EOS without paths; it is not a deployment option.

To use another local image:

```sh
.spark/moondream-photon/venv/bin/python tools/moondream/measure.py --compat --tasks query,detect --image /absolute/path/image.png --prompt 'Describe what is visible in this image.'
```

The supervisor reads the saved Spark reserve, requires the active guard and
30 GiB extra startup headroom, limits batch size to one with 4096 cache pages,
and terminates only its child process group if memory approaches the reserve
or the timeout expires (default 600 seconds). It does not stop/start VSS.
Do not bypass supervision using the internal `--child` entrypoint.
Each run writes unique timestamped logs under `.spark/moondream-photon/runs/`.
`latest-run.txt` records their directory. Missing API results exit 2. Segmentation
cases with invalid/empty masks or spurious negative-control output exit 3.
A nonempty mask is only a structural check, not inspection-accuracy validation.
Token-budget truncation also fails qualification, even if a partial SVG happens
to be renderable.

## Segmentation diagnostics

`--trace-segment` records the actual prompt, committed tokens, sampled logits and
stopping reason. It observes both the generic sampler and fused greedy decode.
The CPU copies add overhead; do not use traced runs as performance measurements.
Ignore uncommitted pipeline lookahead after EOS when interpreting a trace.

`--probe-decode` explicitly enables unsupported per-case experiments through
`diagnostic_prompt` in a case manifest:

- `suppress_first_path_eos`: suppress EOS only for the first step after the
  model's three box tokens, then restore normal decoding.
- `force_svg_start_after_bbox`: constrain that same step to the observed SVG
  boundary token ID10. Its role is inferred from actual Preview output; it is
  not an established MD2 contract. Do not combine this with EOS suppression.
- `coord_denominator_1024`: test the reference implementation's coordinate-bin
  denominator. The original LUT is restored between cases. This did not fix
  the tested default early stopping.

The hooks refuse unaudited engine versions, require serial requests with graphs
off, and modify only the test process. They never supply outline coordinates or
replace a mask with its bounding box. Boundary conditioning produced complete
coarse paths for a narrow Preview subset, with visibly limited quality; other
cases still fail. These are investigation tools, not an enabled VSS feature.

CPU regression checks, including the untraced executor's keyword interface:

```sh
CUDA_VISIBLE_DEVICES='' .spark/moondream-photon/venv/bin/python -m unittest discover -s tools/moondream -p 'test_*.py' -v
```

## Compatibility implementation

`gb10_compat.install_gb10_compat()` attaches an application-owned runtime to
new Kestrel MoE layer instances before `md.photon(...)` constructs the model.
Keep `decode_path="native"`, `enable_cuda_graphs=False`, and batch size one.
There is no model-version or hardware-identity substitution.

The adapter retains FP8 expert storage, casts one routed expert to BF16, uses
FP32 accumulation, respects channel scales and eight-row gate/up interleaving,
and computes exact GELU(gate) times (up + 1). It applies routing weights without
renormalization. No dequantized expert cache is retained. It does not reproduce
native W8A8 activation quantization or promise bitwise native-kernel parity.
LoRA and graph capture are unsupported. Other Photon operations currently use
warned vendor PyTorch fallbacks where SM121 kernels are absent.

GPU numerical checks against an independent CPU dequantization reference:

```sh
.spark/moondream-photon/venv/bin/python tools/moondream/check_gpu.py
```

The numerical checks use real H2048/I1024 matrices with four experts, two
selected experts, and 1/8/64 token batches. They are component checks, not an
accuracy evaluation of the full model. `test_gb10_compat.py` adds CPU checks for
layout, scales, routing, residual activation, malformed inputs and chunking.

## Local assets and observed limits

The model and tokenizer paths are read from `model-path.txt` and
`tokenizer-path.txt` in the artifact directory. Keep the `model.safetensors`
snapshot filename: Photon chooses its loader by suffix, so resolving the
symlink to an extensionless blob selects the wrong loader. Weight SHA256:
`26dde16af961d3a486c7b86b9a34fc8487be7917f7e62324b751400ef4d391b4`.
Model: `moondream3.1-9B-A2B`, revision
`1da27e6c2d2f9118de14560df456881dc62d91f3`.

The positive image is a generated demo illustration, not a real inspection
benchmark. The first successful run took 70.8 seconds to load/warm up, 7.1
seconds for its description and 1.4 seconds for detection. It allocated about
11.9 GiB at idle, reserved about 14 GiB during inference and peaked at 17.3 GiB
allocated during startup. These are limited single-image observations, not
stream throughput or co-residency qualification. Spark shares CPU/GPU memory.

Base image inference runs locally. Upstream Photon also has a usage telemetry
reporter; Hugging Face offline mode controls model downloads and is not a
network isolation mechanism. An air-gapped deployment needs separate validation.

The optional SegHeadRefiner weights require approved Hugging Face access.
Obtaining them alone does not establish usable masks from this 3.1 checkpoint.
No HTTP service or VSS UI integration is enabled by these tools.
