#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

readonly kibana_url="${KIBANA_URL:-http://localhost:5601/kibana}"
readonly elasticsearch_url="${ELASTICSEARCH_URL:-http://localhost:9200}"
readonly max_attempts="${KIBANA_IMPORT_MAX_ATTEMPTS:-30}"

wait_for_endpoint() {
  local name="$1"
  local url="$2"
  local attempt

  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
    if curl --fail --silent --show-error --output /dev/null "${url}"; then
      return 0
    fi
    echo "Waiting for ${name} (${attempt}/${max_attempts})"
    sleep 5
  done

  echo "${name} did not become ready at ${url}" >&2
  return 1
}

import_dashboard() {
  local path="$1"
  curl --fail --silent --show-error \
    --request POST \
    "${kibana_url}/api/saved_objects/_import?overwrite=true" \
    --header "kbn-xsrf: true" \
    --form "file=@${path}"
}

ensure_dashboard_index() {
  local index="$1"
  local status
  local mapping

  status="$(curl --silent --output /dev/null --write-out '%{http_code}' \
    "${elasticsearch_url}/${index}")"

  if [[ "${status}" == "404" ]]; then
    curl --fail --silent --show-error \
      --request PUT \
      "${elasticsearch_url}/${index}" \
      --header "Content-Type: application/json" \
      --data '{"settings":{"number_of_shards":1,"number_of_replicas":0},"mappings":{"properties":{"timestamp":{"type":"date"}}}}'
  elif [[ "${status}" != "200" ]]; then
    echo "Unexpected Elasticsearch status ${status} for ${index}" >&2
    return 1
  fi

  mapping="$(curl --fail --silent --show-error \
    "${elasticsearch_url}/${index}/_mapping/field/timestamp")"
  if ! grep -Eq '"type"[[:space:]]*:[[:space:]]*"date"' <<<"${mapping}"; then
    echo "Dashboard bootstrap index ${index} does not expose timestamp as a date" >&2
    return 1
  fi
}

wait_for_endpoint Elasticsearch "${elasticsearch_url}"
wait_for_endpoint Kibana "${kibana_url}/api/status"
ensure_dashboard_index mdx-raw-thor-bootstrap
ensure_dashboard_index mdx-behavior-thor-bootstrap
import_dashboard /opt/mdx/search-kibana-objects.ndjson
import_dashboard /opt/mdx/its-kibana-objects.ndjson
import_dashboard /opt/mdx/warehouse-2d-kibana-objects.ndjson
import_dashboard /opt/mdx/thor-vss-overview.ndjson
