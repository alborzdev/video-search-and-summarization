# Offline native VIOS 3.3 build

This ARM64 recipe compiles the maintained streamprocessing source, including the
uploaded-file DASH timestamp repair and custom RTSP/HTTP/schema fixes. Python
mounts cannot patch the published native executable. The separate
sensor-management target is outside this build: its retained custom source is
not claimed as compiled or qualified. Thor continues to use its existing image.

The operator controls Docker lifecycle and runtime cutover. The preparation
helper never starts containers or installs host packages. Leave ACT training,
model budgets and the Spark 20 GiB / Thor 10 GiB guards unchanged. A successful
build does not authorize a persisted-database migration or broaden live-ingestion
qualification.

## Locked inputs

`Dockerfile.builder` uses the immutable 3.3 SBSA RT-VLM base with existing GCC,
make and CUDA headers. Its model entrypoint is replaced. The combined
`dev-dependencies.lock.json` has 312 public Ubuntu Noble archives: 176.26 MiB
compressed, approximately 876 MiB installed. The solver used the pinned base's
exact package status, with no recommendations, removals, ESM or NVIDIA archives.
The gRPC generator supplement is included, so the original incremental retry is
not required. No CUDA toolkit or driver download is performed.

`Dockerfile.codecs` uses the immutable public 3.3 streamprocessing manifest.
`native-libs.lock.json` records its 55-archive CPU library closure (25.64 MiB).
The historical 63-archive codec lock under `../thor-current/` stays unchanged;
the separately locked libsodium supplement is also retained. Package extraction
and BLAS/LAPACK linker configuration occur inside the image. There is no runtime
APT or network installation. Codec and runtime stages fail on missing ELFs,
failed `ldd`, unresolved libraries or checksum/control-metadata mismatches.

The helper only stages public allowlisted source paths and verified archives.
Snapshots exclude `.git`, private settings, model caches, datastores, UI packages
and old objects. Generated contexts have Docker allowlists. Static `.a` files
are excluded from the final runtime, while safe shared-library symlinks survive.
Native output checksums and the frozen source manifest must agree before staging.
All caches and generated files belong under ignored `work/`; commit no `.deb`,
ELF, snapshot, build context or model bytes. Budget up to 10 GiB incremental disk.

## Prepare and compile

From the repository root, use a new work directory for each source revision.
The explicit `fetch` command downloads only locked public HTTPS archives with
bounded curl deadlines and verifies size, SHA256 and Debian identity. Existing
verified caches can instead be passed directly; never update lock hashes merely
to make a download pass. A removed archive requires an independently verified
Ubuntu snapshot containing the exact locked bytes.

```sh
python3 tools/runtime/build_vios_native.py --work work/vios-native33 snapshot
python3 tools/runtime/build_vios_native.py fetch --kind dev --cache work/vios-native33/dev-bundle
python3 tools/runtime/build_vios_native.py fetch --kind native --cache work/vios-native33/native-bundle
python3 tools/runtime/build_vios_native.py fetch --kind historical --cache work/vios-native33/codec-bundle
python3 tools/runtime/build_vios_native.py fetch --kind sodium --cache work/vios-native33/sodium-bundle
python3 tools/runtime/build_vios_native.py --work work/vios-native33 builder --cache work/vios-native33/dev-bundle
docker build --network none -t vss-vios-native33-builder:locked work/vios-native33/builder-context
mkdir -p work/vios-native33/scratch-01 work/vios-native33/output-01
```

Use the exact `source-<hash>` path printed by `snapshot` below. The immutable
public bases must already be cached (the operator may pull those exact digests).
Do not override their pinned `FROM` references. Replace `<source-hash>` before
running this operator-only command:

```sh
docker run --rm --name vss-vios-native33-builder \
  --runtime runc --network none --memory 4g --memory-swap 4g --cpus 2 \
  --env NVIDIA_VISIBLE_DEVICES=void --env NVIDIA_DRIVER_CAPABILITIES= \
  --env BASH_ENV= --env ENV= --env VSS_NATIVE_JOBS=1 \
  --mount type=bind,src="$PWD/work/vios-native33/source-<source-hash>",dst=/source,readonly \
  --mount type=bind,src="$PWD/work/vios-native33/scratch-01",dst=/build \
  --mount type=bind,src="$PWD/work/vios-native33/output-01",dst=/out \
  vss-vios-native33-builder:locked
```

