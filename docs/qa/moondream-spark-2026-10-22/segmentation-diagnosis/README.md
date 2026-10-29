# Moondream segmentation diagnosis on Spark

October 22, 2026. This continues the [checkpoint comparison](../alternate-models/README.md).
Moondream now produces real coarse masks through local Photon under experimental
decoding. No substitute segmentation model is used. Reliable local inspection
segmentation remains unfinished: mask quality and negative controls are not
qualified for deployment.

**New result from the continuation experiment:** public Preview emitted a real
coarse SVG for the person/point case after suppressing EOS at one step immediately
after the box. It then generated the path itself and stopped naturally after 91
tokens. Visual inspection shows a partial worker outline, with missing body parts
and some background included. It is not quality validated. The panel case still
emitted boxes only; the coordinate-denominator experiment fixed neither case.
This demonstrates latent path generation and changes the diagnosis below.

## Completed probes and current limits

Times in run IDs are UTC. A positive-mask success below requires natural
termination and a nonempty valid raster mask. It does **not** mean accurate
segmentation. A negative control must return neither a path nor a box.

| Run | Experiment | Positive masks | Negative controls | Budget stops |
| --- | --- | ---: | ---: | ---: |
| [16:24:10 MD2](20261022T162410Z-moondream2-stock/exit.json) | Eight prompt variants; unsupported template | 0/8 | — | 0 |
| [16:30:13 Preview](20261022T163013Z-moondream3-preview-gb10/exit.json) | Normal decoding; no/point/box hints | 0/6 | 1/1 | 0 |
| [16:35:44 Preview](20261022T163544Z-moondream3-preview-gb10/exit.json) | Baseline, coordinate LUT, EOS suppression | 1/6 | 1/1 | 0 |
| [16:40:50 Preview](20261022T164050Z-moondream3-preview-gb10/exit.json) | Twelve-case boundary study | 2/11 | 1/1 | 5 |
| [16:46:22 MD2](20261022T164622Z-moondream2-stock/exit.json) | Observed boundary ID with unsupported template | 0/3 | 0/1 | 0 |
| [16:50:47 3.1](20261022T165047Z-moondream3.1-9B-A2B-gb10/exit.json) | Untraced boundary probe | 2/3 | 0/1 | 1 |
| [16:53:42 Preview](20261022T165342Z-moondream3-preview-gb10/exit.json) | Untraced selected-case repeat | 3/3 | 1/1 | 0 |

These model processes completed. The first six qualification exits are 3 because
requested masks or negative controls failed; this is distinct from a crash. The
last repeat exits 0 on its selected structural checks. Its three positive calls
are two repeats of the same person input and one box-region input, not three
independent objects or an accuracy benchmark.

### Twelve-case Preview boundary experiment

The boundary option permits only ID10 at exactly one step after three committed
coordinate/coordinate/size tokens. Normal sampling and EOS resume immediately.
Its SVG-start meaning is **inferred** from the observed `10 → path → 11 → EOS`
sequence, not an official token-ID contract. The helper never inserts a contour
or constructs geometry. This is unsupported diagnostic conditioning.

| Case | Change | Tokens | Outcome |
| --- | --- | ---: | --- |
| Panel, point | Suppress EOS once | 7 | Boxes only |
| Panel, box hint | Suppress EOS once | 10 | Boxes only |
| Panel, no hint | Permit ID10 once | 256 | Budget; invalid incomplete path |
| Panel, point | Permit ID10 once | 256 | Budget; invalid incomplete path |
| Panel, box hint | Permit ID10 once | 256 | Budget; invalid incomplete path |
| Person, no hint | Permit ID10 once | 256 | Budget; invalid incomplete path |
| Person, point | Permit ID10 once | 91 | Natural EOS; coarse mask |
| Person, box hint | Permit ID10 once | 256 | Budget; invalid incomplete path |
| Panel, point | Leading space only | 4 | Box only |
| Person, point | Leading space only | 4 | Box only |
| Cardboard box, point | Permit ID10 once | 51 | Natural EOS; coarse region mask |
| Blank | Boundary option enabled | 1 | Empty; boundary hook never activates |

