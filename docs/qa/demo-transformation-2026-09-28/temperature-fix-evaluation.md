# Temperature request fidelity — recovery and evaluation

September 28, 2026. This is a bounded recorded-clip check, not full demo acceptance.

## Fix and verification

The RTVI vLLM wrapper now passes explicit temperature zero into SamplingParams
construction in video, text and streaming text paths. The active Cosmos container
was recreated with the wrapper mounted read-only. Two focused constructor tests
passed (zero and nonzero). They exercise the text-only path; the other paths were
inspected in source. AST parsing and diff whitespace checks passed.

The broader 26-test module did not complete: the 48 GiB guard tripped at
47.958 GiB and stopped model services. This failure is recorded in
[inference-test-reserve-trip.json](inference-test-reserve-trip.json). Avoid running
this model-import test suite alongside loaded inference services.

After confirming models stopped, documented idle reclaim restored 101.93 GiB.
Staged core startup restored models; its initial manager process terminated with
143 while Cosmos continued profiling. Readiness was checked before resuming the
manager to restore application services. No model restart loop was used. Final
[core status](temperature-fix-runtime-status.txt) reports 31 service roles and no
failures. Guard remains active, floor unchanged at 48 GiB, boot ID unchanged:
`ac75a3b5-980a-41c5-8301-200423326f72`. Detectors and live ingestion remain paused.

## Recorded evaluation

Same real warehouse source, exact 0–5 second interval, through the app's admitted
API. No answer substitution, cache fixture or report rewriting.

| Request | Elapsed | Observed result |
| --- | --- | --- |
| Final-visible-frame question, run 1 | 12.005 s | Worker holding a box; no completed placement/ascent claim |
| Identical question, run 2 | 10.557 s | Identical answer text |
| General description | 13.031 s | Carrying and stopping; no completed placement/ascent claim |

[Two exact question responses](temperature-zero-evaluation.json) and
[general response](temperature-zero-general-evaluation.json) retain full requests,
answers and stage timings. Question-run endpoint memory samples were
50.744 → 50.442 → 50.317 GiB; these are not peak-load measurements.

The final-frame answer is consistent with the [inspected frame](rehearsal-final-frame.png).
The general answer still uses plural “boxes” and identifies shelving E, while the
specific response references D. Do not treat fine object counts or spatial labels
as validated. These three samples improve on earlier unsupported action claims;
they do not establish general accuracy, repeatability across all conditions, or
latency percentiles. D22 remains open pending representative grounded evaluation.
