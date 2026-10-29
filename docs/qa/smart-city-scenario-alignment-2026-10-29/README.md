# Scenario placement and visible-motion recheck — 2026-10-29

Browser: existing VSS tab at `http://127.0.0.1:7782/?workspace=smart-city`, native cameras at 1280×480. Camera calibration remained `isaac-live-98b2ae97b267da51`. No zoom, crop, camera pose, detector budget or memory reserve changes.

## Actual defects and correction

- Three native agents kept stale locomotion after prepared `teleport`: positions stayed fixed during RUNNING, then jumped to their endpoints. Native `reset` during covered preparation restored continuous rendered motion. Endpoint completion alone was not visual proof.
- The old East-crossing navigation survey exceeded the visible paint. The reviewed image ROI follows the photographed stripe edges and uses the physical road plane consistently on camera and map. The larger Northeast view owns its count.
- Four walkers stay in two files through the stripes, then fan out to distinct native-validated sidewalk exits. Path, body-clearance and WALK checks still run.
- North approach queue begins beyond the painted crossing and stop line. Blockage and emergency areas stay inside the junction.

## Rehearsal evidence

- `crossing.png`: four visible/observed people, matching crossing and map outlines, saved camera event.
- `four-walkers.jpg`: uncropped analyzed Northeast frame showing the four native walkers on the stripe band.
- `queue.png`: two approach vehicles and five stopped junction vehicles; saved event.
- `emergency.png`: visible ambulance behind blocked traffic and saved incident. It subsequently passed and the scene returned to normal traffic in 61.9 seconds.
- `scene-reports.json`: independent camera reports. Crossing replay after both vehicle scenes again peaked at four, with 17.97 seconds occupied and no observation gaps. Emergency has explicitly retained observation gaps; its 39.20 seconds are observed intervals, not inferred continuous coverage.
- `native-crossing-trace.json`: simulator diagnostics only, never used as VSS counts.

Validation: 8 native showcase tests, 42 native pedestrian/reset/path/cohort tests, and 3 area-generation/migration tests passed. The existing tab loaded the changes without a browser refresh. Current rules revision: 1026.
