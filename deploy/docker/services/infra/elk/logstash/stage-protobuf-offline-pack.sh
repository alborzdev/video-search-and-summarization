#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
pack_name="logstash-codec-protobuf-1.3.0-logstash-9.3.3.zip"
pack_dir="${script_dir}/offline-packs"
expected_checksum="${pack_dir}/${pack_name}.expected.sha256"
temporary_dir="$(mktemp -d -t vss-logstash-pack.XXXXXXXX)"
trap 'rm -rf -- "${temporary_dir}"' EXIT

docker build \
  --pull=false \
  --file "${script_dir}/Dockerfile.prepare-protobuf-offline" \
  --output "type=local,dest=${temporary_dir}/output" \
  "${script_dir}"

generated_pack="${temporary_dir}/output/${pack_name}"
test -f "${generated_pack}"

(
  cd -- "${temporary_dir}/output"
  sha256sum "${pack_name}" > "${pack_name}.sha256"
)

python3 "${script_dir}/verify-protobuf-offline-pack.py" \
  "${generated_pack}" \
  "${generated_pack}.sha256" \
  "${expected_checksum}"

install -m 0644 "${generated_pack}" "${pack_dir}/${pack_name}"
install -m 0644 "${generated_pack}.sha256" "${pack_dir}/${pack_name}.sha256"

printf 'Staged %s\n' "${pack_dir}/${pack_name}"
printf 'The Thor derivative can now be built without network access.\n'
