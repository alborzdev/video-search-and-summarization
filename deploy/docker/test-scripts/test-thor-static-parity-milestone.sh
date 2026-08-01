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

# The 172-page recursive fixed-point lock detects raw response-body drift only;
# a byte match is not proof of correct semantic extraction or Thor implementation.
python3 "${thor_local_root}/parity/source-lock/source_lock.py" validate
python3 -m unittest discover \
  -s "${thor_local_root}/parity/source-lock/tests" \
  -p 'test_source_lock.py' -v

# Wave 3 coverage is immutable extraction provenance. Its API-inventory input
# predates the Thor-local LVS adapter, so do not relabel or replay it against
# the evolved live contract. The third successor digest-checks the historical
# merge outputs; current 18/13 API coverage is validated by the contract tier.

# The recursive crawl proves the reviewed VSS 3.2.1 documentation graph reached
# a fixed point. The family candidates remain inert extraction proposals: they
# cannot claim runtime qualification or make excluded sample data mandatory.
python3 "${thor_local_root}/parity/candidates/wave3/recursive-coverage/validate_recursive_coverage.py" \
  --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave3/recursive-coverage/tests" \
  -p 'test_recursive_coverage.py' -v

python3 "${thor_local_root}/parity/candidates/wave3/agent-smartcity/validate_candidate.py" \
  --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave3/agent-smartcity" \
  -p 'test_candidate.py' -v

python3 "${thor_local_root}/parity/candidates/wave3/systems/validate_candidate.py" \
  --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave3/systems/tests" \
  -p 'test_candidate.py' -v

python3 "${thor_local_root}/parity/candidates/wave3/calibration-warehouse/validate_candidate.py" \
  --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave3/calibration-warehouse" \
  -p 'test_candidate.py' -v

# The bundle resolves cross-package source IDs and enrichments before any live
# merge. It is planning-only and must remain bound to the exact reviewed inputs.
python3 "${thor_local_root}/parity/candidates/wave3/bundle/validate_bundle.py" --json
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave3/bundle" \
  -p 'test*.py' -v
python3 "${repo_root}/deploy/docker/thor-local/parity/candidates/wave3/bundle/merge_live.py" --report

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
python3 "${thor_local_root}/qualification/lvs-mcp-static-adapter-integration/integrate_live.py" \
  validate-predecessor
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/executor-cases/tests" \
  -p 'test_executor.py' -v

# The source-contract tranche is the second deterministic planning successor.
# Its immutable receipt remains replayed by the third successor. The old
# source-locked execution is intentionally not repeated after the adapter
# changes those reviewed LVS sources. No runtime evidence is created and no
# full capability oracle advances.
python3 "${thor_local_root}/qualification/source-contract-cases/executor.py" validate

# The live-current third static successor preserves the immutable LVS 13-vs-9
# upstream discrepancy while wiring four Thor-local file-management tools. It
# also binds two deterministic offline MV3DT observations to bounded oracle
# subsets. Neither integration creates runtime evidence or a promotion.
python3 "${thor_local_root}/qualification/lvs-mcp-static-adapter-integration/integrate_live.py" \
  validate
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/lvs-mcp-static-adapter-integration/tests" \
  -p 'test*.py' -v

# Six additional planning requirements have isolated, source-locked checks.
# Five match and the search-upload status contract remains an explicit 400/415
# mismatch. This package cannot alter the 26 integrated live bindings.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave3/executor.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/planning-requirement-executors-wave3/tests"

# A second nonadvancing planning audit selects six of the 78 requirements not
# previously covered by a planning executor package. Five source contracts
# match and the Alerts Qwen example remains an explicit source mismatch.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave4/executor.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/planning-requirement-executors-wave4/tests"

# The third nonadvancing planning audit selects six Smart City contracts from
# the exact 72-row successor denominator. One matches and five preserve source
# gaps; all 84 live-open requirements remain unpromoted.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave5/executor.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/planning-requirement-executors-wave5/tests"

# The fourth nonadvancing planning audit selects six more Smart City source
# contracts from the exact 66-row remainder. Five documented mismatches and
# one external-optional boundary remain explicit; all 84 live-open planning
# requirements stay unpromoted and 60 remain without a planning candidate.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave6/executor.py" \
  --json >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/planning-requirement-executors-wave6/tests"

