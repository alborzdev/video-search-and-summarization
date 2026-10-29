# Independent Preview PyTorch comparison: loader audit

The cached Preview FP8 checkpoint can populate the official Preview PyTorch
model without downloading its 17.26 GiB BF16 export. The loader is
`tools/moondream/reference_loader.py`; its CPU-only dry-run receipt is
`reference-load-audit.json` in this directory.

The loader imports the ten core source files from pinned revision
`5112966d1a723413b1c9a1e8bea272b72e647b35`, verifies their SHA256 hashes, and
constructs the model on the meta device. It uses the locally cached Starmie
tokenizer after checking its audited SHA256. This avoids the Transformers
wrapper: Torch, NumPy, Pillow, and tokenizers are already installed. Neither
Photon nor its GB10 compatibility adapter is imported.

Every one of the official model's **662 parameter tensors** has an exact
checkpoint name mapping and shape check. The 870 source tensors comprise those
662 weights, 40 FP32 expert scale tensors, and 168 scalar KV-quantizer metadata
tensors. Only the known KV metadata is unused, because the official reference
uses BF16 KV caches. Unknown keys, missing parameters, unexpected dtypes, bad
shapes, and nonpositive/nonfinite expert scales cause an error.

Each expert weight is loaded as `(raw_FP8.float() * channel_scale).bfloat16()`.
The original checkpoint already has contiguous gate and up halves. There is
**no Photon row interleave** in this path. Fourier coordinate/size features
are transposed; the region LayerNorm and all three per-layer TAU parameters
are explicitly loaded. The checkpoint is read-only CPU mmap. Only one
destination parameter and one expert's conversion chunk are allocated at a
time; no converted checkpoint file is written.

The stock official forward functions are unchanged: BF16 `F.linear`/`bmm`,
top-k router softmax, exact `GELU(gate) * (up + 1)`, and stock SDPA attention.
Flex decoding is disabled through the existing model flag; compilation is not
called. This is a useful independent implementation comparison, but its BF16
weight rounding, reductions, attention, and KV-cache format differ from Photon.
Matching results do not isolate every possible numerical difference.

Final BF16 parameter storage is **18,537,253,856 bytes (17.264 GiB)**.
The default context is explicitly capped at 4096 tokens (the pinned upstream
default is also 4096): the attention mask is 16 MiB and KV caches total 768 MiB.
The loader requires at least **41.264 GiB MemAvailable** before a full load:
20 GiB saved reserve, 17.264 GiB weights, and a 4 GiB runtime allowance. It
checks the reserve during loading. The CPU audit observed about 39.2 GiB
available, so another resident model must be released before that test. Runtime
allocation remains an empirical quantity; the caller must retain its bounded
supervisor and system memory guard.

Four small CPU tests passed. They cover exact row-scale multiplication and
half-split ordering, rejection of unexpected tensors and malformed scales or
shapes, and both official single-token and multi-token expert code paths
against an independent FP32-accumulated reference with BF16 rounding. The full
mapping dry run passed with `cuda_initialized: false`. No GPU test or service
change was performed for this audit.

Example integration, after the caller configures its CUDA library paths and
coordinates memory/service availability:

```python
from pathlib import Path
from tools.moondream.reference_loader import load_reference_model

state = Path('.spark/moondream-photon')
model, receipt = load_reference_model(
    (state / 'reference-source-path.txt').read_text().strip(),
    (state / 'preview-model-path.txt').read_text().strip(),
    (state / 'tokenizer-path.txt').read_text().strip(),
    device='cuda', max_context=4096, reserve_gib=20,
    dry_run=True,  # CPU/meta mapping audit; full load requires False.
)
```

The pinned official core has no public `segment()` method. Any segmentation
token trace built on this model must be labeled a diagnostic reconstruction,
not an officially supported standalone segmentation API. Official `detect`,
`point`, `query`, and `caption` provide useful control cases first.

Sources: [pinned official core](https://huggingface.co/moondream/moondream3-preview/blob/5112966d1a723413b1c9a1e8bea272b72e647b35/moondream.py),
[official expert math](https://huggingface.co/moondream/moondream3-preview/blob/5112966d1a723413b1c9a1e8bea272b72e647b35/layers.py),
[official model structure](https://huggingface.co/moondream/moondream3-preview/blob/5112966d1a723413b1c9a1e8bea272b72e647b35/text.py).
