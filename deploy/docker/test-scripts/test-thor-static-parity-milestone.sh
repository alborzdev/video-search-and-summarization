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

# Thor's RT-Embed derivative must reuse the already verified Cosmos-Embed
# cache and fail before any git/Hugging Face/NGC downloader on a cache miss.
# These source/static tests perform no registry, model, Docker, or network I/O.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="${repo_root}/services/rtvi/rt-embed/src" \
  python3 -m pytest -q -p no:cacheprovider \
  "${repo_root}/services/rtvi/rt-embed/tests/rtvi_embed/test_ngc_model_downloader.py" \
  "${thor_local_root}/models/tests/test_rtvi_embed_offline.py"

# The old Search readiness package is immutable pre-current-runtime provenance
# whose source locks intentionally predate the evolved Search implementation.
# Validate the sealed current Content-Type run and its canonical evidence
# projection instead; these checks perform no transport or lifecycle action.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/search-content-type-current-runtime-successor/verify.py" \
  >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/search-content-type-current-runtime-successor/tests"

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

# The Spatial AI entry-level contract still binds its exact checked-in
# implementation and CLI surfaces. The original Synthetic Data static contract
# is an immutable pre-promotion snapshot; the terminal current successor below
# replaces its live replay with exact runtime receipts and source controls.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/spatial-ai-entry-static-contract/executor.py" \
  --check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/spatial-ai-entry-static-contract/tests"

# This first static qualification tranche is isolated and non-advancing. It
# validates 24 bounded candidate cases but cannot create runtime evidence or
# mark an oracle executor-ready.
python3 "${thor_local_root}/qualification/static-cases/static_case_executor.py" validate
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/static-cases/tests" \
  -p 'test_static_case_executor.py' -v

# The original ten deterministic file-only executors are frozen planning
# provenance. One row has since advanced through current LVS runtime evidence,
# so the package correctly refuses replay against the evolved live ledger. Its
# remaining current static bindings are validated by the canonical oracle
# compiler and tests above; do not relabel or mutate the historical package.

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
# Five retain their historical source identities. The Search upload assertions
# now all match HTTP 400, while its immutable pre-fix source lock deliberately
# reports drift; the current runtime successor owns promotion. This historical
# package cannot alter the 27 integrated live bindings.
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

# The headline Cosmos/Smart-City source package is immutable pre-current Edge
# provenance and its official-edge Compose lock intentionally predates the
# qualified local model lane. The current Official Edge contract is validated
# later in this wrapper; do not replay or relabel the historical package.

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

# The three Base semantic successor packages are immutable pre-current-ledger
# planning provenance. Their admission/source locks intentionally fail against
# the evolved live metadata, so they are preserved without replay or relabel.
# No Base runtime claim is implied by this static wrapper.

# Video Management now has a concrete regular-Playwright candidate for an
# operator-preexisting numeric-loopback CDP browser and deployed APIs. Static
# qualification syntax-checks the client and runs only inert/mock validation;
# it never launches or connects to a browser, opens a socket, uploads media,
# or mutates a resource. Complete Playwright package trees are digest-pinned;
# Browser-plugin, live-receipt, RTSP-readiness, and canonical-envelope gaps
# remain explicit.
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

# The intermediate LVS HTTP and Agent-session successors are frozen against
# earlier live metadata/source identities and fail closed after later LVS
# promotions. Preserve them as provenance; current LVS packages below remain
# the static acceptance surface.

# The LVS closure successor adds live five-tool discovery plus exact VST
# stored-byte/duration checks, ES caption-range provenance, event/object-
# correlated CA-RAG retrieval,
# and full timeline preservation. Its plan and fake transport tests are inert.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-semantic-runtime-closure-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-semantic-runtime-closure-successor/tests"

# The provider-free LVS multi-video oracle validates ordered per-source
# Markdown/PDF correlation, planted-event isolation, and reversed-completion
# restoration without rendering its recipes or calling a provider. Its JSON
# plan and tests are file-only, non-promoting, and Warehouse-free.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-multi-video-artifact-oracle-successor/executor.py" \
  --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-multi-video-artifact-oracle-successor/tests"

# The LVS focus matrix adds object, event, scenario, combined-target,
# distractor-control, and absent-focus semantics under the frozen 14-action
# envelope. Only its inert plan and fake transport tests run here.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/lvs-focus-semantic-matrix-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/lvs-focus-semantic-matrix-successor/tests"

# The original Search semantic executor is now an immutable pre-readiness
# snapshot. Its exact source and contract identities are checked by the current
# Search readiness successor near the start of this wrapper, so the stale live
# plan is not replayed against the promoted metadata plane.

# The Search fixture provisioner is immutable pre-current-runtime provenance.
# Its old source identity now fails closed; the sealed Search backend and
# Content-Type packages supersede it without mutating this historical tree.