# The fifth nonadvancing planning audit checks three negative contracts, two
# configuration subsets, and one illustrative NvSchema consumer subset from
# the exact 60-row remainder. It leaves 54 unselected and all 84 live-open.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave7/executor.py" \
  --json >/dev/null
python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/planning-requirement-executors-wave7/tests"

# The sixth nonadvancing planning audit preserves six documented negative
# contracts from the exact 54-row remainder. It leaves 48 unselected and all
# 84 live-open requirements without promotion or runtime evidence.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave8/executor.py" \
  --json >/dev/null
python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/planning-requirement-executors-wave8/tests"

# The seventh nonadvancing planning audit checks one preserved negative, two
# configuration-only, and three protocol/source-only subsets from the exact
# 48-row remainder. It leaves 42 unselected and every runtime semantic open.
python3 "${thor_local_root}/qualification/planning-requirement-executors-wave9/executor.py" \
  --json >/dev/null
python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/planning-requirement-executors-wave9/tests"

# The eighth nonadvancing planning audit checks one preserved negative, one
# configuration-only, and four protocol/source-only subsets from the exact
# 42-row remainder. It leaves 36 unselected, excludes every Warehouse row, and
# keeps every one of the 84 live-open requirements unpromoted and evidence-free.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/planning-requirement-executors-wave10/executor.py" \
  --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/planning-requirement-executors-wave10/tests"

# The ninth nonadvancing planning audit checks one preserved negative, one
# configuration-only, and four protocol/source-only subsets from the exact
# 36-row remainder. It leaves 30 unselected, selects no Warehouse row, and
# keeps all 84 live-open requirements unpromoted and evidence-free.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/planning-requirement-executors-wave11/executor.py" \
  --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/planning-requirement-executors-wave11/tests"

# The tenth nonadvancing planning audit checks three protocol and three
# configuration subsets from the exact 30-row remainder. It leaves 24
# unselected, selects no Warehouse row, and keeps all 84 live-open requirements
# unpromoted and evidence-free.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/planning-requirement-executors-wave12/executor.py" \
  --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/planning-requirement-executors-wave12/tests"

# The first three still-open UI rows have a strict future browser/API receipt
# contract. Static qualification only compiles the inert plan and exercises its
# offline validator; it has no execute mode, calls no UI/API/browser/process,
# rejects mock-only evidence, and cannot advance a live state.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/ui-runtime-contracts/validator.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/ui-runtime-contracts/tests"

# The exact 20 non-Warehouse local-runtime rows have constructively derived
# request/action envelopes. This static compiler checks the deterministic,
# non-applied proposal only; canonical oracles remain open and unchanged.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/runtime-execution-bounds-audit/compiler.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/runtime-execution-bounds-audit/tests"

# Nine local runtime rows now have strict, deterministic candidate-input
# contracts. The static tier runs read-only validation and mocked tests only;
# it does not invoke FFmpeg, generate media, start a service, or create runtime
# evidence. Warehouse data remains excluded.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/local20-fixture-pack/fixture_pack.py" \
  validate >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/local20-fixture-pack/tests"

# Four architecture-blocked rows have exact source-locked implementation and
# future-acceptance contracts. Static checking rejects AMC/manual-calibration,
# SVG/Google, in-process-worker/scaling, and fixed-topology/scaling conflation;
# it performs no live, host, container, or lifecycle action.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/architecture-gap-contracts/validator.py" \
  check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/architecture-gap-contracts/tests"

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

# Every manifest entry in a family with no capability rows remains an explicit
# open gap. The compiler proposes 87 literal entry oracles without promoting
# family-level status or requiring the excluded Warehouse sample bundle.
python3 "${thor_local_root}/qualification/advertised-entry-gaps/compiler.py" check
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/advertised-entry-gaps/tests" \
  -p 'test*.py' -v

# Eight of the 87 literal gaps have bounded, source-locked, in-memory candidate
# executors. Their observations remain subset-only: they do not mutate live
# acceptance, create runtime evidence, or close any official capability.
python3 "${thor_local_root}/qualification/advertised-entry-executors/executor.py" \
  >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/advertised-entry-executors/tests" \
  -p 'test*.py' -v