Thus 2/7 positive forced-start cases completed; 5/7 exhausted the 256-token
budget. Incomplete paths pass Kestrel's permissive string parser but fail the
stricter mask validator. Nonempty SVG text alone is not success. All twelve
sampled prefixes match committed tokens; there are no trace errors. The trace
shows ID10 masking only at the intended step, followed by normal sampling.

The [worker overlay](20261022T164050Z-moondream3-preview-gb10/masks/person-point-svg-start.overlay.png)
roughly overlaps the worker but misses the visible right arm and leg and includes
background. Its left boundary is conspicuously straight. The SVG and bbox are
byte-identical across the earlier EOS-suppression probe and direct-ID10 probe,
both with 91 output tokens.

The [box-region overlay](20261022T164050Z-moondream3-preview-gb10/masks/warehouse-box-svg-start.overlay.png)
covers the left portion of a stack, including multiple boxes and gaps, rather
than isolating one box. Different objects produce different geometry and bboxes;
this is not a constant template. Neither mask has labelled ground truth, an IoU
score or production accuracy validation.

### MD2 and 3.1 follow-ups

The four-case MD2 probe forced ID10 at exactly the intended step in every case.
The panel then generated an English description, rejected as SVG at its first
word. The person emitted EOS; the box emitted an equals sign then EOS. Blank
input produced a false box. No path completed. This Preview boundary convention
does not transfer successfully to the tested MD2 checkpoint and unsupported
prompt; it does not disprove the user's prior working MD2 configuration.

The corrected untraced 3.1 probe produced natural masks for the person and box
region in **8.47 s / 62 tokens** and **5.24 s / 34 tokens** respectively. These are
single serial calls excluding model loading, not a throughput benchmark. The
person mask covers part of the body and an adjacent beam. The panel exhausted
256 tokens without a valid mask. Most critically, the blank input produced a
nearly full-frame false mask in **6.69 s / 42 tokens**. A successful rasterization
is therefore not evidence of reliable object presence or inspection quality.

The earlier [16:47:52 3.1 attempt](20261022T164752Z-moondream3.1-9B-A2B-gb10/inference.jsonl)
is excluded from model and latency conclusions. A diagnostic hook used parameter
`context` instead of `request_context`, so keyword admission failed before each
inference. Tracing had hidden this defect by forwarding positionally. The helper
was corrected and CPU tests now exercise keyword invocation. That run has a
model `closed` record but no supervisor `exit.json`; the parent observed session
exit 143. The cause of supervisor termination is not established. No reserve
breach appears in the retained telemetry.

### Final untraced Preview repeat

The [final repeat](20261022T165342Z-moondream3-preview-gb10/exit.json) passed its
selected structural checks with the same coarse masks. The person uses one-step
EOS suppression; the box uses one-step ID10 conditioning. Blank remains empty.

| Selected call | Tokens | Measured elapsed time | Result |
| --- | ---: | ---: | --- |
| Person, point, repeat 1 | 91 | 12.733 s | Natural stop; same coarse worker mask |
| Person, point, repeat 2 | 91 | 12.705 s | Natural stop; identical mask |
| Box-region, point | 51 | 7.520 s | Natural stop; same stack-region mask |
| Blank, EOS-suppression option | 1 | 1.155 s | Empty; suppression never activates |

These are loaded-model serial call times including PNG encoding, Photon, mask
rendering and artifact writing. They exclude model loading and earlier image
load/resize. They are not camera-stream throughput or an accuracy benchmark.
The run's peak CUDA reserved memory was 17.350 GiB.

The worker SVG hash is
`51ec6802ff5de672a81fd1aa29e4b851f3866c0c501a6cebe26b8d23838a0abe`
across four observations in three runs, including the two untraced repeats.
The box-region SVG hash is
`84d2fcaa4c36fee9c1bc71ab0d78cbfa49d6246fcb16ae2c9150d373b2f1b15a`
across traced and untraced runs. Bboxes also match exactly. Repeatability does
not improve the visual quality limitations described above.

## What the new trace establishes

