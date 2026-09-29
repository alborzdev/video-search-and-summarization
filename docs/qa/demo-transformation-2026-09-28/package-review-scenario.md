# Package review scenario — September 28

## Provenance and visible content

Original bundled simulation: deploy/docker/data-dir/videos/nvstreamer/sample-sim-box-conveyor.mp4, 81.5667 seconds. A broader frame audit found white boxes with red stripes near 24 seconds and a visibly crumpled brown carton near 44 seconds. Earlier sparse sampling did not characterize the whole source. The previous live color answer is plausible against this source, but its exact historical window remains unverified.

Created an eight-second stream-copy excerpt from 40–48 seconds: [conveyor-package-review-demo.mp4](conveyor-package-review-demo.mp4), 1,492,524 bytes. [Original frame at 44 seconds](package-condition-frame.jpg). Uploaded through the actual UI with Search only; Upload Complete 1/1. Sensor ebb07ef6-8d22-479f-84b7-ccd77c45ebd4, synthetic archive timeline 2025-01-01 00:00:00–00:00:08 UTC. This is simulation, not a real damaged shipment.

## Rehearsal result

Home → Conveyor — Package Review → Find a box to inspect searched “crumpled cardboard box on a conveyor” scoped to this source. One five-second match (0:00–0:05) returned. Actual playback reached 5/5 seconds, readyState 4, no error; deformed carton visible. Semantic retrieval and human-review path passed.

Fresh selected-evidence questions:

1. “Describe the visible condition of the box.” Answer: “The box is brown and has a recycling symbol on it.” Local analysis 8.3 seconds; observed complete by 12.996 seconds. Missed requested condition.
2. “Describe the box's shape.” Answer: “The box has a rectangular shape.” Local analysis 7.7 seconds; observed complete by 16.868 seconds. Failed to describe the conspicuous deformation.

Backend logged the correct sensor and exact 0–5-second interval, 10 sampled frames. [Second answer evidence](package-shape-answer.jpg). These are reproducible visual accuracy failures, not a successful automated damage-detection demonstration. No report was saved from either answer.

## UI and next work

Home offers the new scenario with “Package review · Find footage for human inspection (simulation)”. Existing warehouse/movement examples remain preferred defaults; uploading a new challenge clip does not displace them. Package review currently demonstrates retrieval plus human inspection. Diagnose actual sampled images/preprocessing/model response before qualifying condition descriptions, alerts or rejection decisions.

Three Home tests and app typecheck passed. All 31 core roles remained healthy, 49.80 GiB available, guard unchanged. No detector or continuous analysis enabled.
