#!/usr/bin/env bash

# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Bounded, destructive-to-its-own-test-data-only capacity check for the Thor
# local profile. It drives the supported RTSP ingest/delete API and therefore
# exercises VIOS, DeepStream, Cosmos Embed and the agent transaction boundary.

set -Eeuo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
deployment_dir=$(cd -- "${script_dir}/.." && pwd)

agent_url="${THOR_CAPACITY_AGENT_URL:-http://127.0.0.1:7777}"
vst_url="${THOR_CAPACITY_VST_URL:-http://127.0.0.1:30888}"
es_url="${THOR_CAPACITY_ES_URL:-http://127.0.0.1:9200}"
rtsp_publish_host="${THOR_CAPACITY_RTSP_PUBLISH_HOST:-127.0.0.1}"
rtsp_consume_host="${THOR_CAPACITY_RTSP_CONSUME_HOST:-}"
rtsp_port="${THOR_CAPACITY_RTSP_PORT:-8554}"
minimum_available_kib="${THOR_CAPACITY_MIN_AVAILABLE_KIB:-3145728}"
baseline_seconds="${THOR_CAPACITY_BASELINE_SECONDS:-8}"
one_stream_seconds="${THOR_CAPACITY_ONE_STREAM_SECONDS:-50}"
two_stream_seconds="${THOR_CAPACITY_TWO_STREAM_SECONDS:-65}"
video="${THOR_CAPACITY_VIDEO:-${deployment_dir}/data-dir/data_log/vst/clip_storage/pit-POV.mp4}"
output_dir="${THOR_CAPACITY_OUTPUT_DIR:-}"

required_containers=(
  vss-agent
  vss-rtvi-cv
  vss-rtvi-embed
  vss-rtvi-vlm
  vss-vios-streamprocessing
  vss-vios-sensor
  vss-vios-ingress
  elasticsearch
  kafka
)

usage() {
  cat <<'EOF'
Usage: thor-capacity-check.sh

Runs a bounded 1 -> 2 live-stream capacity check against an already-running
Thor local stack. The script does not rebuild or restart services. It creates
unique temporary RTSP sources, continuously enforces a 3 GiB available-memory
floor, and removes every source and recording when it exits.

Optional environment variables:
  THOR_CAPACITY_VIDEO                 H.264 sample video (default: pit-POV.mp4)
  THOR_CAPACITY_OUTPUT_DIR            Keep evidence in this new/empty directory
  THOR_CAPACITY_RTSP_CONSUME_HOST     Host/IP containers use for the RTSP server
  THOR_CAPACITY_MIN_AVAILABLE_KIB     Abort floor (default: 3145728 = 3 GiB)
  THOR_CAPACITY_BASELINE_SECONDS      Idle sample duration (default: 8)
  THOR_CAPACITY_ONE_STREAM_SECONDS    One-stream hold duration (default: 50)
  THOR_CAPACITY_TWO_STREAM_SECONDS    Two-stream hold duration (default: 65)
EOF
}

die() {
  printf '[FAIL] %s\n' "$*" >&2
  exit 1
}

for command in curl docker ffmpeg ffprobe jq rg tegrastats timeout; do
  command -v "${command}" >/dev/null || die "Required command is missing: ${command}"
done

[[ -f "${video}" ]] || die "Benchmark video does not exist: ${video}"
[[ "${minimum_available_kib}" =~ ^[0-9]+$ ]] || die "THOR_CAPACITY_MIN_AVAILABLE_KIB must be an integer"
(( minimum_available_kib >= 3145728 )) || die "The safety floor may not be set below 3 GiB"

if [[ -z "${rtsp_consume_host}" ]]; then
  generated_env="${deployment_dir}/thor-local/generated.env"
  [[ -r "${generated_env}" ]] || die "Set THOR_CAPACITY_RTSP_CONSUME_HOST or generate ${generated_env}"
  rtsp_consume_host=$(awk -F= '$1 == "HOST_IP" {print $2; exit}' "${generated_env}")
  rtsp_consume_host=${rtsp_consume_host%$'\r'}
