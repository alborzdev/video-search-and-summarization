#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Unified static-only Thor parity milestone. This script must not start, stop,
# deploy, pull, build, or download anything.
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
thor_local_root="${repo_root}/deploy/docker/thor-local"

bash "${script_dir}/test-thor-local-doctor.sh"
bash "${script_dir}/test-thor-parity-manifest.sh"
python3 "${thor_local_root}/parity/capability_oracles.py" --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/tests" \
  -p 'test_capability_oracles.py' -v

# The live official ledger contains two intentionally layered, static-only
# successors. Validate the terminal six-leaf source-claim repair, then observe
# its exact rollback to the Alerts post-state and the Alerts layer's exact
# rollback to its predecessor. The old single-layer Alerts validator is not a
# standalone validator of this later live state. No rollback or write runs.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/source-claim-hash-repair-successor/integrate_live.py" \
  validate >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s "${thor_local_root}/qualification/source-claim-hash-repair-successor/tests" \
  -p 'test*.py' -v
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/alerts-source-claim-layered-observation-successor/compiler.py" \
  validate >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/alerts-source-claim-layered-observation-successor/tests"

# Exact protocol vectors are source-pinned but deliberately unexecuted.
python3 "${thor_local_root}/qualification/protocol-cases/validate_protocol_cases.py"
python3 "${thor_local_root}/qualification/protocol-cases/protocol_case_executor.py" \
  plan >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/protocol-cases/tests" \
  -p 'test_protocol*.py' -v

# Wave 2 remains immutable extraction provenance and validates its full live merge.
python3 "${thor_local_root}/parity/candidates/wave2/validate_candidate.py" --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave2" \
  -p 'test_candidate.py' -v

# The immutable source-lock implementation is predecessor-anchored below. Its
# 172-page/26,449-edge artifacts are independently recomputed later by the
# documentation-drift validator without invoking the old Wave 3 lifecycle.

# Wave 3 coverage is immutable extraction provenance. Its API-inventory input
# predates the Thor-local LVS adapter, so do not relabel or replay it against
# the evolved live contract. The third successor digest-checks the historical
# merge outputs; current 18/13 API coverage is validated by the contract tier.

# The recursive-coverage implementation is likewise immutable and verified by
# exact predecessor tree identity below; the live artifact semantics are
# rechecked later by the separate offline documentation-drift package.

# The exact-title successor remains an immutable 289-era snapshot, but its
# direct source digest predates the later layered source-claim repair. Do not
# replay it against current live bytes. The activation rebase later preserves
# the historical live-289 descriptor/selector identity and rollback lineage.

# These two entry-level contracts bind the exact checked-in implementation and
# CLI surfaces for the twelve newly canonical tooling entries. They are
# deterministic source-wiring checks only and create no runtime evidence.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/spatial-ai-entry-static-contract/executor.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/spatial-ai-entry-static-contract/tests"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/synthetic-data-entry-static-contract/executor.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/synthetic-data-entry-static-contract/tests"

# This first static qualification tranche is isolated and non-advancing. It
# validates 24 bounded candidate cases but cannot create runtime evidence or
# mark an oracle executor-ready.
python3 "${thor_local_root}/qualification/static-cases/static_case_executor.py" validate
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/static-cases/tests" \
  -p 'test_static_case_executor.py' -v

# Ten deterministic file-only executors are integrated into the corresponding
# live planning requirements. They remain bounded static-subset evidence: no
# full capability oracle is executable and no runtime evidence can be created.
python3 "${thor_local_root}/qualification/executor-cases/executor.py" validate
python3 "${thor_local_root}/qualification/executor-cases/executor.py" \
  run-all >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/executor-cases/tests" \
  -p 'test_executor.py' -v

# The source-contract tranche is the second deterministic planning successor.
# Its immutable receipt remains replayed by the third successor. The old
# source-locked execution is intentionally not repeated after the adapter
# changes those reviewed LVS sources. No runtime evidence is created and no
# full capability oracle advances.
python3 "${thor_local_root}/qualification/source-contract-cases/executor.py" validate

