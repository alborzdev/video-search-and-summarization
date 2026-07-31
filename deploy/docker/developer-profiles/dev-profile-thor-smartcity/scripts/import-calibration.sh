#!/bin/sh

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -eu

api_url="${VIDEO_ANALYTICS_API_URL:-http://127.0.0.1:8081}"
max_attempts="${SMARTCITY_IMPORT_MAX_ATTEMPTS:-60}"
retry_seconds="${SMARTCITY_IMPORT_RETRY_SECONDS:-2}"

case "${max_attempts}" in
  ''|*[!0-9]*|0) echo "SMARTCITY_IMPORT_MAX_ATTEMPTS must be a positive integer" >&2; exit 2 ;;
esac
case "${retry_seconds}" in
  ''|*[!0-9]*) echo "SMARTCITY_IMPORT_RETRY_SECONDS must be a non-negative integer" >&2; exit 2 ;;
esac

wait_for_api() {
  attempt=1
  while [ "${attempt}" -le "${max_attempts}" ]; do
    if curl --fail --silent --show-error --output /dev/null "${api_url%/}/livez"; then
      return 0
    fi
    echo "Video Analytics API is not ready (${attempt}/${max_attempts}); retrying in ${retry_seconds}s..." >&2
    sleep "${retry_seconds}"
    attempt=$((attempt + 1))
  done
  echo "Video Analytics API did not become ready after ${max_attempts} attempts" >&2
  return 1
}

upload_file() {
  doc_type="$1"
  input_file="$2"
  attempt=1
  while [ "${attempt}" -le "${max_attempts}" ]; do
    if curl --fail --silent --show-error \
      --request POST \
      --form "configFiles=@${input_file};type=application/json" \
      "${api_url%/}/config/upload-file/${doc_type}"; then
      echo
      echo "Imported ${doc_type} from ${input_file}"
      return 0
    fi
    echo "Import ${doc_type} failed (${attempt}/${max_attempts}); retrying in ${retry_seconds}s..." >&2
    sleep "${retry_seconds}"
    attempt=$((attempt + 1))
  done
  echo "Import ${doc_type} failed after ${max_attempts} attempts" >&2
  return 1
}

wait_for_api
upload_file calibration /opt/smartcity/calibration.json
upload_file road-network /opt/smartcity/road-network.json