fi
[[ -n "${rtsp_consume_host}" ]] || die "Could not resolve the RTSP host used by containers"

if [[ -n "${output_dir}" ]]; then
  [[ ! -e "${output_dir}" ]] || die "THOR_CAPACITY_OUTPUT_DIR must not already exist: ${output_dir}"
  mkdir -m 0700 -p "${output_dir}"
  work="${output_dir}"
  keep_evidence=true
else
  work=$(mktemp -d "${TMPDIR:-/tmp}/thor-capacity.XXXXXX")
  keep_evidence=false
fi

run_id=$(date -u +%Y%m%dT%H%M%SZ)-$$
name1="thor-capacity-a-${run_id}"
name2="thor-capacity-b-${run_id}"
publish_url1="rtsp://${rtsp_publish_host}:${rtsp_port}/${name1}"
publish_url2="rtsp://${rtsp_publish_host}:${rtsp_port}/${name2}"
consume_url1="rtsp://${rtsp_consume_host}:${rtsp_port}/${name1}"
consume_url2="rtsp://${rtsp_consume_host}:${rtsp_port}/${name2}"
phase_file="${work}/phase"
abort_file="${work}/abort"
metrics="${work}/metrics.tsv"
start_iso=$(date -u +%Y-%m-%dT%H:%M:%SZ)
ffpid1=""
ffpid2=""
monpid=""
added1=false
added2=false
benchmark_complete=false
sensor1=""
sensor2=""

umask 077

cleanup() {
  set +e
  local cleanup_ok=true
  local current_sources=""
  if [[ -n "${monpid}" ]]; then
    kill "${monpid}" 2>/dev/null
    wait "${monpid}" 2>/dev/null
  fi
  if [[ "${added2}" == true ]]; then
    curl -sS --max-time 90 -X DELETE \
      "${agent_url}/api/v1/rtsp-streams/delete/${name2}" \
      >"${work}/delete2.json" 2>"${work}/delete2.err"
  fi
  if [[ "${added1}" == true ]]; then
    curl -sS --max-time 90 -X DELETE \
      "${agent_url}/api/v1/rtsp-streams/delete/${name1}" \
      >"${work}/delete1.json" 2>"${work}/delete1.err"
  fi

  if [[ "${added1}" == true || "${added2}" == true ]]; then
    curl -sf --max-time 30 -X POST \
      -H 'Content-Type: application/json' \
      "${es_url}/mdx-embed-filtered-*/_delete_by_query?conflicts=proceed&refresh=true" \
      -d "{\"query\":{\"terms\":{\"sensor.id.keyword\":[\"${name1}\",\"${name2}\"]}}}" \
      >"${work}/delete-embeddings.json" 2>"${work}/delete-embeddings.err"
  fi
  if [[ -n "${ffpid2}" ]]; then
    kill "${ffpid2}" 2>/dev/null
    wait "${ffpid2}" 2>/dev/null
  fi
  if [[ -n "${ffpid1}" ]]; then
    kill "${ffpid1}" 2>/dev/null
    wait "${ffpid1}" 2>/dev/null
  fi

  if [[ "${added1}" == true ]] && ! jq -e '.status == "success"' \
    "${work}/delete1.json" >/dev/null 2>&1; then
    cleanup_ok=false
  fi
  if [[ "${added2}" == true ]] && ! jq -e '.status == "success"' \
    "${work}/delete2.json" >/dev/null 2>&1; then
    cleanup_ok=false
  fi
  if [[ "${added1}" == true || "${added2}" == true ]]; then
    if ! jq -e '.failures | length == 0' "${work}/delete-embeddings.json" >/dev/null 2>&1; then
      cleanup_ok=false
    fi
    [[ "$(embedding_count "${name1}")" == 0 ]] || cleanup_ok=false
    [[ "$(embedding_count "${name2}")" == 0 ]] || cleanup_ok=false
  fi

  if [[ "${added1}" == true || "${added2}" == true ]]; then
    for _attempt in $(seq 1 15); do
      current_sources=$(active_sources)
      [[ "${current_sources:-unknown}" == 0 ]] && break
      sleep 1
    done
    [[ "${current_sources:-unknown}" == 0 ]] || cleanup_ok=false
  fi
  if [[ -n "${sensor1}" ]] && curl -sS --max-time 5 \
    "${vst_url}/vst/api/v1/sensor/${sensor1}/streams" \
    | jq -e 'type == "array" and length > 0' >/dev/null; then
    cleanup_ok=false
  fi
  if [[ -n "${sensor2}" ]] && curl -sS --max-time 5 \
    "${vst_url}/vst/api/v1/sensor/${sensor2}/streams" \
    | jq -e 'type == "array" and length > 0' >/dev/null; then
    cleanup_ok=false
  fi

  if [[ "${benchmark_complete}" == true && "${cleanup_ok}" == true ]]; then
    printf '[OK] Cleanup proof: DeepStream streams=0; VIOS streams and Cosmos documents absent; publishers stopped.\n'
  else
    printf '[WARN] Benchmark or cleanup proof failed; cleanup was attempted. Evidence: %s\n' "${work}" >&2
  fi
  if [[ "${keep_evidence}" == false && "${benchmark_complete}" == true && "${cleanup_ok}" == true ]]; then
    rm -rf -- "${work}"
  else
    printf 'Evidence directory: %s\n' "${work}"
  fi
}
trap cleanup EXIT INT TERM

