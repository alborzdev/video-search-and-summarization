# Package condition diagnosis — September 28

## Symptom and feedback loop

The visibly crumpled package in [the reference frame](package-condition-frame.jpg) is retrieved and played correctly, but fresh questions omit deformation. This pass tests the existing model rather than changing the answer to match expectations.

Run from the repository root:

```sh
python3 docs/qa/demo-transformation-2026-09-28/debug/check_package_condition.py --base-url http://10.88.9.12:7777 --output /tmp/package-condition-result.json
```

Actual output: `FAIL (missed visible deformation): The box has a rectangular shape.` Elapsed 7.110 seconds. This calls the app evidence-analysis endpoint, including its admission/reservation path, for the same five-second recorded interval. It fails when the answer omits deformation language; a keyword match is only a candidate pass and still needs visual review. This is a diagnostic fixture, not a broad accuracy benchmark. Localhost:7777 is not the ingress binding; use the actual host address.

## Ranked hypotheses and probes

1. **Sampling/scale hides the condition.** Shortening to 3–5 seconds should help if empty early frames dominate. It did not: same rectangular answer, 7.177s. A direct 1280×720 frame at excerpt 4s (original 44s), containing a large clearly crumpled package, also produced a standard rectangular-box answer in 3.657s. This weakens temporal sampling as the main cause; it does not prove every model preprocessing stage is correct.
2. **Prompt encourages generic descriptions.** Asking about surfaces/edges returned brown color, printed symbols and slightly worn edges (8.748s), still omitting crumpling. Changing only “box” to “package” returned “cube-shaped box” (7.331s).
3. **Model/input representation limitation.** Image controls with the same neutral question distinguish an empty belt from an occupied one: “no objects” versus “a brown paper bag.” This demonstrates media sensitivity; it does not establish accurate carton classification or prove all video frames reach the model unchanged.
4. **Reasoning mode improves detailed inspection.** Same clear frame with enable_reasoning true and a 512-token output cap took 33.500s and still described a standard rectangular box. No app setting changed. This probe also had a higher output cap than the brief baseline; neither hit its cap, and the slower result did not improve the symptom.

[Raw diagnostic receipts](debug/) retain exact requests/answers and timing. Reasoning-mode receipt stores only the final answer and counts, not the reasoning trace. No permanent instrumentation was added to services.

## Outcome

Unresolved. Do not declare a preprocessing bug fixed or automated condition classification qualified. Retrieval and human inspection remain useful; generic box-shape questions and reasoning mode do not solve this example. The next justified step is inspecting actual model-preprocessed tensors or comparing a qualified visual model at the same evidence boundary, with resource budgets preserved. Avoid more unstructured prompt retries or enabling slower reasoning globally.

No model/runtime budget changed. Final core check: 31 roles, no failures, 49.99 GiB available. Continuous RTSP analysis and both detectors remain off. No broad automated test pass is claimed by these bounded inference probes.
