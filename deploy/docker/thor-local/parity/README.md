# Thor VSS parity ledger

This directory is the acceptance ledger for the Thor-local VSS integration. It
separates four facts that are easy to conflate:

1. NVIDIA advertises a capability.
2. Its source or deployment asset is present in this checkout.
3. The Thor profile selects and configures it.
4. It has passed a current end-to-end run on this Thor.

The authoritative target is NVIDIA's protected `main` at
`7732edf8fb38ef896b20f2a0a6a701a4db10dc57`: VSS 3.2.1 plus the current LVS
invalid-purpose API fix. Unreleased nightly/develop snapshots are recorded but
do not silently redefine the GA acceptance target.

Run the static contract check from the repository root:

```bash
python3 deploy/docker/thor-local/parity/verify_manifest.py
```

Print the current gap report:

```bash
python3 deploy/docker/thor-local/parity/verify_manifest.py --report
```

Compile the complete stateful acceptance plan without executing it:

```bash
python3 deploy/docker/thor-local/qualification/acceptance.py
```

This Phase 0 planner fail-closes unless every current feature capability,
skill, REST operation, MCP tool, and MCP prompt has a scenario and explicit
blockers. It has no execution option and reports zero network requests,
processes, or mutations. See `qualification/ACCEPTANCE.md` for its owned
namespace, exact-target cleanup, fixture, and append-only ledger contracts.

`manifest.json` is intentionally conservative. `source_only`, `partial`,
`static_only`, `not_qualified`, and `blocked` are open work, not parity. A
feature may become `wired` only when the Thor Compose/config path selects it;
it may become `passed_current` only when a reproducible runtime check and its
evidence are recorded.

Some NVIDIA features are external surfaces rather than local runtime features:
Helm requires Kubernetes, Slack is a third-party destination, and the shipped
Smart City map uses Google Maps. The complete local goal requires either a
documented local replacement or an explicit `external_optional` boundary; it
must never be represented as offline functionality.

NVIDIA's versioned warehouse app-data resource is an optional reference
fixture, not a VSS capability and not a parity gate. The roughly 100 GB sample
bundle is excluded from this Thor acceptance target. Warehouse acceptance is
based on the local custom-data contract (operator-provided compatible models,
videos/streams, and calibration) plus reproducible static and runtime evidence;
an unavailable NVIDIA sample must not turn that capability into a blocker.

Register the 16 versioned NVIDIA VSS skills with Codex, or verify the current
host registration, with:

```bash
deploy/docker/thor-local/install-vss-skills.sh install
deploy/docker/thor-local/install-vss-skills.sh status
```