container_health() {
  local container state
  for container in "${required_containers[@]}"; do
    state=$(docker inspect -f '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{end}}' \
      "${container}" 2>/dev/null || printf 'missing')
    if [[ "${state}" != running* || "${state}" == *unhealthy* ]]; then
      printf 'bad:%s:%s' "${container}" "${state}"
      return
    fi
  done
  printf 'ok'
}

monitor() {
  local now phase available sample temp gpu health
  while true; do
    now=$(date +%s)
    phase=$(<"${phase_file}")
    available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
    sample=$(timeout 2s tegrastats --interval 1000 2>/dev/null | head -n 1 || true)
    temp=$(sed -n 's/.*gpu@\([0-9.]*\)C.*/\1/p' <<<"${sample}")
    gpu=$(sed -n 's/.*VDD_GPU \([0-9]*\)mW.*/\1/p' <<<"${sample}")
    health=$(container_health)
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' \
      "${now}" "${phase}" "${available}" "${temp:-na}" "${gpu:-na}" "${health}" >>"${metrics}"
    if (( available < minimum_available_kib )); then
      printf 'available memory %s KiB is below the %s KiB floor\n' \
        "${available}" "${minimum_available_kib}" >"${abort_file}"
    fi
    if [[ "${health}" != ok ]]; then
      printf '%s\n' "${health}" >"${abort_file}"
    fi
    sleep 1
  done
}

check_abort() {
  if [[ -s "${abort_file}" ]]; then
    die "Safety abort: $(<"${abort_file}")"
  fi
}

wait_checked() {
  local seconds=$1
  local end=$((SECONDS + seconds))
  while (( SECONDS < end )); do
    check_abort
    sleep 2
  done
}

run_request_checked() {
  local response=$1
  shift
  local curl_pid started latency
  started=$(date +%s%3N)
  curl -sS --max-time 120 "$@" >"${response}" 2>"${response}.err" &
  curl_pid=$!
  while kill -0 "${curl_pid}" 2>/dev/null; do
    check_abort
    sleep 1
  done
  wait "${curl_pid}"
  latency=$(( $(date +%s%3N) - started ))
  printf '%s\n' "${latency}" >"${response}.latency_ms"
}

active_sources() {
  curl -sf --max-time 5 http://127.0.0.1:9000/api/v1/stream/get-stream-info \
    | jq -r '."stream-info"."stream-count"'
}

wait_for_sources() {
  local expected=$1
  local deadline=$((SECONDS + 40))
  local actual=""
  while (( SECONDS < deadline )); do
    check_abort
    actual=$(active_sources)
    if [[ "${actual}" == "${expected}" ]]; then
      return
    fi
    sleep 2
  done
  die "DeepStream did not report ${expected} active source(s); last value: ${actual:-unknown}"
}

