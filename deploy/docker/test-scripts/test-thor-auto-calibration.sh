#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/../../.." && pwd)"
runner="${repo_root}/deploy/docker/scripts/thor-auto-calibration.sh"
tests="${repo_root}/deploy/docker/thor-local/auto-calibration/tests"
fixture_dir="$(mktemp -d /tmp/vss-thor-amc-test.XXXXXX)"
trap 'rm -rf -- "${fixture_dir}"' EXIT

python3 -m unittest discover -s "${tests}" -p 'test_*.py' -v

"${runner}" inventory > "${fixture_dir}/inventory.json"
python3 -c '
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
assert p["host_architecture"] == "aarch64"
assert p["images"]["ui"]["state"] == "locked"
assert p["images"]["backend"]["state"] in {"unstaged_unlocked", "present_unlocked", "locked"}
assert p["models"]["vggt"]["state"] in {"absent", "present_unlocked", "locked"}
' "${fixture_dir}/inventory.json"

media_dir="${fixture_dir}/media"
"${runner}" fixture "${media_dir}" --seconds 1 --size 320x180 --fps 10 > "${fixture_dir}/fixture-result.json"
"${runner}" validate-videos "${media_dir}" > "${fixture_dir}/video-result.json"
python3 -c '
import json, sys
p = json.load(open(sys.argv[1], encoding="utf-8"))
assert p["camera_count"] == 2
assert not p["api_upload_ready"]
assert all(v["codec"] == "h264" for v in p["videos"].values())
' "${fixture_dir}/video-result.json"

echo "Thor auto-calibration offline lane tests passed."