# The fourth calibration successor and its predecessor receipts are immutable
# and are verified above by exact predecessor tree/artifact identity. Replaying
# them against the additive CPU compiler/ledger would falsify their old output.

# Six additional planning requirements have isolated, source-locked checks.
# Five match and the search-upload status contract remains an explicit 400/415
# mismatch. This package cannot alter the 27 integrated live bindings.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave3/executor.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/planning-requirement-executors-wave3/tests"

# A second nonadvancing planning audit selects six of the 77 requirements not
# previously covered by a planning executor package. Five source contracts
# match and the Alerts Qwen example remains an explicit source mismatch.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave4/executor.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/planning-requirement-executors-wave4/tests"

# Planning Waves 5-12 remain exact 276-capability historical selections. Their
# package trees, inventories, embedded locks, and non-advancing boundary are
# verified by the fixed-predecessor successor above, not relabelled as 277-era.

# The first UI runtime-contract package is an immutable pre-source-claim
# snapshot. Its official-ledger lock is historical, so do not replay it against
# the layered current live state; it remains non-advancing and unmodified.

# The 20-row runtime-execution-bounds audit is a predecessor-bound historical
# package. Its exact tree and direct core artifacts are verified by the tooling
# successor above rather than replayed against the 289-oracle denominator.

# Nine local runtime rows now have strict, deterministic candidate-input
# contracts. The static tier runs read-only validation and mocked tests only;
# it does not invoke FFmpeg, generate media, start a service, or create runtime
# evidence. Warehouse data remains excluded.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/local20-fixture-pack/fixture_pack.py" \
  validate >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/local20-fixture-pack/tests"

# The architecture-gap contract audit is an immutable pre-source-claim
# snapshot. Its official-ledger lock is historical, so do not replay it against
# the layered current live state; it remains non-advancing and unmodified.

# The clean-room calibration backend is an immutable pre-source-claim package.
# Its architecture/capability source lock is historical, so do not replay its
# tests against the layered current live state; it remains unmodified.

# The opt-in browser derivative is source-only. Inspection verifies its exact
# upstream/overlay/proxy/Compose locks and focused tests exercise deterministic
# materialization without building an image or starting a service.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/legacy-calibration/browser-integration/materialize.py" \
  inspect >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/legacy-calibration/browser-integration/tests"

# The calibration-schema executor's contract hash is embedded in the immutable
# fourth-successor receipt. Its exact predecessor identity is verified above;
# it is not replayed against the additive CPU ledger.

# The fixed-topology scaling audit is an immutable pre-source-claim snapshot.
# Its official-ledger lock is historical, so do not replay it against the
# layered current live state; it remains non-advancing and unmodified.

# The Thor Alert derivative accepts NVIDIA's documented Incident `analytics`
# name as a lossless alias for released protobuf field 7 `analyticsModule`,
# rejects conflicting dual spellings, and preserves the wire tag on roundtrip.
# This source-level test uses no broker, endpoint, service, or lifecycle action.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${repo_root}/services/alert" \
  python3 -m pytest -q -p no:cacheprovider \
  "${repo_root}/services/alert/test/test_schema_util_nvschema_alias.py"

# Dependency-free Alert source tests prove the Thor-only verdict gate, image
# error coercion, terminal job-store ownership, publish gating, offline sink
# receipts, and isolated route semantics without importing the full app or
# performing network, broker, service-lifecycle, or model I/O.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${repo_root}/services/alert" \
  python3 -m pytest -q -p no:cacheprovider \
  "${repo_root}/services/alert/test/test_direct_media_pluggable_parser_ft.py" \
  "${repo_root}/services/alert/test/test_image_error_info_coercion_ft.py" \
  "${repo_root}/services/alert/test/api/test_terminal_job_store.py" \
  "${repo_root}/services/alert/test/api/test_terminal_publish_gate.py" \
  "${repo_root}/services/alert/test/api/test_sink_delivery_receipts_offline.py" \
  "${repo_root}/services/alert/test/api/test_verification_routes_isolated.py"

