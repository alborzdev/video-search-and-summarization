#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Unified static-only Thor parity milestone. This script must not start, stop,
# deploy, pull, build, or download anything.
set -euo pipefail

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
python3 -m unittest discover \
  -s "${thor_local_root}/qualification/protocol-cases/tests" \
  -p 'test_protocol_cases.py' -v

# Wave 2 remains an inert proposal package and does not change the live ledger.
python3 "${thor_local_root}/parity/candidates/wave2/validate_candidate.py" --report
python3 -m unittest discover \
  -s "${thor_local_root}/parity/candidates/wave2" \
  -p 'test_candidate.py' -v

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
