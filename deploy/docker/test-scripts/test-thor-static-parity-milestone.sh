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

# The exact-title successor anchors the published 76596c predecessor and
# freezes the earlier tooling successor at exact tree identity. It proves that
# all 289 existing capabilities map byte-identically to one advertised title,
# changing only the inventory denominator from 13/487/413 to 289/211/137.
# Historical executors are identity-verified rather than replayed against the
# evolved live denominator; no state or evidence advances.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/exact-title-entry-mapping-successor/compiler.py" \
  --check \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/exact-title-entry-mapping-successor/tests"

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

# The first three still-open UI rows have a strict future browser/API receipt
# contract. Static qualification only compiles the inert plan and exercises its
# offline validator; it has no execute mode, calls no UI/API/browser/process,
# rejects mock-only evidence, and cannot advance a live state.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/ui-runtime-contracts/validator.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/ui-runtime-contracts/tests"

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

# Four architecture-gap rows have exact source-locked implementation and
# future-acceptance contracts. Static checking rejects AMC/manual-calibration,
# SVG/Google, in-process-worker/scaling, and fixed-topology/scaling conflation;
# it performs no live, host, container, or lifecycle action.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/architecture-gap-contracts/validator.py" \
  check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/architecture-gap-contracts/tests"

# The provider-free clean-room calibration backend performs real bounded
# Cartesian/image/GIS/multi-camera validation, homography solving, geometry
# validation, deterministic export/readback, plus separate strict and VIOS-UI
# compatibility adapters. These local functional tests do not start either
# server or claim route/nav/proxy wiring, four pending transforms/uploads, the
# UI-to-strict-export bridge, or Thor runtime evidence.
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/legacy-calibration/tests"

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

# Two formerly fixed-topology architecture gaps now have an opt-in, default-
# inert scaling configuration. The validator and adversarial tests inspect only
# checked-in YAML/configuration: they invoke no Docker, network, subprocess, or
# lifecycle operation and cannot promote either row without live evidence.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/fixed-topology-scaling-config/validator.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/fixed-topology-scaling-config/tests"

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

# Three remaining Alert systems requirements now have one digest-locked static
# executor over the production DirectMedia, NvSchema, sink-receipt, and terminal
# job-store code. External clients are deterministic fakes; the result remains
# non-advancing with empty runtime evidence and excludes Warehouse data.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/systems-alert-completion-static-executor/executor.py" \
  --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/systems-alert-completion-static-executor/tests"

# All six Behavior Analytics systems rows now execute bounded real-product
# subsets for config, calibration, state/events, embeddings, and seven output
# routes through in-memory broker fakes. Import state is restored and full
# media, broker, lifecycle, runtime evidence, and Warehouse data remain out.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/systems-behavior-analytics-static-executor/executor.py" \
  --self-test >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  -W ignore::pydantic.warnings.PydanticDeprecatedSince20 \
  "${thor_local_root}/qualification/systems-behavior-analytics-static-executor/test_executor.py"

# The open NvSchema systems row now has a bounded real-product subset across
# the Behavior legacy converter, Spatial AI 3D loader, and Agent incident
# aliases. Two consumer limitations remain explicit; no broker, service,
# runtime evidence, official promotion, or Warehouse sample is involved.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/systems-nvschema-json-static-executor/executor.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/systems-nvschema-json-static-executor/tests"

# Search upload, LVS queue, and LVS format boundaries execute against real
# checked-in product code with deterministic fakes. The expected 400/observed
# 415 mismatch, absent handler-level serialization, and UI format gap remain
# non-advancing and require future live Thor evidence.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/systems-search-lvs-boundary-static-executor/executor.py" \
  --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/systems-search-lvs-boundary-static-executor/tests"

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

# The first shared-framework consumer binds the candidate-alerts planning row
# to an exact eight-request/eight-action future workflow. Static qualification
# runs only its inert plan and injected fake transport tests; config mutation,
# background VLM work, HTTP, and service lifecycle remain authorization-gated.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-alerts-runtime-evidence/collector.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-alerts-runtime-evidence/test_collector.py"

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

# The VIOS playback-remediation candidate binds the final canonical oracle and
# local20 metadata to an inert 8-request/9-action future plan. Its plain-data
# transcript simulation has no callback or live adapter and remains
# non-promoting; no media, network, process, service, or Warehouse data is used.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/systems-vios-playback-remediation/collector.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/systems-vios-playback-remediation/test_collector.py"

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

# Every still-unmapped advertised string in an empty or partial capability
# family remains an explicit gap: 69 entries across 13 zero-row families plus
# five in partial VIOS. The compiler proposes 74 literal oracles without
# promotion or Warehouse. Another 137 advertised strings retain family-only
# planning bindings and separately block literal completeness.
python3 "${thor_local_root}/qualification/advertised-entry-gaps/compiler.py" check
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/advertised-entry-gaps/tests" \
  -p 'test*.py' -v

# Advertised-entry Waves 1-7 remain immutable 87-gap candidate snapshots. Their
# exact trees, inventories, predecessor chains, 125 source locks, and 83-way
# candidate/blocker partition are verified by the CPU successor above. They are
# not replayed against the current 74-gap denominator.

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

# The four unresolved capability-to-service bindings have an authoritative
# negative audit. None of the contracts selects a unique runtime participant
# set, so the audit must keep all four open and forbid runtime-lane updates.
python3 "${thor_local_root}/qualification/service-binding-resolution/compiler.py" \
  --check
python3 -m pytest -q \
  "${thor_local_root}/qualification/service-binding-resolution/tests"

# The lane compiler binds every one of the 500 advertised entries and all 289
# current capability oracles. It records 289 exact capability-title mappings,
# while preserving all 211 missing entry-specific
# mappings, unresolved service bindings, and zero runtime evidence.
python3 "${thor_local_root}/qualification/runtime-lanes/runtime_lane_compiler.py" \
  --check
python3 -m pytest -q "${thor_local_root}/qualification/runtime-lanes/tests"

# The global coverage compiler partitions every advertised string exactly once:
# 276 exact pre-existing capability mappings, 13 exact canonical entry mappings,
# 74 explicit missing-entry gaps, and 137 family-only unreviewed entries. It
# preserves all 211 semantic blockers and contains no runtime evidence.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-coverage/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/advertised-entry-coverage/tests"

# Every one of the 211 remaining semantic blockers has a source-bound candidate
# capability and future-oracle contract. The compiler proves a schema-valid
# in-memory 500-capability / 500-exact-title projection, but it does not merge
# the live ledger, create runtime evidence, use the Warehouse sample, or promote
# any state.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/remaining-advertised-entry-candidates/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/remaining-advertised-entry-candidates/tests"

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
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/remaining-entry-workloads/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/remaining-entry-workloads/tests"

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

# The three audio advertised semantics have separate native-audio and local-ASR
# future evidence lanes. Static qualification runs only the inert plan and
# artifact-validator tests; it generates no fixture, loads no model, starts no
# ASR/VSS process, and cannot treat native Omni's ASR skip as transcript proof.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/audio-entry-oracles/oracle.py" \
  --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/audio-entry-oracles/tests"

# The remaining material actions are divided into 14 explicit, non-inheriting
# operator approval scopes. This compiler has no execute mode and the static
# suite proves it cannot inspect the host, contact a provider, download an
# artifact, invoke Docker, grant approval, or perform a lifecycle action.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/runtime-approval-bundles/compiler.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/runtime-approval-bundles/tests"

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
