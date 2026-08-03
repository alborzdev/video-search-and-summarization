# Agent Evaluation producer-only qualification package

This package prepares the next qualification lane for the five required-local
Agent Evaluation rows:

- `evaluation.agent.report`
- `evaluation.agent.qa`
- `evaluation.agent.trajectory`
- `evaluation.agent.multi-turn`
- `evaluation.agent.execution-artifacts`

It is intentionally **not promotion evidence**. It does not edit or authorize
the canonical ledger, oracle, selector, descriptors, or any metadata correction
package. Its base revision is source lineage only; it locks evaluator and profile
Git blobs directly and does not require canonical metadata to stay byte-identical.

## What runs now

The default command is inert and prints a schema-shaped nonpromoting plan:

```bash
python3 deploy/docker/thor-local/qualification/agent-evaluation-runtime-evidence-successor/executor.py
```

The bounded development command generates two independent copies of tiny JSON
fixtures, validates exact source/config/NAT locks, exercises deterministic local
stub mechanics and adjacent negatives, compares every generated file digest, and
removes both temporary trees:

```bash
python3 deploy/docker/thor-local/qualification/agent-evaluation-runtime-evidence-successor/executor.py \
  --execute \
  --output /tmp/agent-evaluation-mechanics.json
```

The executor makes zero Docker, network, download, model, service, product
subprocess, credential, or Warehouse-sample accesses. It always records an empty
eligibility list, `receipt_is_runtime_evidence=false`, and
`aggregate_is_promotable=false`.

## Cached-image discovery already completed

Thor has the ARM64 image
`nvcr.io/nvidia/vss-core/vss-agent:3.2.1` at immutable digest
`sha256:b7f3246aaf355ebf96e91a40b2f0abc5dea7e330e7bf9a7cf726107b560c3ac1`.
A one-shot, entrypoint-overridden inspection used `--pull never`,
`--network none`, read-only filesystems, no GPU, and
`INSTALL_PROPRIETARY_CODECS=false`. It established only that:

- NAT 1.6.0 exposes `nat eval --config_file`;
- the image registers `report_evaluator`, `customized_qa_evaluator`, and
  `customized_trajectory_evaluator`.

No VSS service or model was started. The exact discovery boundary is recorded in
`discovery-observation.json` and carries no promotion value.

## What cannot execute under the current constraint

A genuine run of the five advertised contracts is blocked because the local
evaluation dataset, ground-truth reports, referenced uploaded videos, running VSS
workflow dependencies, and authorized local judge endpoint are absent. QA and
trajectory are LLM-judge evaluators; report also advertises `llm_judge`. The
product `nat eval` workflow was therefore not run, and the five generated result
files are explicitly synthetic filename-mechanics placeholders, not NAT outputs.

The corrected judge binding is kept explicit: `report_evaluator` selects
`metric_configs.llm_judge.llm_name: eval_llm_judge`, whose profile is
`max_tokens: 4096` and `temperature: 0.0`. The local Thor profile is locked at
SHA-256 `5d07f34f…`; the repository-authoritative upstream raw file at commit
`7732edf8…` is recorded separately as `e89664e4…`. The former binds the actual
checked Thor input while the latter preserves upstream lineage for the same
selection/profile semantics. These are profile values, not evaluator defaults.

One source/config coverage gap is also kept visible: the checked report metrics
profile does not exercise `f1`, although the report
evaluator registry implements it.

The purpose-built tiny fixture includes all four deterministic report metrics,
the unexecuted `llm_judge` identity, dynamic fields, exact `4096/0.0` judge profile,
both trajectory modes, same-step tools, two-turn context, valid/invalid dataset
filters, the referenced-video precondition, and all five output filenames. These
prove fixture and routing mechanics only.

## Requirements for later promotion

Promotion requires a separately authorized, offline/cache-only run that uses the
locked image and a real local judge, starts the necessary local product services,
uploads generated tiny referenced video fixtures, invokes real
`nat eval --config_file`, validates semantic scores and nonempty artifact schemas,
and performs reviewed metadata integration afterward. A deterministic fake judge
may help test plumbing but cannot prove the advertised semantic quality.