# The four systems static-executor packages above are immutable pre-source-
# claim snapshots. Their official-ledger locks are historical, so do not replay
# them against the layered current live state; they remain unmodified.

# The exact VSS 3.2.1 Cosmos3 Nano artifact/default/served-ID chain and the
# Smart City three-version mismatch are checked through locked product files.
# This process-free subset leaves all three canonical oracles open and requires
# neither a model artifact nor the optional Warehouse sample.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/headline-cosmos-smartcity-static-executor/executor.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/headline-cosmos-smartcity-static-executor/tests"

# The August 1 documentation observation is metadata-only. It independently
# revalidates the immutable July 31 172-page/26,449-edge baseline and records
# stable sizes/topology plus universal raw-hash drift, with semantic equality
# explicitly unproven and no relabel, feature promotion, or runtime evidence.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/official-vss-doc-drift-observation/validate_observation.py"
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/official-vss-doc-drift-observation/tests"

# Shared future runtime-evidence primitives are checked only through their
# static contract and fake in-memory transport/resource self-test. The library
# constructs no network opener and performs no host, Docker, subprocess,
# service-lifecycle, or live runtime action in this milestone.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/runtime-evidence-common/common.py" \
  check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/runtime-evidence-common/common.py" \
  self-test >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/runtime-evidence-common/test_common.py"

# The first candidate-alerts runtime-evidence package is an immutable old-
# oracle snapshot. Its source lock is historical and is not replayed here.

# The completion scaffold separately models the final confirmed/rejected
# verdict, exact media/server identity, terminal sink receipt, bounded query,
# proof-gated ownership, and late-publication blocker. Only its inert plan and
# fake-only tests run here; no execute command or network path exists.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-alerts/collector.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-alerts/test_collector.py"

# The Search documents/bboxes runtime-evidence package is likewise a frozen
# predecessor snapshot. The tooling successor verifies its exact tree and core
# artifact identities without relabelling or replaying the old denominator.

# The VIOS playback-remediation candidate is an immutable old-oracle snapshot.
# Its source lock is historical and is not replayed here.

# Default host-preflight mode is an inert, inspectable plan. Live inspection is
# intentionally excluded from this static wrapper.
python3 "${thor_local_root}/qualification/host-preflight/preflight.py" \
  plan >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/host-preflight/tests" \
  -p 'test*.py' -v

# Four platform prerequisite oracles have a source-locked, sanitized host
# evidence collector. The unified static milestone executes only its inert
# plan and injected/mocked tests; live inspection requires a separate exact
# acknowledgement and is not performed here.
python3 "${thor_local_root}/qualification/host-prerequisite-evidence/collector.py" \
  plan >/dev/null
python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/host-prerequisite-evidence/tests"

# The cgroupfs remediation defaults to an inert plan. Its mocked transaction
# suite exercises execute/rollback/recover safety without inspecting or
# changing this host, Docker, systemd, or any container lifecycle state.
python3 "${thor_local_root}/qualification/host-cgroupfs-remediation/remediate.py" \
  plan >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/host-cgroupfs-remediation/tests"

# Five documented API exclusions resolve to seven independently addressable
# REST surfaces. Six have exact static descriptors totaling 80 operations;
# legacy calibration remains an authoritative-unknown server denominator with
# only L>=14 client evidence. This check cannot claim complete-product totals.
python3 "${thor_local_root}/qualification/extended-api-surface-contracts/validate.py"
python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/extended-api-surface-contracts/tests"

# The original advertised-entry-gaps package is an immutable old-ledger
# snapshot. Its exact successor receipt is observed by the drift package below.

# The published 74-successor and its Waves 1-7 inputs are immutable candidate
# evidence. Their implementation locks predate current product changes, so the
# live wrapper verifies exact historical identities and observes source drift
# without replaying the stale-current compiler or guarded dispatcher. The
# original receipt remains the downstream guarded-observer identity.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-74-drift-observation-successor/validator.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/advertised-entry-executors-74-drift-observation-successor/tests"

# Advertised-entry Waves 1-7 remain immutable 87-gap candidate snapshots. Their
# exact trees, inventories, predecessor chains, 125 source locks, and 83-way
# candidate/blocker partition are identity-verified by the drift observer above.
# They are not replayed against the current 74-gap denominator.

