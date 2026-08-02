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

# The Search readiness successor preserves the exact preceding LVS/RT-VLM
# current-contract layer while binding the later additive Search routes and
# reviewed API totals. The immutable predecessor is identity-checked, not
# replayed against the evolved API inventory.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/search-semantic-runtime-readiness-successor/executor.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/search-semantic-runtime-readiness-successor/test_executor.py"

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

# Base/HITL/UI and LVS now have authorization-gated semantic executor
# packages. The static milestone runs only their inert plans and fake/injected
# transport tests: no localhost request, browser, Docker action, model call,
# fixture write, cleanup, receipt promotion, or Warehouse input is permitted.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/base-semantic-runtime-evidence/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/base-semantic-runtime-evidence/tests"
# The additive Base successor replaces the predecessor's false namespace
# cleanup assumption with exact response-derived Markdown/PDF read, delete,
# and individual 404 checks. Its plan and fake transport tests remain inert;
# the corrected 11/12 full-lane envelopes are explicitly non-promoting.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/base-semantic-exact-cleanup-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/base-semantic-exact-cleanup-successor/tests"

# The corrected Base successor integrates each exact five/six-step semantic
# case with its report-object read/delete/404 workflow under honest 11/12
# bounds. Only its inert plan and fake transport tests run here; report-key
# preexisting absence, deployed receipts, canonical binding, and promotion
# remain explicitly unproven.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/base-semantic-full-envelope-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/base-semantic-full-envelope-successor/tests"

# Video Management now has a concrete regular-Playwright candidate for an
# operator-preexisting numeric-loopback CDP browser and mock APIs. Static
# qualification syntax-checks the client and runs only inert/mock validation;
# it never launches or connects to a browser, opens a socket, uploads media,
# or mutates a resource. Browser-plugin, transitive-tool, live-receipt, and
# canonical-envelope gaps remain explicit.
node --check \
  "${thor_local_root}/qualification/ui-video-management-playwright-successor/harness.mjs"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/ui-video-management-playwright-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/ui-video-management-playwright-successor/tests"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-semantic-runtime-evidence/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-semantic-runtime-evidence/tests"

# The additive LVS HTTP successor concretely exercises the bounded file,
# model, one-file summary, and exact cleanup subset. Only its inert plan and
# mock transport tests run here; Agent sessions, streams, dependencies,
# cancellation, runtime evidence, and promotion all remain open.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-semantic-runtime-http-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-semantic-runtime-http-successor/tests"

# The Agent/session successor supplies a direct numeric-loopback NAT WebSocket
# candidate for single/multi reports, ordered HITL state, persistence, and
# isolation plus exact six-object cleanup. Its static tier performs no upgrade,
# HTTP request, fixture access, or report generation; five-tool discovery,
# dependency/media identity, captions, quiescence, and complete unrelated-state
# proof remain open.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-semantic-runtime-agent-session-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-semantic-runtime-agent-session-successor/tests"

# Search now has a concrete, authorization-gated, exact-14 numeric-loopback
# candidate executor with exact owned-document cleanup. Static qualification
# runs only its source-locked plan and fake openers; it provisions no fixture,
# opens no socket, and creates no runtime evidence or promotion.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/search-semantic-runtime-evidence-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/search-semantic-runtime-evidence-successor/tests"

# The Search provisioning successor is an inert, source-locked blocker audit.
# It proves why current public VST/CV/Search/deletion APIs cannot safely create
# and roll back the predecessor's exact functional fixture; it implements no
# runtime transport and leaves the operator-preprovisioned fixture gap open.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/search-semantic-fixture-provisioning-blocker-successor/compiler.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/search-semantic-fixture-provisioning-blocker-successor/tests"

# This selected-row registry reports the current semantic transport boundary
# without binding or promoting any of the five canonical Metadata-500 rows.
# Its compiler and tests are static and source-locked; live receipts remain
# zero and the Warehouse sample remains excluded.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/semantic-executor-bindings-current/compiler.py" \
  check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/semantic-executor-bindings-current/tests"

# The additive wave-2 registry inventories the four new candidate packages
# without modifying the published registry or binding any selected row. Its
# checked artifact must preserve five canonical null bindings, zero receipts,
# zero promotions, Browser/tool provenance gaps, the Search fixture blocker,
# and Warehouse exclusion.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/semantic-executor-bindings-wave2-successor/compiler.py" \
  check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/semantic-executor-bindings-wave2-successor/tests"

# Wave 3 links exactly five advertised entries to partial executor candidates
# and five Search entries to the static fixture blocker. It deliberately
# preserves binding_kind:none, zero concrete/full bindings, zero admission,
# zero runtime receipts, zero promotions, and Warehouse exclusion.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-candidate-bindings-wave3-successor/compiler.py" \
  check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/advertised-candidate-bindings-wave3-successor/tests"

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

# The current-source 71-row rebase preserves the immutable historical receipt
# while resolving all 182 row/source references through an exact nine-path
# overlay. It independently checks cancellation-aware Kafka publication and
# the 56-operation NAT inventory; evidence and promotion remain empty.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-71-current-source-rebase-successor/validator.py" \
  --check --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/advertised-entry-executors-71-current-source-rebase-successor/tests"

# Advertised-entry Waves 1-7 remain immutable 87-gap candidate snapshots. Their
# exact trees, inventories, predecessor chains, 125 source locks, and 83-way
# candidate/blocker partition are identity-verified by the drift observer above.
# They are not replayed against the current 74-gap denominator.

# The separate detection-mAP candidate is an immutable old-gap snapshot. Its
# exact predecessor tree is verified by the tooling successor above; the new
# canonical entry remains runtime-unqualified and is not replayed here.