sensor_id_by_name() {
  local name=$1
  curl -sf --max-time 10 "${vst_url}/vst/api/v1/sensor/list" \
    | jq -r --arg name "${name}" '.[] | select(.name == $name) | .sensorId' \
    | head -n 1
}

embedding_count() {
  local sensor_name=$1
  curl -sf --max-time 10 -X POST "${es_url}/mdx-embed-filtered-*/_refresh" >/dev/null
  curl -sf --max-time 10 -H 'Content-Type: application/json' \
    "${es_url}/mdx-embed-filtered-*/_count" \
    -d "{\"query\":{\"term\":{\"sensor.id.keyword\":\"${sensor_name}\"}}}" \
    | jq -r .count
}

fps_reading() {
  local sensor_name=$1
  awk -v sensor_name="${sensor_name}" '
    index($0, "stream_name " sensor_name) {
      instantaneous = $1
      average = $2
      gsub(/[()]/, "", average)
    }
    END { printf "instantaneous=%s average=%s", instantaneous, average }
  ' "${work}/cv.log"
}

print_metrics_summary() {
  awk -F '\t' '
    NR > 1 {
      n[$2]++
      if (!min[$2] || $3 < min[$2]) min[$2] = $3
      if ($3 > max[$2]) max[$2] = $3
      if ($5 != "na") { gpu_sum[$2] += $5; gpu_n[$2]++ }
      if ($4 != "na") { temp_sum[$2] += $4; temp_n[$2]++ }
      if ($6 != "ok") bad[$2]++
    }
    END {
      for (phase in n) {
        printf "%s samples=%d min_available_gib=%.2f max_available_gib=%.2f avg_gpu_power_w=%.1f avg_gpu_temp_c=%.1f health_bad=%d\n",
          phase, n[phase], min[phase] / 1048576, max[phase] / 1048576,
          gpu_n[phase] ? gpu_sum[phase] / gpu_n[phase] / 1000 : 0,
          temp_n[phase] ? temp_sum[phase] / temp_n[phase] : 0, bad[phase] + 0
      }
    }
  ' "${metrics}" | sort
}

if [[ "${1:-}" == "--help" || "${1:-}" == "help" ]]; then
  usage
  benchmark_complete=true
  exit 0