# The separate detection-mAP candidate is an immutable old-gap snapshot. Its
# exact predecessor tree is verified by the tooling successor above; the new
# canonical entry remains runtime-unqualified and is not replayed here.

# Wave eight upgrades the two LVS MCP literals from source-shape candidates to
# a real in-process production-server subset. Its two IDs remain in the current
# 74-gap plan, so its live locks are refreshed while its old Wave3/Wave7
# predecessor hashes stay frozen. Runtime transport/inference remains open.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-wave8/executor.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/advertised-entry-executors-wave8/tests"

# Bind the two passing Wave 8 production-code subsets to their exact selected
# Metadata-500 oracle rows. The selected v2 oracle document remains byte-for-
# byte identical; the separate annotation index retains every runtime blocker,
# an unmet operator gate, and zero promotion or runtime evidence.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/successor-500-executable-subsets-wave1/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/successor-500-executable-subsets-wave1/tests"

# The old four-entry external-attestation package includes the now-canonical
# AWS/GCS boundary and is therefore a historical snapshot. Its exact predecessor
# tree is verified by the tooling successor instead of being relabelled here.

# The two Search scale literals have an exact, Warehouse-free future workload
# plan: progressive 2/4/8/16 plus a separate operator-approved 100-stream run.
# This static command compiles only identities, gates, evidence shape, aborts,
# and cleanup; it starts no publisher, API request, service, or container.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/search-scale-qualification-plan/plan.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/search-scale-qualification-plan/tests"

# The service-binding, runtime-lanes, advertised-entry-coverage, and remaining-
# candidate compilers are immutable old-ledger snapshots. Their successor
# identities are consumed by the current 500-candidate chain below; the stale
# live-source replays are intentionally omitted.

# Three candidate-only successor inputs make the future 289-to-500 oracle
# transition explicit without changing the live ledgers. They preserve all 289
# current oracle states/evidence, adapt all 211 exact semantic contracts, expand
# the protocol design from 7 to 30 cases with all 23 additions non-activating,
# and bind exact workloads for the 41 API and 19 deployment candidates.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-oracle-adapter/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-oracle-adapter/tests"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/protocol-cases-v2-candidates/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/protocol-cases-v2-candidates/tests"
# The original remaining-entry-workloads package is an immutable old-ledger
# snapshot and is consumed by the current successor chain without replay.

# The isolated oracle successor preserves the 289 live rows exactly, then
# appends all 211 candidate contracts in manifest-pointer order. The ledger
# successor binds that same 500-row order to an exact-title manifest and
# capability-ledger projection. Both remain candidate-only: evidence and
# promotions stay empty, while nine family aggregates and eight acceptance
# coverage records remain explicit live-merge blockers.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/oracle-500-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/oracle-500-successor/tests"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/ledger-500-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/ledger-500-successor/tests"

# Two isolated metadata successors close the projected merge blockers without
# touching live parity files. The manifest projection applies six policy-valid
# aggregate fields and preserves three external_optional family boundaries; the
# acceptance projection appends exactly eight missing scenario links. Together
# they leave zero policy-correct aggregate or acceptance-coverage gaps, but do
# not merge or promote any capability.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/manifest-500-aggregate-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/manifest-500-aggregate-successor/tests"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/acceptance-500-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/acceptance-500-successor/tests"

# The composition proof binds the final ledger, oracle, policy-valid manifest,
# and acceptance successors. The authoritative validator must accept exactly
# 500 capabilities / 55 families / 47 discrepancies with zero aggregate or
# acceptance gaps. Live predecessor files remain at 289, candidate evidence is
# empty, and live/oracle/runtime migration remains explicitly blocked.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/metadata-500-composition-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/metadata-500-composition-successor/tests"

# The versioned migration and activation rebase packages bind the current
# source-claim/Alerts ledger, selected Metadata-500 projection, and immutable
# historical package identities without replaying the stale applied packages.
# They perform no canonical write and preserve zero evidence or promotion.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/live-metadata-500-migration-rebase-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/live-metadata-500-migration-rebase-successor/tests"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/live-metadata-500-activation-rebase-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/live-metadata-500-activation-rebase-successor/tests"