# Wave8 and its Metadata-500 subset are immutable pre-Search API snapshots.
# Their exact compiler and rebase identities are preserved by the Search
# readiness successor above rather than replayed against the evolved inventory.

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

# The candidate-oracle adapter is an immutable pre-cancellation input to the
# Metadata-500 projection. Its 211 candidate rows remain preserved by the
# downstream successor artifacts; it is not replayed against later live bytes.
# Protocol-v2 is an immutable pre-cancellation candidate. Its additive
# successor preserves the 29 non-Warehouse case/binding identities and binds
# the exact request-cancellation route without calling any endpoint.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/protocol-cases-v2-cancellation-successor/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/protocol-cases-v2-cancellation-successor/tests"
# The original remaining-entry-workloads package is an immutable old-ledger
# snapshot and is consumed by the current successor chain without replay.

# The original oracle/ledger 500 projections preserve the pre-cancellation 289
# live-row prefix and are immutable inputs to the metadata successors below.
# Their exact projected artifacts remain source-locked downstream; the current
# 289-row ledger/oracle pair is validated by the layered successor above.

# The manifest, acceptance, composition, migration-rebase, and activation-
# rebase Metadata-500 packages are frozen pre-cancellation snapshots. Their
# projected outputs remain inputs to the current candidate mapping/admission
# chain below, while the new layered and cancellation successors own validation
# of the evolved live contracts. None is replayed or relabelled against the
# current official/oracle/operation-manifest bytes.

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

# The historical 14-scope approval predecessor directly locks the older live
# launcher. Its exact contract/compiler identity and its later 16-scope
# extension are preserved transitively by the offline-verifier safety successor
# below, so the historical compiler is not replayed against evolved live bytes.

# The historical v1 classification directly locks the pre-cancellation
# canonical selector. Its exact artifact remains preserved downstream, but it
# is intentionally not replayed after the current atomic selector activation.

# The finalized 16-bundle approval successor is preserved by exact identity in
# the offline-verifier safety successor. Do not replay its old direct lock
# against the evolved live launcher. The new successor proves only that large
# attached verification archives bypass Docker container logging; it changes
# no approval, receipt, execution, model, or Warehouse state.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/offline-verifier-logdriver-successor/compiler.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/offline-verifier-logdriver-successor/test_compiler.py"

# The Sparse4D repair rebase likewise directly locks the historical selector.
# Later checked artifacts preserve its exact repair identity; do not replay it
# against the current selector.

# The v2 approval classification is also an exact historical-selector snapshot.
# Its 211 receipt-free, non-executable rows remain preserved by identity, not
# replayed against the current selector.

# The empty admission-receipt snapshot directly locks the historical selector.
# It remains immutable evidence of zero admissions/receipts and is not replayed.

# The execution-binding registry is an immutable pre-Search API snapshot. Its
# exact compiler and rebase identities are preserved by the Search readiness
# successor above; all 208 rows stay inert and no binding is promoted.

# The empty candidate-authority registry also directly locks the historical
# selector. Its zero-authority artifact stays preserved and is not replayed.

# Wave1 is an immutable pre-cancellation overlay. Its v2 successor preserves
# both candidate identities while rebinding repaired LVS MCP/server/handler
# sources; transport, cleanup execution, evidence, and admission remain open.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-execution-bindings-wave1-rebase-successor-v2/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-execution-bindings-wave1-rebase-successor-v2/tests"

# The terminal workload repair is an immutable pre-cancellation overlay. Its
# v2 successor binds the repaired MCP source and final 13-tool manifest while
# retaining its fail-closed cleanup blocker and zero runtime evidence.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-mcp-candidate-workload-repair-successor-v2/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-mcp-candidate-workload-repair-successor-v2/tests"

# The cancellation umbrella is an immutable pre-Search API snapshot. Its exact
# compiler and contract identities are preserved by the Search readiness
# successor above instead of replaying its stale aggregate inventory lock.

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

# The additive Aug. 2 successor advances that frozen denominator to the exact
# current NVIDIA develop/nightly tip: 500 commits and 109,059 develop path
# records. The sole delta is a Warehouse 2D Phoenix-profile fix; Warehouse is
# operator-excluded and Thor's older layout already has the equivalent profile.
# This validator is offline-only and creates no runtime evidence or promotion.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/prerelease-20260802-warehouse-exclusion-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/prerelease-20260802-warehouse-exclusion-successor/tests"

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
# Connected exact-artifact staging is also inert by default. The execute path
# requires a separate exact acknowledgement and is covered only by mocked
# tests in this wrapper.
python3 "${thor_local_root}/official-edge/stage_artifacts.py" plan >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/official-edge/tests" -v

# Official-edge readiness defaults to an inert plan. Its tests enforce exact
# artifact-tree verification and allowlisted read-only Docker inspection, but
# this static wrapper performs no host inspection or lifecycle operation.
python3 "${thor_local_root}/qualification/official-edge-readiness/readiness.py" \
  plan >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/official-edge-readiness/tests" -v

# Terminal metadata routing: reconstruct and byte-verify the exact current
# 289+211 post-cancellation/post-Search projection, then resolve and run both
# authoritative validator generations through the atomically selected set.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/metadata-500-current-cancellation-search-successor/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/metadata-500-current-cancellation-search-successor/tests" \
  "${thor_local_root}/parity/metadata_sets/tests" \
  "${thor_local_root}/parity/tests/test_verify_metadata_set.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/parity/verify_metadata_set.py" --json >/dev/null

printf 'PASS: unified static-only Thor parity milestone\n'
