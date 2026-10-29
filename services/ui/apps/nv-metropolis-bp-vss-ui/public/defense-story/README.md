# Recorded inspection example

`panel-input.jpg` is the 1024 × 576 JPEG submitted to the local VSS model service
on 2026-10-22. Its source is the existing AI-generated
`/defense-preview/drone-close.png` illustration, not a real camera capture.

`panel-mask.png` is a transparent teal visualization of the actual returned
binary SAM 2.1 Tiny mask. Its extent is unmodified. Moondream 2 through Photon
provided the point for prompt `metal panel`. `panel-result.json` retains the
result metadata, input hash, model identity and timings, with the large base64
mask removed. The UI reads the point and timing from this metadata.

This single warm inference demonstrates the local pipeline, not field accuracy,
stream throughput, native Moondream segmentation, or qualification on Thor.
