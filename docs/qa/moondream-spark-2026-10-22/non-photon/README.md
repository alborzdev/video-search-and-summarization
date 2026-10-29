# Moondream Preview without Photon on DGX Spark

October 22, 2026. **The non-Photon runtime works; bypassing Photon does not fix
the tested segmentation failure.** This is an executed local comparison. The
completed run made eleven serial calls on GB10: three official description and
detection controls and eight diagnostic segment calls. Only Moondream was used.

## Observed results

| Test | Normal decoding | Experimental SVG-start conditioning |
| --- | --- | --- |
| Warehouse worker, point hint | Box then EOS; no mask, 0.96 s | 84 tokens; partial worker mask, 7.21 s |
| Metal panel, point hint | Box then EOS; no mask, 1.27 s | 256-token limit; incomplete path, 20.77 s |
| Cardboard box, point hint | Repeated boxes until 256-token limit; no mask, 20.71 s | 61 tokens; broad stack-region mask, 5.61 s |
| Blank image | Empty result, 1.11 s | Empty result, 1.15 s; conditioning never activated |

Normal decoding yielded **0/3 positive masks**. Conditioning yielded **2/3
structurally valid masks**, but visual inspection rejected both as dependable
object masks. The worker outline misses the right arm and leg and includes
background to the left. The box outline spans several boxes and gaps. A valid
SVG is not an accurate mask. Neither result has labelled ground truth or IoU.

- [Worker overlay](20261022T171044Z-preview-pytorch-reference/masks/person-point-conditioned.overlay.png)
- [Box-region overlay](20261022T171044Z-preview-pytorch-reference/masks/box-point-conditioned.overlay.png)
- [All results and raw tokens](20261022T171044Z-preview-pytorch-reference/inference.jsonl)
- [Structured summary](result.json)

Official `query` described the worker's yellow vest, hard hat and dark trousers
in 3.54 s. Official `detect` localized the worker in 1.34 s and returned an empty
list on the blank image in 0.80 s. These controls support basic loader and image
path correctness; they do not qualify general detection accuracy.

For the worker, the unmodified probability of EOS after the box was **95.67%**,
versus **4.20%** for the observed SVG-start token. For the panel, EOS probability
was **99.9955%**. These are model choices before any output parser. For the box,
another coordinate token was preferred (65.13%) over EOS (34.86%), causing
repeated boxes. The model does not stop identically in every runtime, but normal
segmentation remains unsuccessful here.

## What this comparison establishes

The public [Preview source](https://huggingface.co/moondream/moondream3-preview/blob/5112966d1a723413b1c9a1e8bea272b72e647b35/moondream.py)
has no official `segment` API. We used its unchanged vision encoder, text
decoder, attention and region heads, with a small diagnostic segmentation loop.
The loop uses the same segment prompt as Photon, spatial feedback and full
vocabulary logits. It does not call the official point generator, which restricts
the vocabulary to coordinates and EOS and therefore cannot generate SVG paths.

The default loop adds no token constraints. The separately labelled experiment
forces token 10 exactly once after the first coordinate/coordinate/size triple,
then restores ordinary greedy decoding. The model generates all contour tokens.
Token 10's SVG-start role is inferred from observed sequences; this is not a
vendor-supported segmentation configuration. No box is painted as a substitute
mask. Incomplete paths and token-budget termination fail the structural check.

The same cached Preview FP8 checkpoint was loaded independently and its expert
weights were dequantized into resident BF16 tensors. This removes Photon and our
GB10 adapter from execution, but **does not restore the original pre-quantization
weights**. Expert rounding/accumulation, attention, TAU GELU and image processing
can differ. Both runtimes normalize selected top-eight router logits and use
BF16 KV caches on this host. This is a runtime comparison, not bitwise parity
or proof of which training/export component caused the failure.

The strongest conclusion is that Photon alone is not a sufficient explanation
for the worker/panel early EOS. Public Preview can generate some SVG geometry
after unsupported conditioning, but these tests do not establish reliable local
segmentation. They also do not disprove the user's previous working Moondream 2
or Preview configuration. Resolving its exact checkpoint and invocation remains
more useful than assuming all releases or cloud/local configurations are equal.

## Runtime and memory

- Host: DGX Spark, GB10 SM121, aarch64; PyTorch 2.13.0+cu130.
- Official source revision: `5112966d1a723413b1c9a1e8bea272b72e647b35`; ten source hashes verified before import.
- Checkpoint SHA256: `699bd3876f9e105440d60a5fe30c26bc33fbdf008f5bd611a3557663b24bd371`.
- All 662 parameter tensors mapped; 40 expert tensors dequantized with per-output-channel FP32 scales. Raw half-split expert layout preserved.
- Eager BF16 PyTorch/SDPA, batch one, context 4096, no compile or CUDA graphs, no LoRA, BF16 KV caches.
- Model load: **21.36 s**. Resident weights: **17.264 GiB**; after caches, **18.042 GiB CUDA allocated**.
- Whole-run peak CUDA reservation: **18.402 GiB**. Minimum sampled host memory available: **37.648 GiB**. Saved reserve remained **20 GiB**, guard active.
- Runtime import audit found **no Photon SDK or Kestrel modules loaded**. No inference API was used; all images and inference stayed local.

Times above include image encoding and, for segmentation, SVG rendering and
artifact writing. File open/resize and model loading are excluded. Raw records
also separate inference from rendering. These are single observations, not
sustained throughput or a representative inspection benchmark. The previous
experimental Photon worker case took 12.71–12.73 s for 91 output tokens; this
reference case took 7.21 s for 84 different output tokens. That is encouraging
for this implementation, but not a controlled speed ratio.

No segmentation service or VSS integration was enabled. Cosmos was temporarily
stopped using the user's existing authorization. Final readiness and the guard
state are recorded in `recovery.json` after restoration. No concurrency
qualification between Cosmos and this BF16 model is claimed.

## Reproduction and evidence

After staging the pinned source files and cached checkpoint and arranging the
documented workload headroom:

```sh
.spark/moondream-photon/venv/bin/python tools/moondream/measure_reference.py --cases docs/qa/moondream-spark-2026-10-22/non-photon/20261022T171044Z-preview-pytorch-reference/cases.json --timeout 600
```

The supervisor requires the active Spark guard and 30 GiB above the saved reserve
before startup, samples memory every 0.2 s, and terminates only its own child if
available memory falls below reserve + 3 GiB or the timeout expires. It does not
manage VSS services; do not invoke its internal `--child` mode directly.

The completed child exited **0** after all eleven calls. The supervisor exited
**3** because four positive segmentation requests failed qualification; this is
not a runtime crash. All **31 CPU tests passed**, including independent loader
arithmetic and decoding protocol checks. See [CPU results](cpu-tests.txt),
[loader audit](reference-load-audit.md), and [source/evidence hashes](source-and-test-receipt.json).

The earlier 17:10:00 run is retained as a harness failure: a query updated
inference-mode KV buffers outside `torch.inference_mode()`. The harness was
corrected to execute all model calls under that context, then all eleven cases
were rerun at 17:10:44. The failed run is excluded from capability and timing conclusions.
