# RT-VLM offline codec bundle

This directory intentionally contains no Debian packages in Git. The exact
ARM64 package identities come from the source-locked VSS 3.2.1 RT-Embed
installer, and extend the later open-source RT-VLM installer's 59-package set
with the four runtime libraries required to load every retained GStreamer plugin.
The staging tool resolves current security versions through signed Ubuntu
Noble metadata over HTTPS, validates all packages as ARM64 Debian archives,
and writes hashes plus control metadata to
`bundle/manifest.json`.

Connected, additive staging (not run during this audit):

```bash
python3 deploy/docker/thor-local/audio/codec_bundle.py source-audit
python3 deploy/docker/thor-local/audio/codec_bundle.py stage
```

Offline verification and image construction:

```bash
python3 deploy/docker/thor-local/audio/codec_bundle.py verify
docker build --network=none --pull=false \
  -f deploy/docker/thor-local/audio/Dockerfile.rtvi-vlm-codecs \
  -t cti-vss-rt-vlm:3.2.1-thor-audio-offline .
```

The derivative sets `INSTALL_PROPRIETARY_CODECS=false` in its entrypoint and
sources the already-extracted codec root. No `apt`, `curl`, model download, or
registry access occurs during image build or service startup. Operators remain
responsible for codec licensing in their jurisdiction.
