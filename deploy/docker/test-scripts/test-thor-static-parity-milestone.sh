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

# Wave 3 binds the complete documentation-index denominator and keeps all
# still-untranscribed semantic pages explicit. It is an inert coverage audit,
# not evidence that the omitted capabilities are implemented or qualified.
python3 "${thor_local_root}/parity/candidates/wave3/coverage/validate_coverage.py" \
  --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave3/coverage/tests" \
  -p 'test_coverage.py' -v

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

# An isolated candidate tranche supplies ten deterministic, genuinely runnable
# file-only executors. Live planning flags remain unchanged; even a match cannot
# create runtime evidence or advance a capability to passed_current.
python3 "${thor_local_root}/qualification/executor-cases/executor.py" validate
python3 "${thor_local_root}/qualification/executor-cases/executor.py" \
  run-all >/dev/null
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/executor-cases/tests" \
  -p 'test_executor.py' -v

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

printf 'PASS: unified static-only Thor parity milestone\n'
