#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

bundle=${1:-/tmp/vios-codec-bundle}
target=${2:-/}
mode=${3:-install}
manifest="${bundle}/manifest.json"
lock=${4:-/tmp/vios-codec-lock.json}
expected_source=20f1c024c11405ed88192ed9e26a2841348249b8c4238bccd5cce355f7051238
expected_set=ed28389b37a2d74a484251e874b4a131e9eb2a8350b4013ba0c209154bfdf3b4
expected_lock=e15b1ec7a68ca4087669a395148a1dea1e9d18288dcd072a259a43bcfe67f197
expected_count=63

[[ "${target}" == / ]] || { echo "VIOS codecs may only be installed into an image root" >&2; exit 2; }
[[ "${mode}" == install || "${mode}" == verify-only ]] || {
  echo "VIOS codec installer mode must be install or verify-only" >&2; exit 2;
}
[[ -d "${bundle}" && -f "${manifest}" ]] || { echo "missing VIOS codec bundle" >&2; exit 2; }
[[ -f "${lock}" && ! -L "${lock}" ]] || { echo "missing canonical VIOS codec lock" >&2; exit 2; }
command -v dpkg-deb >/dev/null || { echo "dpkg-deb is required" >&2; exit 2; }
command -v sha256sum >/dev/null || { echo "sha256sum is required" >&2; exit 2; }

[[ $(sha256sum "${lock}" | awk '{print $1}') == "${expected_lock}" ]] || {
  echo "canonical VIOS codec lock digest is not trusted" >&2; exit 2;
}
cmp -s "${manifest}" "${lock}" || {
  echo "codec bundle manifest does not match the canonical lock" >&2; exit 2;
}

grep -Fq "\"source_installer_sha256\": \"${expected_source}\"" "${manifest}" || {
  echo "codec manifest is not anchored to the VSS 3.2.1 source" >&2; exit 2;
}
grep -Fq "\"package_set_sha256\": \"${expected_set}\"" "${manifest}" || {
  echo "codec manifest has the wrong package identity set" >&2; exit 2;
}
grep -Fq "\"package_count\": ${expected_count}" "${manifest}" || {
  echo "codec manifest package count is not ${expected_count}" >&2; exit 2;
}
grep -Fq '"architecture": "arm64"' "${manifest}" || {
  echo "codec manifest is not ARM64" >&2; exit 2;
}

