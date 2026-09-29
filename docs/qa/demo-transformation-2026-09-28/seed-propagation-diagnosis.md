# Sampling seed propagation diagnosis

September 28, 2026. Investigated a confounder in the live any-frame miss versus
successful fixed-file replay. This finding does not establish the cause of the miss.

## Finding

`VlmRequestParams.from_vlm_query` copies a supplied seed into `VlmGenerationConfig`.
The vLLM adapter seeded local Python/NumPy/Torch globals in its video path but
omitted `seed` from all three `SamplingParams` constructors (video, text and
streaming text). Local global RNG seeding does not establish that the engine's
request sampling seed was set. Prior requests specified seed 42; the adapter did
not pass that value to the sampling constructor. Prior measured answers and
latencies remain valid observations, but cannot be described as engine-seed-pinned.

The current `vss-memory-cosmos` container bind-mounts this adapter source.
Existing worker imports do not hot reload when the file changes.

## Change and test scope

Added `seed: config.seed` to all three engine sampling dictionaries. Extended
the existing full model constructor test to include zero and 42. Added a lightweight
standard-library regression that executes the production sampling-construction
blocks extracted from the AST, with a recording constructor in place of vLLM.
This avoids importing or allocating GPU models just to inspect request arguments.

Command:

```
python3 -m unittest discover -s services/rtvi/rt-vlm/tests/generation_config -v
```

Before fix: nine failures, seeds 0/1/42 across all three paths (`None != seed`).
After fix: all nine cases pass in one test. This tests constructor arguments,
not model output reproducibility, visual accuracy, or the full request pipeline.
The extended GPU-dependent full model test has not been run in this pass.

## Next controlled comparison

1. Load the change through staged model restart with the 48 GiB guard and
   documented startup headroom; do not assume the mounted file is active.
2. Verify effective sampling arguments, including seed, temperature, system
   prompt, frame count and processor configuration in the active worker.
3. Compare the preserved missed clip under matched settings, then a bounded live
   run with actual sampled inputs captured. Keep source timing separate from the
   reconstructed retained interval.
4. Do not adopt the faster default on latency alone; require correct positive and
   negative evidence and repeatable event/report handoff.

No service was restarted, inference run or runtime budget changed in this pass.