# The historical 289 descriptor remains immutable and binds the pre-layer live
# hashes, so it cannot be relabelled as authoritatively valid against the
# evolved 289-row documents. The activation rebase above preserves its exact
# descriptor/selector identities and rollback lineage without replaying it.
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/parity/tests/test_capability_oracles_v2.py"

# The candidate-only offline MV3DT observation and its immutable receipt are
# verified above at exact predecessor identity by the CPU multimedia successor.
# They are intentionally not replayed against the evolved current manifest.

# The four MV3DT advertised semantics have an exact-four custom-data admission
# plan and a strict future candidate-receipt validator. Static qualification
# executes only the inert plan and adversarial tests; no model, Docker, broker,
# service lifecycle, external receipt, or official state is touched.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/mv3dt-entry-oracles/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/mv3dt-entry-oracles/tests"

# The two Sparse4D advertised semantics similarly reuse the existing custom
# four-camera lane through an inert plan and strict candidate-receipt contract.
# The static tier runs no preflight, model, process, service, or lifecycle path.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/sparse4d-entry-oracles/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/sparse4d-entry-oracles/tests"

# The known-speech H.264/AAC fixture tool defaults to a write-free plan. Its
# static suite mocks the only two allowed local subprocesses and keeps the real
# FFmpeg integration opt-in, so this milestone creates no media or receipt.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/tiny-audio-fixture/fixture.py" plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/tiny-audio-fixture/tests"

# The audio-entry-oracles package is an immutable old-ledger/oracle snapshot.
# Its candidate contracts remain historical and are not replayed here.

# Preserve the historical 14 explicit, non-inheriting approval scopes. This
# predecessor compiler has no execute mode and takes no material action.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/runtime-approval-bundles/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/runtime-approval-bundles/tests"

# Preserve the historical v1 classification: 206 mapped, three static/non-
# activating, one contract conflict, and one scope gap. It grants no approval,
# admits or executes no candidate, and excludes Warehouse.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-approval-mapping-rebase-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-approval-mapping-rebase-successor/tests"

# The current additive approval successor preserves the historical 14-bundle
# prefix exactly and appends read-only firewall inspection followed by firewall
# configuration. It is an inert contract compiler: it grants no approval,
# consumes no receipt, performs no host/firewall action, and excludes Warehouse.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/runtime-approval-bundles-rebase-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/runtime-approval-bundles-rebase-successor/tests"

# This additive Sparse4D planning repair changes only the one objectively wrong
# candidate dependency from the MV3DT pipeline to the existing Sparse4D pipeline.
# It does not alter selected Metadata-500 files, grant approval, create evidence,
# execute a service, or use the Warehouse sample.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/sparse4d-candidate-dependency-repair-rebase-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/sparse4d-candidate-dependency-repair-rebase-successor/tests"

# The v2 approval classification preserves 209 historical rows and resolves the
# two former classification gaps through the checked 16-bundle vocabulary and
# Sparse4D repair. Its split is 208 mapped, three static/non-activating, and zero
# contract/scope gaps. All 211 rows remain receipt-free, not admitted, not
# executable, and runtime-evidence-empty; Warehouse remains excluded.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-approval-mapping-rebase-successor-v2/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-approval-mapping-rebase-successor-v2/tests"

# The admission-receipt successor binds all 211 ordered candidates to their
# exact mapping, oracle, Metadata-500, and 16-bundle identities. It validates
# only the canonical empty receipt state: 204 local/alternate candidates remain
# blocked on exact execution bindings and receipts, four external candidates
# cannot establish local admission, and three static entries are runtime N/A.
# It has no receipt-consumption, write, action, or execution mode; Warehouse is
# excluded and receipts/admissions/executable candidates remain zero.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-admission-receipts-rebase-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-admission-receipts-rebase-successor/tests"

