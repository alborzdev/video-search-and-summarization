#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Build-time-only installer for the verified, already-staged ARM64 codec pack.
# The caller is expected to build with --network=none.  This script has no
# package-manager or downloader path.

set -euo pipefail

bundle=${1:-/tmp/rtvi-vlm-codec-bundle}
install_dir=${2:-/opt/nvidia/rtvi/thor-codecs}
lib_dir="${install_dir}/usr/lib/aarch64-linux-gnu"
gst_plugin_dir="${lib_dir}/gstreamer-1.0"

[[ -d "${bundle}" ]] || { echo "missing codec bundle: ${bundle}" >&2; exit 2; }
[[ ! -e "${install_dir}" ]] || { echo "refusing to replace existing codec root: ${install_dir}" >&2; exit 2; }

install -d -m 0755 "${install_dir}"
package_count=0
while IFS= read -r -d '' package; do
  dpkg-deb --extract "${package}" "${install_dir}"
  package_count=$((package_count + 1))
done < <(find "${bundle}" -maxdepth 1 -type f -name '*_arm64.deb' -print0 | sort -z)

[[ ${package_count} -eq 59 ]] || {
  echo "expected 59 staged ARM64 packages, extracted ${package_count}" >&2
  exit 2
}

[[ -f "${lib_dir}/blas/libblas.so.3" ]] &&
  ln -s "${lib_dir}/blas/libblas.so.3" "${lib_dir}/libblas.so.3"
[[ -f "${lib_dir}/lapack/liblapack.so.3" ]] &&
  ln -s "${lib_dir}/lapack/liblapack.so.3" "${lib_dir}/liblapack.so.3"

if [[ -f "${install_dir}/usr/bin/ffmpeg" ]]; then
  mv "${install_dir}/usr/bin/ffmpeg" "${install_dir}/usr/bin/ffmpeg_for_overlay_video"
fi

# These plugins have dependencies intentionally absent from NVIDIA's runtime.
# This is the same exclusion list as the VSS 3.2.1 non-root codec installer.
for plugin in libgstspandsp libgstopenh264 libgstvoaacenc libgstfaad libgstdtsdec \
  libgstdvdread libgstmpeg2enc libgstmplex libgstresindvd libgstladspa \
  libgstzxing libgstneonhttpsrc libgstfluidsynthmidi libgstdirectfb \
  libgstaasink libgstcacasink; do
  find "${gst_plugin_dir}" -name "${plugin}.so" -delete 2>/dev/null || true
done

[[ -e "${lib_dir}/libavcodec.so.60" ]] || { echo "codec pack lacks libavcodec.so.60" >&2; exit 2; }
[[ -e "${gst_plugin_dir}/libgstlibav.so" ]] || { echo "codec pack lacks GStreamer libav" >&2; exit 2; }
[[ -e "${gst_plugin_dir}/libgstisomp4.so" ]] || { echo "codec pack lacks the ISO MP4 demuxer" >&2; exit 2; }

cat > "${install_dir}/codec_env.sh" <<'EOF'
export GST_PLUGIN_PATH=/opt/nvidia/rtvi/thor-codecs/usr/lib/aarch64-linux-gnu/gstreamer-1.0${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}
export LD_LIBRARY_PATH=/opt/nvidia/rtvi/thor-codecs/usr/lib/aarch64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}
export PATH=/opt/nvidia/rtvi/thor-codecs/usr/bin${PATH:+:$PATH}
EOF
chmod 0444 "${install_dir}/codec_env.sh"
touch "${install_dir}/.installed-offline"
chmod -R a+rX "${install_dir}"
chown -R 1001:1001 "${install_dir}"