# The companion Search RTSP archive candidate binds one reviewed local source
# through Agent add, VST/Search readiness, exact identity-preserving delete,
# unrelated-control preservation, and delayed no-reappearance. Only its inert
# plan and fake opener tests run here.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/search-rtsp-archive-lifecycle-successor/executor.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/search-rtsp-archive-lifecycle-successor/tests"

# This selected-row registry reports the current semantic transport boundary
# without binding or promoting any of the five canonical Metadata-500 rows.
# Its compiler and tests are static and source-locked; live receipts remain
# zero and the Warehouse sample remains excluded.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/semantic-executor-bindings-current/compiler.py" \
  check >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/semantic-executor-bindings-current/tests"

# The Wave-2, advertised Wave-3, and semantic-closure registries are immutable
# pre-promotion views. Their old null/readiness and source locks intentionally
# reject the evolved Search/LVS metadata. The current canonical registry above
# remains replayed; historical successors remain unmodified provenance.

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

# The terminal Alerts successor binds server-generated job correlation IDs,
# completed sink receipts, cancellation terminality, and exact config cleanup.
# Its default plan and injected fake-transport tests perform no service,
# network, broker, media, or Warehouse action and create no runtime receipt.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/candidate-alerts-terminal-runtime-evidence-successor/collector.py" \
  plan >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/candidate-alerts-terminal-runtime-evidence-successor/test_collector.py"

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
# while resolving all 182 row/source references through an exact seventeen-path
# overlay. It independently checks cancellation-aware Kafka publication and
# the 64-operation Agent inventory (44 historical + 12 Search + 8 released
# evaluation/async routes); evidence and promotion remain empty.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/advertised-entry-executors-71-current-source-rebase-successor/validator.py" \
  --check --json >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/advertised-entry-executors-71-current-source-rebase-successor/tests"

# The former Metadata-500 overlay audit is an immutable pre-Synthetic-Data
# selector snapshot. Its locked artifacts remain checked in for provenance but
# are not replayed as the current selector authority.

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

# The Warehouse-free Search scale workload plan is immutable pre-current-API
# provenance. Its Agent operation-inventory lock intentionally predates the
# current Search routes, so it is preserved without replay or relabel; scale
# remains explicitly runtime-unqualified.

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
# The MV3DT and Sparse4D entry-oracle packages are immutable pre-promotion
# manifest snapshots. MV3DT's exact historical receipt/source locks are
# revalidated by the canonical capability-oracle suite above; Sparse4D's exact
# repair lineage is preserved downstream. Neither stale live plan is replayed.

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

# The finalized approval and offline-verifier log-driver successors are
# immutable historical launcher snapshots. Their `thor-local.sh` lock predates
# the evolved current launcher, so both remain preserved without replay.

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

# The non-official local Qwen alternate is an immutable pre-current-artifact
# snapshot. Its artifact-lock digest now fails closed, so it remains preserved
# without replay and cannot promote an official capability.

python3 "${thor_local_root}/rt-vlm/model_matrix.py" \
  --matrix "${thor_local_root}/rt-vlm/model-matrix.json" \
  --artifact-lock "${thor_local_root}/rt-vlm/artifacts.lock.json" \
  --repo-root "${repo_root}" \
  validate
python3 -m unittest discover \
  -s "${thor_local_root}/rt-vlm/tests" -v

python3 "${thor_local_root}/agent-models/validate.py"
python3 "${thor_local_root}/agent-models/verify_thor_requirements.py" static
python3 -m unittest discover \
  -s "${thor_local_root}/agent-models/tests" -v

# The semantic collector successor is immutable pre-current-source provenance;
# its source lock now fails closed and the current canonical Edge receipt is
# validated through the official capability ledger instead of replaying it.

# The Warehouse-free runtime campaign is a frozen composition of earlier
# semantic contracts. Its predecessor lock intentionally rejects evolved or
# user-owned contract bytes, so it remains preserved without replay.

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

# SpatialAI and Agent Evaluation promotion compilers are immutable historical
# records that lock their publication-time canonical inputs. The active Agent
# Evaluation selector has advanced beyond both snapshots, so current metadata
# coherence is validated through the generic selector/schema verifier below,
# not by replaying a stale historical publisher against later source rebases.
# The live acceptance compiler is a separate current-state consumer. Compile
# its inert Phase 0 plan and run its safety/coverage tests so REST or MCP
# operation drift cannot leave the advertised 500-capability plan stale.
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/qualification/acceptance.py" >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/qualification/tests/test_acceptance.py" \
  "${thor_local_root}/qualification/tests/test_acceptance_executor.py"

PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  "${thor_local_root}/parity/metadata_sets/tests" \
  "${thor_local_root}/parity/tests/test_verify_metadata_set.py"
PYTHONDONTWRITEBYTECODE=1 python3 \
  "${thor_local_root}/parity/verify_metadata_set.py" --json >/dev/null

printf 'PASS: unified static-only Thor parity milestone\n'