# The execution-binding registry source-locks all 208 mapped candidates and
# keeps semantic, planning-action, observer, and lane projections distinct from
# authoritative executable bindings. It directly checks 235 semantic files and
# 26 active-lane profile/Compose files. Every executor, service/profile,
# cleanup/rollback, postcondition, and evidence binding remains null or empty;
# admission-grade bindings remain zero and Warehouse remains excluded.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-execution-binding-registry-rebase-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-execution-binding-registry-rebase-successor/tests"

# The candidate authority successor freezes an empty, non-consuming trust
# boundary and a design-only DSSEv1/Ed25519/JCS receipt-envelope contract. It
# has zero roots, keys, policies, revocations, receipts, accepted/consumed
# records, or spent-ledger entries and no sign/verify/write/execute mode. Hashes
# provide integrity only; no candidate becomes admitted or executable.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-authority-registry-rebase-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-authority-registry-rebase-successor/tests"

# Wave 1 resolves the two strongest LVS/MCP candidates to exact static
# `lvs-server`/`vss-lvs` Thor service/profile wiring while retaining every
# deployed-action, transport, real-video, cleanup, evidence, authorization,
# and runtime blocker. It remains non-admission-grade and performs no lifecycle
# or network action; Warehouse is excluded and cloud inference is not required.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-execution-bindings-wave1-rebase-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-execution-bindings-wave1-rebase-successor/tests"

# The terminal LVS MCP workload repair binds the finalized 13-tool production
# catalog and current mapping/execution identities while retaining an unresolved
# candidate-scoped cleanup blocker. Check and tests are static and read-only.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-mcp-candidate-workload-repair-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-mcp-candidate-workload-repair-successor/tests"

# The divergent VSS 3.3.0 development line remains an isolated curated
# prerelease watchlist. Its 14 selected candidate-static families and 40 exact
# remote pointers define no authoritative full-diff denominator and make no
# exhaustive-coverage claim. Validation uses no network or local develop
# checkout; all runtime states stay unexecuted, the Warehouse sample remains
# excluded, and stale Thor Edge 4B remains an explicit conflict.
python3 "${thor_local_root}/qualification/prerelease-watchlist/validator.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/prerelease-watchlist/tests"

# The adjacent prerelease denominator exhaustively locks all 499 develop-side
# commits and 109,058 develop path/status records plus two main-only divergence
# exceptions. Its head-delta record separately classifies the one post-nightly
# Hermes/NemoClaw commit. This is commit/path accounting and a bounded semantic
# record, not complete feature semantics, implementation, or runtime parity.
python3 "${thor_local_root}/qualification/prerelease-denominator/validator.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/prerelease-denominator/tests"

# The local Qwen alternate model contract is checked only in its inert plan
# mode. Runtime HTTP probes require a separate exact acknowledgement.
python3 "${thor_local_root}/qualification/local-alternate-models/qualify.py" \
  >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/local-alternate-models/tests"

python3 "${thor_local_root}/rt-vlm/model_matrix.py" \
  --matrix "${thor_local_root}/rt-vlm/model-matrix.json" \
  --artifact-lock "${thor_local_root}/rt-vlm/artifacts.lock.json" \
  --repo-root "${repo_root}" \
  validate
python3 -m unittest discover \
  -s "${thor_local_root}/rt-vlm/tests" -v

python3 "${thor_local_root}/agent-models/validate.py"
python3 -m unittest discover \
  -s "${thor_local_root}/agent-models/tests" -v

# Deliberately use only the static Edge contract gate. The audit,
# render-command, and readiness modes concern staged or running artifacts.
python3 "${thor_local_root}/official-edge/official_edge.py" static
python3 -m unittest discover \
  -s "${thor_local_root}/official-edge/tests" -v

# Official-edge readiness defaults to an inert plan. Its tests enforce exact
# artifact-tree verification and allowlisted read-only Docker inspection, but
# this static wrapper performs no host inspection or lifecycle operation.
python3 "${thor_local_root}/qualification/official-edge-readiness/readiness.py" \
  plan >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/official-edge-readiness/tests" -v

printf 'PASS: unified static-only Thor parity milestone\n'