For public Preview, six positive cases (panel and person, each with no hint,
point hint and box hint) produced exactly **coordinate, coordinate, size, EOS**.
The model itself selected EOS. None stopped on a skill-specific rule, token
budget or context budget. All observed logits were finite. The blank control
correctly produced only EOS, without a box.

| Positive case | EOS minus next-best logit | EOS unscaled softmax |
| --- | ---: | ---: |
| Panel, no hint | 12.125 | 99.9996% |
| Panel, point hint | 10.25 | 99.9966% |
| Panel, box hint | 10.25 | 99.9966% |
| Person, no hint | 4.75 | 99.14% |
| Person, point hint | 2.75 | 93.87% |
| Person, box hint | 5.375 | 99.54% |

These percentages describe the observed next-token distribution, **not calibrated
confidence in an inspection result**. The trace does not prove that no possible
prompt can produce a mask. It does establish that these empty paths originate
before SVG parsing, with a strong model preference to end the response.

The scheduler pipelines one extra sampled token after the committed EOS. That
lookahead is not part of the answer. The summary matches sample positions to
committed token IDs and ignores it. The trace preserves the fused greedy sampler;
it does not disable that path. Copying logits to the CPU adds overhead, so these
runs must not be used as performance benchmarks.

Moondream 2 was also tested with eight prompt variants: two objects, with/without
a leading space and with single/double answer delimiters. All returned only a
box and EOS. MD2 requires an explicit unsupported segment-template override for
this experiment; its stock configuration disables the skill. That first trace
captured stop reasons and committed tokens but missed greedy decode logits. The
subsequent Preview trace fixes this omission and has CPU tests for both sampler
branches. Do not infer MD2 EOS probabilities from that earlier trace.

See [trace-summary.json](trace-summary.json), the timestamped run directories,
and the copied case manifests. Generated demo artwork and a retained warehouse
frame are functionality inputs, not a defense inspection accuracy benchmark.

## Other causes checked

- **Tokenizer:** the cached tokenizer exactly matches official Starmie. Current
  official MD2 and Preview code select Starmie, despite legacy tokenizer files
  remaining in the MD2 repository. Task tokens match; no tokenizer postprocessor
  inserts EOS. An SVG fixture survives the actual engine parser.
  [Tokenizer audit](tokenizer-audit.md).
- **Newer checkpoint filenames:** all 870 tensor storage CRCs and tensor metadata
  in the public Moondream-next PT match cached 3.1. Its safetensors file has the
  same advertised SHA-256 as 3.1. Preview's newer BF16 export matches the cached
  FP8 export on the sampled tensors/rows after dequantization. These checks do
  not justify treating those downloads as new segmentation weights. CRC and
  sampling limitations are explicit in the [checkpoint audit](checkpoint-comparison.md).
- **SVG renderer:** CPU fixtures cover curves, holes, bbox-relative placement and
  invalid paths. Default decoding provided no path; the altered-decoding cases
  above supply real paths. A box is never used as a replacement mask.
- **Coordinate bins:** official Preview HF code divides coordinate indices by
  1024; Photon uses a 0-to-1 linspace, effectively dividing by 1023. Their BF16
  tables differ at 128/1024 bins, with maximum delta 0.00390625. The isolated
  `/1024` ablation fixed neither object. Size decoding already agrees. The
  diagnostic restores the original LUT before each subsequent case.
- **Refiner:** Photon only invokes the optional refiner after a nonempty coarse
  path exists. The absent refiner cannot explain zero coarse-path tokens.
- **Memory:** the normal supervisor and 20 GiB reserve remained in force. No
  out-of-memory termination explains these responses. Exact minimum available
  memory is in each receipt. The copied runs have a minimum of **34.207 GiB host
  available**, above both the 20 GiB reserve and the supervisor's 23 GiB stop
  threshold. This is unified memory; CUDA allocation is not a separate VRAM
  capacity claim. Cosmos recovery is recorded separately.

## Release discrepancy and next required evidence

