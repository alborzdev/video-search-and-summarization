# Draft request to Moondream: exact local segmentation deployment

Prepared locally; not sent.

We need Moondream segmentation locally through Photon on DGX Spark (GB10,
aarch64, SM121). Your local quickstart calls `segment` on public 3.1, but the
engine README requires separate weights, and the 3.1 model-card commit removes
segment. Your [Photon 2.0 release PR](https://github.com/m87-labs/moondream-python/pull/15)
also records an H100 smoke request returning a box without SVG tokens.

We reproduce box-then-EOS on public Preview and 3.1. Preview's independent
PyTorch forward reproduces it too. Forcing the first post-box token to ID10
produces some coarse, incomplete paths; this is not a supported solution.

Please provide:

1. The exact segmentation checkpoint repository, filename, revision/hash and
   access process, plus the matching tokenizer, config and Photon version.
2. Whether `SegHeadRefiner` is required, and whether the historical
   `vikhyatk/moondream-next/seg-model.pt` reference is still relevant.
3. One reproducible image/prompt/expected mask, including any decoding settings.
4. The supported GB10 build or the supported reference path for this checkpoint.

Tested: moondream 2.6.1, Kestrel 0.9.1, kernels 0.7.4, native 0.1.8,
PyTorch 2.13.0/CUDA 13. The GB10 Photon path uses our experimental MoE adapter;
the separate PyTorch comparison does not. The 0.9.2 publisher wheel has the
same SegmentSkill and checkpoint mapping as 0.9.1. Both normal and forced
decoding receipts, actual overlays and memory measurements are available.

Public Preview revision: `5112966d1a723413b1c9a1e8bea272b72e647b35`.
Public 3.1 revision: `1da27e6c2d2f9118de14560df456881dc62d91f3`.