fi
(( $# == 0 )) || die "Unknown argument: $1"

curl -sf --max-time 5 "${vst_url}/vst/api/v1/sensor/version" >/dev/null \
  || die "VIOS is not reachable at ${vst_url}"
curl -sf --max-time 5 "${es_url}/_cluster/health" >/dev/null \
  || die "Elasticsearch is not reachable at ${es_url}"
[[ "$(container_health)" == ok ]] || die "One or more required containers are not healthy"

initial_sources=$(active_sources)
[[ "${initial_sources:-0}" == 0 ]] \
  || die "Capacity check requires an idle DeepStream pipeline; active sources: ${initial_sources}"

printf 'epoch\tphase\tmem_available_kib\tgpu_temp_c\tgpu_power_mw\tcore_health\n' >"${metrics}"
printf 'baseline\n' >"${phase_file}"
monitor &
monpid=$!

printf '[RUN] Baseline for %ss.\n' "${baseline_seconds}"
wait_checked "${baseline_seconds}"

ffmpeg -nostdin -hide_banner -loglevel error -re -stream_loop -1 -i "${video}" \
  -map 0:v:0 -c:v copy -an -f rtsp -rtsp_transport tcp "${publish_url1}" \
  >"${work}/ffmpeg1.log" 2>&1 &
ffpid1=$!
wait_checked 4
ffprobe -v error -rtsp_transport tcp \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -of compact=p=0:nk=1 "${consume_url1}" >"${work}/probe1.txt"

printf 'one_ingest\n' >"${phase_file}"
printf '[RUN] Registering stream 1 through the agent transaction.\n'
run_request_checked "${work}/add1.json" -X POST \
  "${agent_url}/api/v1/rtsp-streams/add" \
  -H 'Content-Type: application/json' \
  -d "{\"sensorUrl\":\"${consume_url1}\",\"name\":\"${name1}\",\"username\":\"\",\"password\":\"\",\"location\":\"capacity-test\",\"tags\":\"temporary\"}"
jq -e '.status == "success"' "${work}/add1.json" >/dev/null \
  || die "Stream 1 ingest failed: $(<"${work}/add1.json")"
added1=true
sensor1=$(sensor_id_by_name "${name1}")
[[ -n "${sensor1}" ]] || die "VIOS did not expose stream 1 after successful ingest"
wait_for_sources 1
printf 'one_stream\n' >"${phase_file}"
printf '[RUN] Holding one stream for %ss.\n' "${one_stream_seconds}"
wait_checked "${one_stream_seconds}"
count1=$(embedding_count "${name1}")

ffmpeg -nostdin -hide_banner -loglevel error -re -stream_loop -1 -i "${video}" \
  -map 0:v:0 -c:v copy -an -f rtsp -rtsp_transport tcp "${publish_url2}" \
  >"${work}/ffmpeg2.log" 2>&1 &
ffpid2=$!
wait_checked 4
ffprobe -v error -rtsp_transport tcp \
  -show_entries stream=codec_name,width,height,r_frame_rate \
  -of compact=p=0:nk=1 "${consume_url2}" >"${work}/probe2.txt"

printf 'two_ingest\n' >"${phase_file}"
printf '[RUN] Registering stream 2 through the agent transaction.\n'
run_request_checked "${work}/add2.json" -X POST \
  "${agent_url}/api/v1/rtsp-streams/add" \
  -H 'Content-Type: application/json' \
  -d "{\"sensorUrl\":\"${consume_url2}\",\"name\":\"${name2}\",\"username\":\"\",\"password\":\"\",\"location\":\"capacity-test\",\"tags\":\"temporary\"}"
jq -e '.status == "success"' "${work}/add2.json" >/dev/null \
  || die "Stream 2 ingest failed: $(<"${work}/add2.json")"
added2=true
sensor2=$(sensor_id_by_name "${name2}")
[[ -n "${sensor2}" ]] || die "VIOS did not expose stream 2 after successful ingest"
wait_for_sources 2
printf 'two_stream\n' >"${phase_file}"
printf '[RUN] Holding two concurrent streams for %ss.\n' "${two_stream_seconds}"
wait_checked "${two_stream_seconds}"
count1_after_two=$(embedding_count "${name1}")
count2=$(embedding_count "${name2}")

docker logs --since "${start_iso}" vss-rtvi-cv >"${work}/cv.log" 2>&1
docker logs --since "${start_iso}" vss-rtvi-embed >"${work}/embed.log" 2>&1

printf '\nThor capacity result\n'
printf '  Input 1: %s\n' "$(<"${work}/probe1.txt")"
printf '  Input 2: %s\n' "$(<"${work}/probe2.txt")"
printf '  Stream 1 ingest latency: %s ms\n' "$(<"${work}/add1.json.latency_ms")"
printf '  Stream 2 ingest latency: %s ms\n' "$(<"${work}/add2.json.latency_ms")"
printf '  Stream 1 embedding chunks after one-stream phase: %s\n' "${count1}"
printf '  Stream 1 embedding chunks after two-stream phase: %s\n' "${count1_after_two}"
printf '  Stream 2 embedding chunks after two-stream phase: %s\n' "${count2}"
printf '  Two-stream embedding throughput: %.2f chunks/s aggregate\n' \
  "$(awk -v count="$((count1_after_two - count1 + count2))" -v seconds="${two_stream_seconds}" 'BEGIN {print count / seconds}')"
printf '  Final DeepStream stream 1 FPS: %s\n' "$(fps_reading "${name1}")"
printf '  Final DeepStream stream 2 FPS: %s\n' "$(fps_reading "${name2}")"
printf '  DeepStream active-source proof: 0 -> 1 -> 2\n'
printf '  Safety floor: %.2f GiB available memory\n' "$(awk -v value="${minimum_available_kib}" 'BEGIN {print value / 1048576}')"
print_metrics_summary | sed 's/^/  /'

check_abort
[[ "$(container_health)" == ok ]] || die "A required container degraded after the test"
benchmark_complete=true
