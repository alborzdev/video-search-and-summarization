# Checkpoint comparison — October 22, 2026

The comparison found no evidence that downloading Preview's newer BF16 files
or Moondream-next would provide different segmentation weights. The precise
results and HTTP byte-range ledger are in [checkpoint-comparison.json](checkpoint-comparison.json).

## Preview BF16 versus cached Preview FP8

The public Preview `model_fp8.pt` was uploaded on January 26, 2026. A February
10 commit changed the Hugging Face BF16 index to `modelv2-*` shards and fixed
the accompanying region-normalization implementation. These publication dates
alone do not establish that the weights were retrained.

At revision `5112966d1a723413b1c9a1e8bea272b72e647b35`:

- Six complete, nonquantized tensors match the cached FP8 checkpoint exactly:
  region normalization weight and bias, coordinate encoder bias, layer-4
  router bias, final text normalization weight, and language-head bias.
- Five expert rows, spanning gate, up and down projections and experts 0 and
  63, exactly equal the cached FP8 values multiplied by their channel scales
  and rounded to BF16.
- Requantizing those five BF16 rows with the cached channel scales reproduces
  100% of the corresponding FP8 bits.
- The four BF16 shards total 18,537,326,392 bytes (17.264 GiB).

This is a sample comparison, not an exhaustive comparison of Preview's
weights. It supports retaining the existing checkpoint instead of downloading
17 GiB on the assumption that `modelv2` contains a new segmentation model.

## Moondream-next versus cached Moondream 3.1

At Moondream-next revision `a5b63b4e19d1be4ae8dbd1d02b2bde864cc09913`:

- `model.safetensors` has the same advertised SHA-256 and size as cached 3.1:
  `26dde16af961d3a486c7b86b9a34fc8487be7917f7e62324b751400ef4d391b4`,
  10,505,269,576 bytes.
- The remote `model.pt` ZIP directory and inert pickle metadata describe 870
  tensors. Every tensor name, shape, dtype and contiguous storage layout
  matches cached 3.1.
- Every one of the 870 remote storage CRC32 values matches a CRC32 calculated
  from the corresponding local safetensors payload. There are no differences
  and no skipped tensors.

The remote PT tensor bodies were not downloaded. Their complete SHA-256 was
not independently verified; CRC32 equality is not a cryptographic proof.
The aggregate evidence nevertheless strongly supports alternate packaging of
the already-tested 3.1 weights, rather than a new checkpoint to test.

## Reproduce

Run from `/home/sparkdev/vss`, using the already-staged checkpoints:

```bash
.spark/moondream-photon/venv/bin/python tools/moondream/compare_checkpoint_samples.py --receipt docs/qa/moondream-spark-2026-10-22/segmentation-diagnosis/checkpoint-comparison.json
```

The script disables CUDA, uses CPU memory mapping, accepts only inert remote
pickle metadata, and enforces 16 MiB per network read and 50 MiB total. This
run read 442,300 response-body bytes in 28 requests; the largest was 115,705
bytes. It read 10,505,161,984 bytes from the already-local 3.1 payloads for CRC
comparison. No model inference or service changes occurred.

Primary sources: [Preview revision](https://huggingface.co/moondream/moondream3-preview/tree/5112966d1a723413b1c9a1e8bea272b72e647b35),
[February BF16 update](https://huggingface.co/moondream/moondream3-preview/commit/1dae073c11761588126e4bf439ff918ba77ac6c1),
[Moondream-next revision](https://huggingface.co/moondream/moondream-next/tree/a5b63b4e19d1be4ae8dbd1d02b2bde864cc09913).