The entrypoint requires cgroup-v2 memory <=4 GiB, CPU quota <=2 CPUs, and no NVIDIA
or DRM devices. Both shell initializer variables must remain empty: the vendor
base's inherited Bash initializer was observed creating `/dev/nvidiactl` even
under runc without requested GPU devices. The strict device guard caught that
before compilation and remains unchanged.

The example uses one compiler job, matching the measured build alongside ACT
and the model services. Use two only with adequate available-memory headroom;
the active Spark guard and selected reserve still apply.

The internal native make command is `make -j${VSS_NATIVE_JOBS-2} arch=aarch64
CUDA_TARGET_DIR=/usr/local/cuda PROJECT=vst MODULE=streamprocessing
GRPC_LIBS="$(pkg-config --libs grpc++ protobuf)" CXX_SYSROOT= all`. It preserves the
full streamprocessing/adaptor scope. The native gRPC override avoids upstream's
ARM64 cross-qemu assumption. `VSS_NATIVE_JOBS` accepts only `1` or `2`, defaulting
to two jobs; recursive make inherits that bounded jobserver. This
explicit recipe replaces `build.sh` only because that wrapper pulls cross
builders and launches uncapped nested Docker with `-j12`.

For dependency/recipe-only recovery, add `--env VSS_NATIVE_RESUME=1` using the same
read-only snapshot and incomplete scratch/output mounts. Every original input
is rehashed; only narrowly scoped generated `.o`/`.d`, protobuf, native shared
libraries and the executable may be extra. Altered source, manifests or escaping
symlinks stop the build. Changed source requires a fresh snapshot and scratch.
If a compiler is killed by the build container's memory limit, retain the
verified incomplete scratch and add both `--env VSS_NATIVE_RESUME=1` and
`--env VSS_NATIVE_JOBS=1` when rerunning with the documented 4 GiB/2 CPU limits.
Serial recovery reduces concurrent compiler memory without removing any source,
features, optimization flags, linker checks or resource guards.

## Stage and qualify the runtime

```sh
python3 tools/runtime/build_vios_native.py --work work/vios-native33 runtime \
  --output work/vios-native33/output-01 \
  --source work/vios-native33/source-<source-hash> \
  --native-cache work/vios-native33/native-bundle \
  --historical-cache work/vios-native33/codec-bundle \
  --sodium-cache work/vios-native33/sodium-bundle
docker build --network none -t vss-vios-streamprocessing:3.3-native \
  work/vios-native33/runtime-context-output-01
```

The staged Dockerfile composes the codec closure and native overlay directly on
the public immutable streamprocessing digest. A local Docker configuration ID
is not a valid portable `FROM` pin: BuildKit can interpret `sha256:<ID>` as a
Docker Hub repository/tag. The manifest digest above is an actual registry image
reference. No mutable intermediate codec tag is used by this maintained recipe.
`runtime-overlay-receipt.json` records that base, codec lock hashes, source tree
and included/skipped bytes; the image retains its source manifest.

The bounded qualification used a fresh private PostgreSQL/Redis/data namespace,
one 7.534-second Conveyor upload, CPU software x264, one GPU-disabled browser and
no camera. The final source (`ca097b99afb9f384…`) published a finite 7.466667-second
measured DASH timeline and decoded the visible box at source 7.3 seconds. Native
seek from +2 seconds produced a new owned viewer with a 5.500000-second timeline;
its decoded local 5.3-second frame again showed the source 7.3-second box. Stop
returned 200 and the final viewer query was empty. This qualifies that one
short archived CPU replay path, including its tail and seek; it does not qualify
sustained RTSP, overlays, audio or hardware codecs.

The complete serial build passed under 4 GiB/2 CPU limits without GPU access.
Its maximum observed builder peak was 1,693,147,136 bytes; host available memory
stayed at or above 22.04 GiB while ACT remained alive and the 20 GiB guard stayed
active. The runtime still uses its separate 2 GiB/2 CPU envelope.

Repeat isolated encoded playback after changing source/dependencies. Main
cutover requires backup and reviewed rollback/schema compatibility; the actual
paired backup, additive migration and UI rehearsal are in the
[VSS 3.3 qualification receipt](../../../docs/qa/2026-10-20-vss33-spark.md).
Never delete an application volume or use global Docker prune to clean this build.

Focused CPU/static checks:

```sh
python3 tools/runtime/test_native_vios.py -v
python3 services/vios/test/gtests/dash_replay_sensor_type_test.py -v
python3 services/vios/test/gtests/dash_eof_test.py -v
python3 services/vios/test/gtests/dash_manifest_completion_test.py -v
bash -n deploy/docker/vios-native33/build-native.sh
```
