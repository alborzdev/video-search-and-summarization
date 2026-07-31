# Official VSS 3.2.1 capability-ledger evidence

Date: 2026-07-31
Mode: static, read-only audit; no container lifecycle or artifact download

## Pinned target

- GA tag commit: `7640d917047cf7b0fd3085eefb8282754b56bc94`
- Current upstream `main`: `7732edf8fb38ef896b20f2a0a6a701a4db10dc57`
- Versioned documentation target: VSS 3.2.1

`official-capabilities.json` records 161 reviewed claims from 55 deduplicated
versioned or commit-pinned source records and cross-links them into 25 manifest families and
Phase 0 planning. The claim-set hashes protect the checked-in transcription;
they are not hashes of NVIDIA's remote HTML, and the generic scenario is not a
capability-specific runtime oracle. No new claim is marked `passed_current`.

## Coverage added

- Official local and Edge agent LLM/VLM identities, including Cosmos3 Nano BF16
  as the 3.2.1 default.
- Every named managed/self-hosted LLM and VLM example from the 3.2.1 agent model
  configuration pages, retained as external optional rather than collapsed into
  a generic OpenAI-compatible claim.
- VSS Configurator, SDRC, DeepStream Configurator, Agent Evaluation, model
  customization, SDG and legacy calibration, VLM autoscaling, Brev, secure
  deployment, seven performance appendices, and MV3DT configuration utilities.
- Five API surfaces missing from the scoped 17-surface core ledger and seven
  non-REST protocol contracts.
- Thirty-two exact RT-VLM, RT-Embed, RT-CV, and VIOS release-note behaviors,
  including independent RT-VLM job lifecycle and RT-Embed URL security, queue,
  GOP decode, NGC credential, and TensorRT build contracts.
- Seven platform prerequisites, including the exact AGX Thor BSP/driver and
  supported toolchain versions, kernel/runtime settings, host capacity,
  credential boundaries, and the required Docker `cgroupfs` driver.
- The official 3.2.1 Thor boundary (base and alerts remote-LLM profiles) is
  distinct from this repository's custom, still-unqualified all-local lane.
- Fourteen digest-bound core API/MCP operation surfaces covering RT-VLM,
  RT-Embed, RT-CV, Video Summarization, Alerts, all six documented VST service
  groups, Video Analytics API, VA-MCP, and LVS MCP.
- Agent Skills, validated harnesses, and all nine Orchestrator MCP operations.
- Agent configuration/MCP/report hierarchy and persistence, evaluation output
  artifacts, Phoenix trace structure, and known issues.
- Exact RT-Embed Cosmos-Embed1 variants and scoped defaults; Auto Calibration
  workflow/input/output schemas; Warehouse behavior, alerts, agents, and UI;
  Helm developer profiles; and secure-deployment limitations.
- Eighteen structured discrepancy/boundary records. Every record retains at
  least two exact source/locator/claim observations, even when both sides occur
  in a single official page.

## Deliberate boundaries

- The optional warehouse sample bundle remains excluded; none of these static
  contracts requires it.
- Kubernetes autoscaling, Brev, managed model endpoints, and infrastructure
  authentication/TLS/rate limiting are `external_optional`.
- NVIDIA reference-hardware performance numbers are not represented as Thor
  measurements.
- The versioned RT-VLM documentation's 18-model table and the repository
  README's 11-model table remain an explicit source discrepancy. Missing exact
  artifacts remain unqualified.
- The Video Summarization documentation lists 13 MCP tools, while the pinned
  source registers nine. The four docs-only file-management tools remain a
  blocked source discrepancy, not fabricated local functionality.
- Docker on this Thor still reports the unsupported `systemd` cgroup driver;
  remediation requires an operator-approved daemon restart that interrupts
  running containers.

## Reproduction

```bash
python3 deploy/docker/thor-local/parity/verify_official_capabilities.py --report
python3 deploy/docker/thor-local/parity/verify_manifest.py --report
python3 deploy/docker/thor-local/qualification/acceptance.py
python3 deploy/docker/thor-local/parity/tests/test_official_capabilities.py
```