mapfile -t debs < <(find "${bundle}" -maxdepth 1 -type f -name '*_arm64.deb' -print | LC_ALL=C sort)
[[ ${#debs[@]} -eq ${expected_count} ]] || {
  echo "expected ${expected_count} ARM64 archives, found ${#debs[@]}" >&2; exit 2;
}
[[ -z "$(find "${bundle}" -maxdepth 1 -type l -print -quit)" ]] || {
  echo "codec bundle contains a symlink" >&2; exit 2;
}

raw_checksums=$(mktemp)
checksums=$(mktemp)
manifest_files=$(mktemp)
actual_files=$(mktemp)
package_names=$(mktemp)
sorted_package_names=$(mktemp)
trap 'rm -f "${raw_checksums}" "${checksums}" "${manifest_files}" "${actual_files}" "${package_names}" "${sorted_package_names}"' EXIT
awk -F'"' '
  /"filename":/ { filename=$4 }
  /"sha256":/ && filename != "" { print $4 "  " filename; filename="" }
' "${manifest}" > "${raw_checksums}"
while IFS= read -r checksum_line; do
  if [[ ! ${checksum_line} =~ ^([0-9a-f]{64})[[:space:]][[:space:]]([A-Za-z0-9][A-Za-z0-9.+:%~_-]*_arm64\.deb)$ ]]; then
    echo "codec manifest contains an unsafe filename or checksum" >&2
    exit 2
  fi
  printf '%s  %s\n' "${BASH_REMATCH[1]}" "${BASH_REMATCH[2]}" >> "${checksums}"
  printf '%s\n' "${BASH_REMATCH[2]}" >> "${manifest_files}"
done < "${raw_checksums}"
[[ $(wc -l < "${manifest_files}") -eq ${expected_count} ]] || {
  echo "codec manifest does not contain ${expected_count} filename/checksum pairs" >&2; exit 2;
}
[[ $(LC_ALL=C sort -u "${manifest_files}" | wc -l) -eq ${expected_count} ]] || {
  echo "codec manifest contains duplicate archive filenames" >&2; exit 2;
}
LC_ALL=C sort -o "${manifest_files}" "${manifest_files}"
find "${bundle}" -maxdepth 1 -type f -name '*_arm64.deb' -printf '%f\n' | LC_ALL=C sort > "${actual_files}"
cmp -s "${manifest_files}" "${actual_files}" || {
  echo "codec manifest archive inventory does not match the bundle" >&2; exit 2;
}
(cd "${bundle}" && sha256sum --check --strict "${checksums}")

for deb in "${debs[@]}"; do
  [[ $(dpkg-deb --field "${deb}" Architecture) == arm64 ]] || {
    echo "non-ARM64 archive in bundle: ${deb}" >&2; exit 2;
  }
  package_name=$(dpkg-deb --field "${deb}" Package)
  [[ ${package_name} =~ ^[a-z0-9][a-z0-9+.-]*$ && ${deb##*/} == "${package_name}_"* ]] || {
    echo "archive filename/control package identity mismatch: ${deb}" >&2; exit 2;
  }
  printf '%s\n' "${package_name}" >> "${package_names}"
done
LC_ALL=C sort -u "${package_names}" > "${sorted_package_names}"
[[ $(wc -l < "${sorted_package_names}") -eq ${expected_count} ]] || {
  echo "codec bundle contains duplicate package identities" >&2; exit 2;
}
[[ $(sha256sum "${sorted_package_names}" | awk '{print $1}') == "${expected_set}" ]] || {
  echo "codec bundle package identities do not match the VSS 3.2.1 set" >&2; exit 2;
}

if [[ "${mode}" == verify-only ]]; then
  echo "verified exact VIOS codec bundle membership, hashes, architecture, and package identities"
  exit 0
fi

for deb in "${debs[@]}"; do
  dpkg-deb --extract "${deb}" "${target}"
done

lib_dir=/usr/lib/aarch64-linux-gnu
gst_dir=${lib_dir}/gstreamer-1.0

# Match NVIDIA's non-root codec overlay: plugins whose dependency closure is
# intentionally outside this 63-package set must not poison GStreamer scans.
for plugin in libgstspandsp libgstopenh264 libgstvoaacenc libgstfaad libgstdtsdec \
              libgstdvdread libgstmpeg2enc libgstmplex libgstresindvd libgstladspa \
              libgstzxing libgstneonhttpsrc libgstfluidsynthmidi libgstdirectfb \
              libgstaasink libgstcacasink; do
  find "${gst_dir}" -name "${plugin}.so" -delete 2>/dev/null || true
done

# VIOS uses NVIDIA hardware codecs; never restore Intel MediaSDK/QSV artifacts
# as a transitive side effect of the Ubuntu plugin package.
rm -f "${lib_dir}"/mfx/libmfx_*_hw64.so* \
      "${lib_dir}"/libmfx.so* "${lib_dir}"/libmfxhw64.so* \
      "${lib_dir}"/libmfx-tracer.so* "${gst_dir}"/libgstmsdk.so* \
      "${gst_dir}"/libgstqsv.so* 2>/dev/null || true
rm -rf "${lib_dir}/mfx" /root/.cache/gstreamer-1.0

[[ -e "${lib_dir}/libavcodec.so.60" ]] || { echo "libavcodec.so.60 missing" >&2; exit 2; }
[[ -e "${lib_dir}/libavformat.so.60" ]] || { echo "libavformat.so.60 missing" >&2; exit 2; }
[[ -e "${lib_dir}/libx264.so.164" ]] || { echo "CPU H.264 library missing" >&2; exit 2; }
[[ -e "${lib_dir}/libx265.so.199" ]] || { echo "CPU H.265 library missing" >&2; exit 2; }
[[ -e "${gst_dir}/libgstlibav.so" ]] || { echo "GStreamer libav plugin missing" >&2; exit 2; }
[[ -e "${gst_dir}/libgstisomp4.so" ]] || { echo "GStreamer ISO MP4 plugin missing" >&2; exit 2; }
[[ -e "${lib_dir}/libbs2b.so.0" ]] || { echo "libav filter dependency libbs2b.so.0 missing" >&2; exit 2; }
[[ -e "${lib_dir}/libsbc.so.1" ]] || { echo "GStreamer SBC dependency missing" >&2; exit 2; }
[[ -e "${lib_dir}/libcdio.so.19" ]] || { echo "GStreamer CDIO dependency missing" >&2; exit 2; }
[[ -e "${lib_dir}/libsidplay.so.1" ]] || { echo "GStreamer SID dependency missing" >&2; exit 2; }

install -d -m 0555 /usr/share/vss-thor/vios-codecs
install -m 0444 "${lock}" /usr/share/vss-thor/vios-codecs/manifest.json
printf '%s\n' "${expected_set}" > /usr/share/vss-thor/vios-codecs/package-set.sha256
chmod 0444 /usr/share/vss-thor/vios-codecs/package-set.sha256
