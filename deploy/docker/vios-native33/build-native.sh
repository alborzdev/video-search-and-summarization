#!/usr/bin/env bash
# Compile only an operator-owned scratch copy; never launch the application.
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
import os
memory = (Path('/sys/fs/cgroup') / 'memory.max').read_text().strip()
quota, period = (Path('/sys/fs/cgroup') / 'cpu.max').read_text().split()
assert memory != 'max' and int(memory) <= 4 * 1024**3, 'Builder requires <=4GiB memory limit'
assert quota != 'max' and int(quota) <= 2 * int(period), 'Builder requires <=2CPU quota'
assert not list(Path('/dev').glob('nvidia*')), 'Builder must have no GPU devices'
assert not Path('/dev/dri').exists(), 'Builder must have no DRM devices'
resume = os.environ.get('VSS_NATIVE_RESUME') == '1'
assert Path('/build/vios').exists() == resume, 'Fresh build requires empty scratch; resume requires existing scratch'
assert not (Path('/out') / 'launch_vst').exists(), 'Use a fresh native output directory'
PY
mkdir -p /build/vios /build/tmp /out
if [[ "${VSS_NATIVE_RESUME:-0}" != 1 ]]; then
    cp -a /source/. /build/vios/
fi
cd /build/vios
python3 - <<'PY'
import hashlib, json
from pathlib import Path
manifest = json.loads(Path('/source/source-manifest.json').read_text())
assert json.loads(Path('source-manifest.json').read_text()) == manifest, 'Scratch/source receipt mismatch'
for name, expected in manifest['files'].items():
    path = Path(name)
    if 'symlink' in expected:
        assert path.is_symlink() and str(path.readlink()) == expected['symlink'], name
    else:
        assert not path.is_symlink() and hashlib.sha256(path.read_bytes()).hexdigest() == expected['sha256'], name
generated = []
proto_dirs = ('src/framework/notification/', 'src/adaptors/vms_media/', 'src/framework/protocols/grpc/')
for path in Path('.').rglob('*'):
    if not path.is_file() and not path.is_symlink():
        continue
    name = str(path)
    if name in manifest['files'] or name == 'source-manifest.json':
        continue
    object_file = name.startswith('src/') and path.suffix in ('.o', '.d')
    proto_file = name.startswith(proto_dirs) and name.endswith(('.pb.h', '.pb.cc'))
    shared_lib = name.startswith('prebuilts/aarch64/') and '.so' in path.name
    assert object_file or proto_file or shared_lib or name == 'launch_vst', 'Unexpected generated file: ' + name
    if path.is_symlink():
        assert not path.readlink().is_absolute() and path.resolve().is_relative_to(Path.cwd()), name
    generated.append(name)
print('Verified exact source snapshot', manifest['tree_sha256'], flush=True)
print('Verified allowed generated files:', len(generated), flush=True)
PY
unset CROSS_COMPILE JETSON_ROOTFS SYSROOT cc
export TMPDIR=/build/tmp
export LD_LIBRARY_PATH="/build/vios/prebuilts/aarch64:/build/vios/prebuilts/aarch64/sbsa:/build/vios/prebuilts/aarch64/gst-plugins:/build/vios/prebuilts/aarch64/prom_so:/build/vios/prebuilts/aarch64/aws:/build/vios/prebuilts/aarch64/minio:/usr/lib/aarch64-linux-gnu/blas:/usr/lib/aarch64-linux-gnu/lapack:${LD_LIBRARY_PATH:-}"
# Same native internal Makefile path used by upstream docker/Dockerfile. The
# external build.sh cc wrappers launch unbounded nested Docker with -j12.
# The vms_media adaptor assumes cross-qemu even on native ARM64. Explicit
# native pkg-config flags preserve its full gRPC functionality without qemu.
vios_grpc_libs="$(pkg-config --libs grpc++ protobuf)"
make -j2 arch=aarch64 CUDA_TARGET_DIR=/usr/local/cuda PROJECT=vst MODULE=streamprocessing \
    GRPC_LIBS="${vios_grpc_libs}" CXX_SYSROOT= all
test -s launch_vst
test -s prebuilts/aarch64/libnvvideo_source.so
test -s prebuilts/aarch64/gst-plugins/libgstdashmp4mux.so
cp -a launch_vst source-manifest.json /out/
mkdir -p /out/prebuilts
cp -a prebuilts/aarch64 /out/prebuilts/
ldd launch_vst > /out/builder-linker.txt
if grep -q 'not found' /out/builder-linker.txt; then
    cat /out/builder-linker.txt
    exit 1
fi
python3 - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('/out')
paths = [root / 'launch_vst', *sorted((root / 'prebuilts').rglob('*'))]
files = {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
         for path in paths if path.is_file() and not path.is_symlink()}
(root / 'output-checksums.json').write_text(json.dumps(files, indent=2) + '\n')
print('Built full streamprocessing source; exported', len(files), 'ELF/archive files', flush=True)
PY