The [Kestrel README](https://github.com/m87-labs/kestrel#segment) states that local
segmentation requires Moondream 3 and separate model weights, obtained from
Moondream. The 3.1 maintainer explicitly [removed segment from its public model
card](https://huggingface.co/moondream/moondream3.1-9B-A2B/commit/1da27e6c2d2f9118de14560df456881dc62d91f3).
However, the [Photon support table](https://moondream.ai/photon/support) advertises
Segment even for MD2, and the [cloud API](https://docs.moondream.ai/skills/segment/)
lists both Preview and 3.1. These claims do not identify identical downloadable
weights and are inconsistent with the installed MD2 template.

**Revised working diagnosis:** ordinary decoding ends before the path, but the
public Preview checkpoint can produce an outline under altered decoding. It is
therefore incorrect to conclude that these weights have no segmentation ability.
The cause of the default stopping behavior and poor outline quality remains open:
checkpoint training, skill invocation, and the unqualified GB10 runtime may all
matter. A known working checkpoint and vendor reference output would help isolate
these factors. Successful image answers and component tests do not eliminate
full-model numerical differences.

The saved account's access check for the known segmentation checkpoint returned
403; see the previous [access receipt](../alternate-models/access-check.json).
No access gate was bypassed and no external message was sent. A concrete
[vendor question draft](vendor-question.md) identifies the needed artifacts.
The user's report of prior working MD2/Preview segmentation is retained as a
useful lead, not contradicted by these local tests.

## Reproduce

Each timestamped copy includes original logs, settings, mask artifacts, case
list and the model manifest. Its `evidence-manifest.json` records SHA-256 for all
copied files and input images. Copies were made after supervisor exit receipts
existed, except the explicitly labelled closed 3.1 harness failure. That failure
is excluded from model conclusions. `trace-summary.json` also records exact
per-run reproduction commands, counts, memory minima and current helper hashes.
Current helper hashes are not historical source snapshots for older probes.

| Artifact | Published SHA-256 from saved HF manifest |
| --- | --- |
| Preview `model_fp8.pt` | `699bd3876f9e105440d60a5fe30c26bc33fbdf008f5bd611a3557663b24bd371` |
| MD2 `model.safetensors` | `70a7d94c0c8349eb58ed2d9e636ef2d0916960f321ecabeac6354b8ba3d7403f` |
| 3.1 `model.safetensors` | `26dde16af961d3a486c7b86b9a34fc8487be7917f7e62324b751400ef4d391b4` |

Exact repository revisions are retained in the manifests. Large weights were
not rehashed during this documentation pass.

Twenty CPU tests pass: adapter math, SVG rendering, trace preservation, exact
one-step constraints, LUT reset and keyword-compatible runtime invocation:

```sh
CUDA_VISIBLE_DEVICES='' .spark/moondream-photon/venv/bin/python \
  -m unittest discover -s tools/moondream -p 'test_*.py'
```

Arrange memory headroom using the existing service policy, then run from VSS:

```sh
.spark/moondream-photon/venv/bin/python tools/moondream/measure.py \
  --model moondream3-preview --compat --probe-decode --trace-segment \
  --tasks segment --timeout 600 \
  --cases docs/qa/moondream-spark-2026-10-22/segmentation-diagnosis/20261022T164050Z-moondream3-preview-gb10/cases.json
```

Expected current result: supervisor exit 3, because positive masks are missing;
the model process itself completes normally. These are cached, pinned local
weights. The command does not stop/start Cosmos or launch an HTTP service.
Other probes' equivalent commands are stored in `trace-summary.json` under
`reproduce_from_vss_root`. Traced timings are not latency claims; untraced timings
are small serial probes excluding load, not deployment qualification.

Diagnostic hooks are application-owned, process-only and version checked.
Installed vendor packages, the VSS UI, the selected detector and model budgets
are unchanged by this investigation.

## Service recovery

Cosmos was restored after the final test. The [recovery receipt](recovery.json)
at 16:57:59 UTC records Docker `running healthy`, readiness HTTP 200, the active
Spark guard, 38.90 GiB available memory and no remaining Moondream test process.
The saved reserve remains 20 GiB. No Moondream HTTP service is enabled.
