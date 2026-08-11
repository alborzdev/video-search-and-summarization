# VIOS upload, clip, and snapshot runtime qualification

This package binds one namespaced live Thor transaction to exact official VSS
3.2.1 rows 412, 415, and 416: file upload/registration, clip plus raw/full-file
download, and historical snapshots.

The locked base executor creates a deterministic 40,394-byte H.264/AAC file,
uploads it through the main loopback VIOS ingress, verifies registration across
timeline/file/metadata surfaces, rejects a duplicate name, and downloads the
raw file byte-identically. It derives an interior 1.2-second interval from the
runtime timeline and asks VIOS to produce a distinct H.264 MP4 clip. It also
requests a timestamped MJPEG snapshot and compares decoded RGB pixels with the
owned source marker. Cleanup must restore the exact sensor and file inventories.

Plan mode verifies source locks without product actions:

```bash
python3 deploy/docker/thor-local/qualification/vios-file-lifecycle-manifest-runtime-successor/executor.py plan
```

Runtime mode is explicitly acknowledged:

```bash
python3 deploy/docker/thor-local/qualification/vios-file-lifecycle-manifest-runtime-successor/executor.py \
  execute \
  --ack I_ACK_NAMESPACED_VIOS_UPLOAD_CLIP_SNAPSHOT_AND_EXACT_CLEANUP \
  --write-receipt
```

The retained receipt contains no raw file/sensor/stream identifiers, request
paths, media bytes, or pre-existing inventory contents. It calls neither the
VSS Agent nor RT-CV and does not use the Warehouse sample.