# A second disjoint advertised-entry tranche provides 21 more bounded helper
# and source-contract observations. Together the two candidate packages cover
# 29/87 entries and leave 58 open; neither package advances official status.
python3 "${thor_local_root}/qualification/advertised-entry-executors-wave2/executor.py" \
  >/dev/null
python3 -m pytest -q \
  "${thor_local_root}/qualification/advertised-entry-executors-wave2/tests"

# The third advertised-entry package code-locks the plan, manifest, both
# predecessors, and all selected sources. Its 23 source-shape candidates bring
# isolated coverage to 52/87; 35 lack even a candidate and all 87 remain
# unpromoted in live official status.
python3 "${thor_local_root}/qualification/advertised-entry-executors-wave3/executor.py" \
  >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/advertised-entry-executors-wave3/tests" \
  -p 'test*.py' -v

# Wave four checks the five remaining LVS live-workflow literals across the
# agent, LVS, RT-VLM, Kafka/Logstash, and CA-RAG source graph. Its AST and
# bounded-config observations bring isolated candidate coverage to 57/87 and
# leave 30 without a candidate; no live workflow or official status advances.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-wave4/executor.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s "${thor_local_root}/qualification/advertised-entry-executors-wave4/tests" \
  -p 'test*.py' -v

# Wave five checks six required-local VIOS codec/audio literals against exact
# source, configuration, ARM64 package-lock, and networkless-Dockerfile
# contracts. Candidate coverage reaches 63/87 and leaves 24 without a
# candidate; no media fixture, service, Docker, or official status advances.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-wave5/executor.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s "${thor_local_root}/qualification/advertised-entry-executors-wave5/tests" \
  -p 'test*.py' -v

# Wave six checks seven VIOS UI literals plus NAT generate/chat. Relative to
# its five formal predecessors it reaches 71/87 and leaves 16. Placeholder UI
# routes and all browser/API semantics remain explicitly unexecuted.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-wave6/executor.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover \
  -s "${thor_local_root}/qualification/advertised-entry-executors-wave6/tests" \
  -p 'test*.py' -v

# The separate detection-mAP candidate runs a deterministic tiny AP oracle and
# locks the production evaluator sources/tests, but does not claim the absent
# optional dependency stack or production evaluator executed. Combined with
# Wave six, aggregate candidate coverage is 72/87 with 15 still unselected.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/detection-map-static-executor/executor.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/detection-map-static-executor/tests"

# Wave seven partitions the final 15 entries after Wave six and detection-mAP:
# 11 receive digest-locked source/provenance candidates while Slack, AWS/GCS,
# RAG reporting, and FRAG retrieval remain external-attestation blockers.
# Aggregate candidate coverage is 83/87; all 87 official gaps remain open.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-wave7/executor.py" \
  --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/advertised-entry-executors-wave7/tests"

# The exact four external blockers have a credential-free future attestation
# contract. Static qualification compiles only the inert plan and adversarial
# validator tests; it contacts no Slack, cloud object store, RAG endpoint, or
# credential source and cannot promote a blocked entry.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/external-entry-attestations/plan.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/external-entry-attestations/tests"

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

# The lane compiler binds every one of the 500 advertised entries and all 276
# current capability oracles, while preserving entry-level semantic gaps,
# unresolved service bindings, and zero runtime evidence.
python3 "${thor_local_root}/qualification/runtime-lanes/runtime_lane_compiler.py" \
  --check
python3 -m pytest -q "${thor_local_root}/qualification/runtime-lanes/tests"

# Two custom-data MV3DT repository utilities execute twice against a tiny
# synthetic calibration. Their observations bind exact non-advancing oracle
# subsets only: no Warehouse sample, Docker, network, model, service lifecycle,
# runtime evidence, full-oracle readiness, or official-state promotion.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/offline-mv3dt-tools/executor.py" --check
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  "${thor_local_root}/qualification/offline-mv3dt-tools/tests"

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

# The adjacent prerelease denominator exhaustively locks all 498 develop-side
# commits and 109,052 develop path/status records plus two main-only divergence
# exceptions. This is commit/path accounting only: classification does not
# claim semantic feature completeness, local implementation, or runtime parity.
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
