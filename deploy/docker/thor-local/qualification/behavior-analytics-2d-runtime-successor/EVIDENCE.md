# Evidence

- Released image: `nvcr.io/nvidia/vss-core/vss-behavior-analytics:3.2.1`
- Exact image ID: `sha256:f3fd84f9c9f63b9d00298161929b71c73f36b301782d58bf810e0583843c9fa6`
- Architecture: arm64
- Input: 20,000 frames, 171,436 objects, three calibrated cameras
- Decoded output: 38,286 behaviors, 20,000 enhanced frames, 121 events, and 24,924 incidents
- Directional semantics: ROI ENTRY/EXIT and tripwire IN/OUT were all observed
- Trajectories: 1,778,483 location points; 13,084 multi-point trajectories; 200-point maximum
- Occupancy: 58,323 positive FOV counts and 32,983 positive ROI counts
- Proximity/clustering: 426 detections and 426 cluster entries
- Exit integrity: oracle and playback both exited 0, were not OOM-killed, and never restarted
- Cleanup: disposable containers and all six qualification topics are absent; normal consumers are running

The receipt locks the configuration, inspector, playback fixture, calibration,
container image identity, captured log digests, exact decoded counts, and cleanup
postconditions. No VSS Agent generation, external request, main VIOS mutation, or
main RT-CV mutation occurred.
