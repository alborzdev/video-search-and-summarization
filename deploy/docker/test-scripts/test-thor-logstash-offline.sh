#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)"
logstash_dir="${repo_root}/deploy/docker/services/infra/elk/logstash"
thor_compose="${repo_root}/deploy/docker/thor-local/compose.yml"
pack_name="logstash-codec-protobuf-1.3.0-logstash-9.3.3.zip"
expected_digest="f9f35aa8b54e3728fbfea6b9a71d77a572d443823903ff0dd3352b07440dd8fd"
expected_lock="${logstash_dir}/offline-packs/${pack_name}.expected.sha256"

bash -n "${logstash_dir}/stage-protobuf-offline-pack.sh"
python3 -m unittest discover \
  -s "${logstash_dir}/tests" \
  -p 'test_*.py'

python3 - "${thor_compose}" <<'PY'
import sys
from pathlib import Path

import yaml


class ComposeLoader(yaml.SafeLoader):
    pass


ComposeLoader.add_constructor(
    "!override", lambda loader, node: loader.construct_sequence(node)
)


compose = yaml.load(
    Path(sys.argv[1]).read_text(encoding="utf-8"), Loader=ComposeLoader
)
service = compose["services"]["logstash"]
build = service["build"]
assert service["command"] == [], service["command"]
assert service["environment"]["STREAM_TYPE"] == "kafka"
assert build["network"] == "none"
assert build["dockerfile"] == "Dockerfile.protobuf-offline"
assert "@sha256:" in build["args"]["LOGSTASH_BASE_IMAGE"]
assert build["args"]["LOGSTASH_PROTOBUF_VERSION"] == "1.3.0"
PY

grep -Fq 'file:///tmp/logstash-offline-pack/${LOGSTASH_PROTOBUF_PACK}' \
  "${logstash_dir}/Dockerfile.protobuf-offline"
grep -Fq 'sha256sum --check' "${logstash_dir}/Dockerfile.protobuf-offline"
grep -Fq '"$(awk '\''{print $1}'\'' "${LOGSTASH_PROTOBUF_PACK}.sha256")" =' \
  "${logstash_dir}/Dockerfile.protobuf-offline"
if grep -Eq '(^|[^[:alnum:]_-])(cmp|diff|comm)([[:space:]]|$)' \
  "${logstash_dir}/Dockerfile.protobuf-offline"; then
  printf 'Runtime Dockerfile uses a comparison utility absent from the minimal base.\n' >&2
  exit 1
fi
grep -Fq -- '--version "${LOGSTASH_PROTOBUF_VERSION}"' \
  "${logstash_dir}/Dockerfile.prepare-protobuf-offline"
grep -Fqx "${expected_digest}  ${pack_name}" "${expected_lock}"
grep -Fq '"${expected_checksum}"' \
  "${logstash_dir}/stage-protobuf-offline-pack.sh"

# The Thor overlay is intentionally narrow. NVIDIA's shared/non-Thor service
# remains unchanged until upstream adopts an offline image.
grep -Fq 'logstash-plugin install logstash-codec-protobuf' \
  "${repo_root}/deploy/docker/services/infra/compose.yml"

printf 'Thor Logstash offline-pack source checks passed.\n'
