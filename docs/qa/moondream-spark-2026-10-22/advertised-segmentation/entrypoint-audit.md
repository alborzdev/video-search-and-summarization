# Photon segmentation entrypoint audit — 2026-10-22

No alternate standard Photon entrypoint was found that automatically selects
a different segmentation checkpoint. The installed SDK, its legacy local
factory, and the public Triton example all use Kestrel's model registry.
Current upstream registry and prompt-config files are byte-identical to the
installed Kestrel 0.9.1 copies. This is evidence against a missed standard
launcher option, not proof that a private or historical deployment never used
different weights.

## Exact model selection

| SDK identifier | Hugging Face repository | Default file | Segment template |
| --- | --- | --- | --- |
| `moondream2` | `vikhyatk/moondream2` | `model.safetensors` | `None` |
| `moondream3-preview` | `moondream/moondream3-preview` | `model_fp8.pt` | Prefix `[1,17374,2]`, suffix `[3]` |
| `moondream3.1-9B-A2B` | `moondream/moondream3.1-9B-A2B` | `model.safetensors` | Prefix `[1,17374,2]`, suffix `[3]` |

All three use `moondream/starmie-v1`, BOS/EOS `0`, coordinate token `5`, and
size token `6`. The registry does not pin revisions. Segment adds BOS, optional
spatial-reference tokens, the object text encoded without an added leading
space, then its suffix. Runtime prompt configuration comes from the installed
registry's `default_config`, not a newly fetched HF `config.json`.
[Registry](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/kestrel/models/moondream/registration.py),
[configuration](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/kestrel/models/moondream/config.py),
[segment request](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/kestrel/models/moondream/skills/segment.py).

## SDK, server, adapters, and capability discovery

`md.vl(local=True, model=...)` calls `md.photon(...)`. The SDK passes the model
identifier and runtime options into `RuntimeConfig` and `InferenceEngine`.
An explicit `model_path` can supply a different compatible checkpoint; normal
startup otherwise uses the registry's HF file. A fine-tune is selected only
by an explicit `{base}/{finetune_id}@{step}` identifier or adapter setting.
No default segmentation adapter was found. The documented quickstart calls
base 3.1 segmentation directly, without a special checkpoint or adapter.
[Official local setup](https://docs.moondream.ai/running-locally/).

Neither installed distribution (`moondream` 2.6.1, `kestrel` 0.9.1) declares
a console script, so there is no installed `photon serve` command to inspect.
The official Triton example creates the same `RuntimeConfig`; its optional
`KESTREL_MODEL_PATH` is an explicit override. That example currently dispatches
only query, caption, detect, and point: it does not expose segment at all.
[Triton engine construction](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/triton_server/model_repository/moondream/1/engine_singleton.py),
[Triton task dispatch](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/triton_server/model_repository/moondream/1/model.py#L182).

Capability discovery is insufficient proof: MD2 and MD3 share a skill registry
that includes `SegmentSkill`. Consequently `tasks`/`supports` can advertise
segment for MD2 even though its prompt template is `None` and request building
rejects it. The registry declares API machinery, not validated checkpoint
behavior. [Shared skills](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/kestrel/models/moondream/skills/__init__.py).

## Optional refinement is separate from initial mask generation

`SegmentRefiner` automatically initializes only if `_vision_backend is None`
and `cv2`, Pillow, and `resvg` all import. This environment lacks `cv2` and
`resvg`, so refinement is disabled. There is no separate runtime-config switch
that makes it generate the initial SVG. Its additional weights come from
`moondream/SegHeadRefiner/model.pt`, a manually gated HF repository; the public
metadata lists revision `d3664cf8d8501b37d9ed8cd222e6d4e876c88621` and total
repository storage of 185,178,335 bytes. No gated download was attempted.
[Refiner implementation](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/kestrel/seg_refiner.py),
[repository metadata](https://huggingface.co/api/models/moondream/SegHeadRefiner).

The skill invokes refinement only after a nonempty, parseable SVG and bbox
exist. The refiner also refuses zero-area input masks. Installing it cannot
alter the earlier model-generated bbox-then-EOS trace; it may improve an
already generated outline. Missing refinement could explain a quality
difference, not the observed absence of coarse SVG tokens.

## Documentation conflict and independent upstream evidence

The pinned Kestrel README describes additional weights as a requirement for
MD3 segmentation and directs users to request access. It does not name those
weights or distinguish a different base checkpoint
from the refinement head. This is an unresolved documentation gap, not proof
of a hidden language-model checkpoint.
[README, line 319](https://github.com/m87-labs/kestrel/blob/8e6fb899bb8a076f3235b6a5ab832a78c031c77b/README.md#L319).

Upstream SDK release PR #15 reports that its selected MD3 H100 segmentation
smoke prompt also produced a box without SVG tokens in the raw Kestrel output.
Ordinary and streamed wrappers agreed, and the authors did not synthesize a
mask. That independently establishes that this symptom can occur outside our
GB10 adaptation. It is one selected prompt, not a universal statement about
all checkpoints, prompts, or Moondream segmentation deployments.
[Official SDK release PR #15](https://github.com/m87-labs/moondream-python/pull/15).

The decisive next evidence would be a known-good local segmentation fixture:
exact model file hash/revision, package versions, input image, prompt,
template, and expected nonempty coarse SVG before refinement. A different
server wrapper or the missing refiner alone is not a supported fix for the
current symptom.

## Reproduction

```bash
.spark/moondream-photon/venv/bin/python docs/qa/moondream-spark-2026-10-22/advertised-segmentation/entrypoint-audit.py
```

The adjacent JSON records source hashes, line locations, exact registry
entries/templates, dependency presence, upstream revision, and HTTP byte
counts. The script is CPU-only, does not import Torch, and does not load a
model, install packages, change services, or call cloud inference.
