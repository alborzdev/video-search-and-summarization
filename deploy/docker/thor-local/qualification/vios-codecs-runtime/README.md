# VIOS codec runtime qualification

This package records the warehouse-free Thor runtime qualification of the VSS
3.2.1 NvStreamer/VIOS multimedia paths. The exercised container is isolated on
loopback ports `31000` and `31554`; it uses tiny generated fixtures, a copied
configuration, a temporary database, and the immutable local NvStreamer
derivative. It does not change the main VIOS configuration or register a
camera/RTSP source into the main deployment.

The run exercises:

- a High-profile H.264/AAC fixture with exactly two B-frames;
- a four-slice-per-picture HEVC/AAC fixture (120 first slices and 360
  continuation slices);
- hardware-default snapshots and 120-frame RTSP/TCP decode for H.264 and HEVC;
- a separate `data.use_software_path=true` restart;
- software H.264/H.265 snapshots;
- forced x264/x265 ingest transcode at 12 fps, 1.2 Mbps, GOP 24, zero B-frames,
  with AAC retained and republished over RTSP;
- every retained GStreamer plugin's dynamic-library closure.

`capture.py` performs no container or product lifecycle action and no mutation
through the NvStreamer API. It validates the already-produced artifacts plus
the currently running software-path qualifier and writes a canonical receipt:

```bash
python3 deploy/docker/thor-local/qualification/vios-codecs-runtime/capture.py \
  --artifacts /tmp/OWNED_ARTIFACT_DIRECTORY \
  --output deploy/docker/thor-local/qualification/vios-codecs-runtime/runtime-receipt.json
```

`official-runtime-evidence.json` binds that raw receipt to canonical capability
`manifest-entry.vios-codecs-audio.05-cpu-multimedia-support` and records the
exact six-stream API cleanup, owned container removal, isolated empty sensor
list before shutdown, and absence of both temporary trees. The parity verifier
validates the complete raw receipt, not only the selected result pointer. The
broader media family remains open for the approval-gated main-VIOS recording
handoff.

The direct H.264+B-frame+AAC combination remains an evidenced upstream
limitation: video republishes and decodes, but the audio track is absent from
the RTSP presentation. The qualified local substitute is the software
transcode, which removes B-frames while retaining AAC. Registering the returned
RTSP URL into the main VIOS instance remains deliberately unexecuted until the
exact approval phrase `approve RT-CV sample stream add` is supplied.

Run the offline checks with:

```bash
pytest -q deploy/docker/thor-local/qualification/vios-codecs-runtime/tests
```
