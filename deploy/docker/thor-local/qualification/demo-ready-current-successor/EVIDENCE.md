# Thor VSS demo-ready evidence — 2026-08-12

Status: **passed** against implementation commit `187c38dd8` on
`agent/vss-3.2.1-thor-parity`.

This is the concise operator-facing qualification record for the local NVIDIA
VSS 3.2.1 Thor demo lane. It deliberately summarizes representative product
workflows rather than repeating the exhaustive capability ledger.

## Current runtime

- `official_edge.py static`: passed.
- `thor_demo.py ... readiness`: passed for the exact local
  `nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8` LLM and
  `nim_nvidia_cosmos3-nano-reasoner_bf16-final` VLM lane.
- `thor-local.sh doctor`: 40 pass, 2 warning, 0 fail.
- `thor-local.sh qualify --tier runtime`: 33 pass, 1 optional skip, 0 fail.
  The skip is the optional Video Analytics OpenAPI document; its health and
  behavior query probes passed.
- `thor-local.sh model-check`: local LLM chat passed and the local VLM accepted
  four ordered images.
- Offline API contract: 17 surfaces, 350 declared REST operations and 44 MCP
  tools plus 5 prompts passed from a clean worktree.
- Disk: 19 GiB free at capture time, above the enforced 10 GiB floor. The cache
  cleaner was running as a single three-process shell tree.
- Exact-model recovery identity/readiness passed after the host reboot. The
  current pull-free recovery path is documented in
  [`../../DEMO.md`](../../DEMO.md).

The two doctor warnings are reviewed and non-blocking: internal diagnostic
listeners bind beyond loopback while the supported ingress remains
loopback-only, and the disk is 98% used while retaining more than 10 GiB free.

## Representative workflow evidence

- Archive semantic search:
  [`../search-semantic-current-runtime-successor/EVIDENCE.md`](../search-semantic-current-runtime-successor/EVIDENCE.md),
  receipt `57a8d5e9dccaac3d613b842f8aac99c71859734857adb9975bfbbdae54796bae`.
- Global Agent chat UI:
  [`../ui-global-chat-sidebar-runtime-successor/EVIDENCE.md`](../ui-global-chat-sidebar-runtime-successor/EVIDENCE.md),
  receipt `6a431d7a3b9c025ff158db9817265a96332cdcff7298d37ca0173a7ad673a743`.
- RT-VLM stream APIs:
  [`../rt-vlm-stream-apis-runtime-successor/EVIDENCE.md`](../rt-vlm-stream-apis-runtime-successor/EVIDENCE.md),
  receipt `450222affc198a1ded9ad5751c81b159cc4136b8fab47b2e8055d780910f7972`.
- Detection plus behavior analytics:
  [`../behavior-analytics-2d-runtime-successor/EVIDENCE.md`](../behavior-analytics-2d-runtime-successor/EVIDENCE.md),
  receipt `b36262e99620b3769f020ef9ef4f4144dd6e0d5280a205c2e10c3e415657cbe0`.
- CV candidate to VLM verification:
  [`../cv-behavior-vlm-verification-runtime-successor/EVIDENCE.md`](../cv-behavior-vlm-verification-runtime-successor/EVIDENCE.md),
  receipt `32091be1b9f0b351368a382bb5b0d57c712cc3a357f7a2ecce0025eb23b9f92a`.
- Fresh local file captioning and summarization, including correct media-time
  bounds and cleanup:
  [`../lvs-file-caption-summary-runtime-successor/EVIDENCE.md`](../lvs-file-caption-summary-runtime-successor/EVIDENCE.md),
  receipt `9aa5d062b2574b7b65da3c67e9bac03c501acfc276f1a0af037318d84a644f7f`.
- A fresh read-only incident query returned stored, confirmed Cosmos3 VLM
  incidents with timestamps, prompts, verdicts, evidence frame IDs and model
  identity through `/api/v1/realtime/incidents`.

## Acceptance boundary

This record qualifies the primary local customer demo. It does not claim
cloud/Kubernetes deployment, the optional 100 GB warehouse sample, Slack,
separately licensed enterprise services, unavailable physical multi-camera
calibration, or large-scale performance limits. Historical alert receipts whose
source locks predate later alert-service improvements remain historical; the
current live alert health, OpenAPI, rule-list, WebSocket and incident-query
contracts passed.
