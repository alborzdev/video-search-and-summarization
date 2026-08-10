# Thor VIOS media lane

This directory closes the VIOS runtime-package-install gap on Jetson AGX
Thor. The released VSS 3.2.1 stream processor and NvStreamer images retain
the Ubuntu package database but omit multimedia files. Upstream normally
repairs them with `apt` at every start. The Thor derivatives instead extract
an already-staged, checksum-locked ARM64 bundle during a networkless build and
refuse to start if either runtime install flag is enabled.

No warehouse sample bundle is used. Runtime qualification uses tiny generated
or operator-supplied fixtures only.

## What is covered

| Advertised behavior | Pinned implementation evidence | Runtime evidence still required |
|---|---|---|
| B-frame handling | B-frame discovery, DB propagation, low-latency-decoder guard, H.264/H.265 slice parsing | Upload and republish a tiny H.264 B-frame clip |
| HEVC multislice / RFC 7798 | HEVC continuation-slice pacing, Live555 H.265 RTP source/sink and DONL/DOND support | Republish a four-slice HEVC fixture and consume every frame over RTSP/TCP |
| H.264 / H.265 | H.264/H.265 parsers, NVIDIA encoders, x264/x265 CPU fallback, Thor codec allowlist | Upload, media-info, snapshot, RTSP and clip checks for both codecs |
| Audio recording | AAC transcode plus audio remux consumers and recording storage path | Record a non-B-frame H.264/AAC source and download a clip with audio enabled |
| Audio RTSP republish | `includeAudio=true`, audio subsession creation, A/V loop synchronization | `ffprobe` the NvStreamer URL with `includeAudio=true` and require an audio stream |
| CPU multimedia | `avdec_h264`, `avdec_h265`, `x264enc`, `x265enc`, `avenc_aac`; matching ARM64 libraries in the bundle | Qualify a separate `use_software_path=true` run; the default Thor graph remains hardware accelerated |

The source audit hashes the exact VSS files behind those claims so a future
upstream change fails closed rather than silently weakening the evidence.

## Connected staging (one time)

The VIOS lane deliberately shares the RT-VLM lane's tracked
`audio/codec-bundle.lock.json`, which fixes the exact 59 upstream versions plus
four Thor runtime-closure packages, including every filename,
sizes, SHA-256 values, and credential-free allowlisted source URLs. VIOS keeps
its own ignored local bundle directory. The stager resolves through signed
Ubuntu Noble metadata over HTTPS but refuses any result that differs from the
committed lock.

```bash
python3 deploy/docker/thor-local/vios-codecs/vios_media.py source-audit
python3 deploy/docker/thor-local/vios-codecs/vios_media.py stage
python3 deploy/docker/thor-local/vios-codecs/vios_media.py verify
```

`stage` is the only connected command. It is additive and refuses to replace
an existing bundle. The ignored bundle lives at
`deploy/docker/thor-local/vios-codecs/bundle/`.

There is deliberately no automatic lock refresh. A security-version update is
a reviewed source change to the one shared lock plus the shell verifier's
expected lock digest, followed by both codec adversarial suites.

## Networkless image build

After verification, print the two exact commands:

```bash
python3 deploy/docker/thor-local/vios-codecs/vios_media.py build-command
```

Both use `docker build --network=none`. The Dockerfiles first require
`manifest.json` to equal the trusted shared lock, then verify all 63 archive
checksums, validate ARM64 Debian metadata, extract them,
remove unsupported/QSV plugins, assert libav + MP4 + x264 + x265 files, and
embed the manifest. They contain no `apt`, `curl`, `wget`, or `pip` operation.

The Thor base, Warehouse 2D, MV3DT, and Sparse4D overlays also declare
`build.network: none`, set the install flags to `false`, and select the
fail-closed `/usr/local/bin/vios-offline-entrypoint`.

## Non-lifecycle preflight

```bash
python3 deploy/docker/thor-local/vios-codecs/vios_media.py preflight
```

This performs source, bundle, architecture, image-label, and entrypoint checks
using only `docker image inspect`. It never creates or runs a container.
Exit `0` means both immutable images are staged; exit `2` prints every blocker.

## Runtime qualification boundary

Static evidence is not runtime qualification. When a VIOS profile is already
running, use tiny custom fixtures and capture all of the following in one run:

1. H.264/AAC with two B-frames: NvStreamer PUT succeeds, media-info reports
   H.264 + AAC, and its discovered RTSP URL with `includeAudio=true` exposes
   both streams via `ffprobe -rtsp_transport tcp`.
2. HEVC/AAC encoded with at least four slices per frame: `trace_headers` shows
   both `first_slice_segment_in_pic_flag=1` and `=0`; NvStreamer media-info
   reports H.265 + AAC; RTSP consumption reaches fixture frame count with no
   decode error.
3. A non-B-frame H.264/AAC source registered into VIOS: recorder becomes
   active, timeline appears, and a direct `/storage/file/{streamId}` MP4
   download with `disableAudio=false` contains H.264 video plus AAC audio.
4. Repeat the VIOS upload/snapshot/clip surface with HEVC. Use direct binary
   endpoints, not the known-broken `/url` envelope variants.
5. In an isolated restart using a copied config with
   `data.use_software_path=true`, repeat H.264, H.265, and AAC transcode. Do not
   change the default hardware-accelerated Thor config in place.

Use identifiers returned by each PUT and URLs returned by
`GET /sensor/{id}/streams`; never construct them. Delete only artifacts created
by the qualification run. Audio + B-frame clip extraction remains a distinct
case because the current VIOS API reference still recommends
`disableAudio=true` for B-frame files; evidence must show actual 3.2.1 behavior
before claiming that combination.
