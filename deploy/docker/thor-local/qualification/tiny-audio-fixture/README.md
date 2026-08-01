# Tiny known-speech audio fixture

This isolated tool creates one six-second, Warehouse-free MP4 candidate input
for the three `audio-understanding` runtime gaps:

- `audio-aware Base workflow`
- `audio transcript per RT-VLM chunk`
- `audio-aware summarization and alerts`

The video is a 320x240, 10 fps color card with `drawtext`, encoded as H.264
`yuv420p`. The mono 48 kHz AAC-LC track is synthesized locally by FFmpeg's
`lavfi` `flite` filter and says exactly:

```text
Attention operator. The blue crate is ready.
```

No media binary or generated receipt is checked into this directory.

## Inert default

Running the tool without a subcommand only prints a plan. It resolves no
binary, starts no subprocess, and writes nothing:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/tiny-audio-fixture/fixture.py
```

## Explicit generation

Generation requires the exact acknowledgement below and an absolute new
`.mp4` path outside the repository. The output parent must already exist. The
tool refuses an existing media path or adjacent receipt path and never uses an
overwrite operation.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/tiny-audio-fixture/fixture.py \
  generate \
  --output /tmp/vss-known-speech.mp4 \
  --acknowledge \
  I_ACKNOWLEDGE_GENERATING_ONE_TINY_AUDIO_FIXTURE_OUTSIDE_THE_REPOSITORY
```

That creates only:

```text
/tmp/vss-known-speech.mp4
/tmp/vss-known-speech.mp4.receipt.json
```

Choose unused paths; the example will fail safely if either already exists.
Generation invokes only absolute local `ffmpeg` and `ffprobe` executables
resolved inside `/usr/local/bin:/usr/bin:/bin`. The canonical binaries and
trusted roots must be root-owned and not group/world writable; their paths and
SHA-256 values are recorded in the receipt. Both receive a fixed environment
containing only `PATH`, `LANG`, `LC_ALL`, and `TZ`; `shell=False`, a null stdin,
fixed timeouts, and a local-only protocol whitelist are enforced. Stdout and
stderr are incrementally captured with respective 131,072-byte and 16,384-byte
hard ceilings; a timeout or flood kills and reaps the process group. The recipe
contains only `lavfi` sources and a local file output. It has no Docker,
network, download, service, credential, model, or Warehouse-data path.

The media is bounded to 2,000,000 bytes. Generation occurs in a newly owned
mode-0700 work directory under the output parent. Publication uses
same-filesystem hard links, so an existing destination is never replaced. If
receipt publication collides after media publication, the tool preserves the
current output path and the competing receipt rather than attempting an unsafe
pathname rollback that could delete a replacement inode. It reports that
partial publication explicitly. Cleanup never recursively removes unexpected
content.

## Read-only verification

Verification validates the strict receipt schema, recomputes the media SHA-256
and byte count, and compares a fresh read-only `ffprobe` observation:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 \
  deploy/docker/thor-local/qualification/tiny-audio-fixture/fixture.py \
  verify \
  --media /tmp/vss-known-speech.mp4 \
  --receipt /tmp/vss-known-speech.mp4.receipt.json
```

`verify` opens each input once with `O_NOFOLLOW`, admits it with `fstat`, and
keeps both descriptors pinned through verification. Receipt reads and media
hashes use the descriptors; `ffprobe` receives `/proc/self/fd/<n>` through an
explicit `pass_fds` set. Identity, size, timestamps, receipt bytes, and media
SHA-256 are checked again after probing. It writes nothing and invokes only
`ffprobe`. The raw receipt schema is itself pinned by SHA-256. The receipt locks
the exact phrase and its UTF-8 SHA-256, fixed generator recipe, local tool
provenance, media SHA-256 and size, container duration, and exact H.264 and
AAC-LC stream properties.

## Tests

The default suite covers acknowledgement, outside-repository path admission,
no-overwrite behavior, trusted/sanitized subprocess execution, timeouts,
stdout/stderr flooding, raw-schema drift, malformed and duplicate probe JSON,
stream/property drift, symlink and TOCTOU replacement, publication collisions,
hash drift, and read-only verification. Media generation and probing are mocked
except in the opt-in integration:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/tiny-audio-fixture/tests
```

The real local FFmpeg integration is opt-in and still writes only to pytest's
fresh temporary directory outside the repository:

```bash
VSS_RUN_TINY_AUDIO_FIXTURE_INTEGRATION=1 \
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q \
  deploy/docker/thor-local/qualification/tiny-audio-fixture/tests/test_fixture.py::test_optional_local_ffmpeg_integration
```

## Qualification boundary

This package supplies a fixed-recipe, individually hashed candidate artifact;
it does not claim byte-identical output across FFmpeg builds, speech-recognition
accuracy, or semantic understanding. It does not run VSS and cannot advance any
of the three gaps. Closing them still requires an admitted local audio-capable
runtime plus transcript or semantic output and the actual workflow response
transcript. In particular, the per-chunk transcript claim requires a
transcript-producing ASR path; known spoken input alone is not ASR evidence.
The receipt therefore says `candidate_input_only` and never reports runtime
evidence or a passed capability.
