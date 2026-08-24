# Project documentation

This index separates the current operator and deployment contracts from design
history and qualification evidence. Start here instead of guessing which
Markdown file is authoritative.

## Operate and deploy

- [Vision Intelligence operator guide](vision-intelligence-operator-guide.md)
  explains the live, investigation, monitoring, evidence, and system workflows.
- [Vision Intelligence acceptance record](vision-intelligence-acceptance.md)
  records the accepted product and runtime checks.
- [Vision Intelligence parity matrix](vision-intelligence-parity.md) maps the
  current UI to the accepted design concepts and supported backend behavior.
- [Docker deployment guide](../deploy/docker/DEPLOYMENT.md) is the canonical
  clean-device, offline-cache, validation, rollback, and trusted-LAN runbook.
- [Docker profile reference](../deploy/docker/README.md) describes the upstream
  profiles and the Thor-local entrypoint.

## Product and architecture

- [Domain context](../CONTEXT.md) defines the shared product language and
  boundaries used by the code and UI.
- [Architecture decisions](adr/) contain numbered, current design decisions.
  New decisions should supersede an older ADR explicitly instead of silently
  rewriting its history.
- [Accepted CT AI Labs design](design/ct-ai-labs-brand-v2/IMPLEMENTATION.md)
  identifies the visual concept set implemented by the custom UI.

## Research

- [VSS market and capability-gap analysis](research/2026-08-23-vss-market-capability-gap-analysis.md)
  compares the implementation with current NVIDIA and adjacent primary-source
  capabilities and records the Thor-safe priority order.

## Evidence retention

Files beneath `deploy/docker/thor-local/qualification/` are dated qualification
evidence, not active deployment configuration. Keep evidence referenced by a
contract or acceptance record. Generated runtime state, model caches, `.env`
files, and `deploy/docker/data-dir/` are machine-local and must never be treated
as disposable source cleanup targets.
