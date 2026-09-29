# Fresh data reset — September 9, 2026

User requested clearing saved generated data while retaining sources.

Removed 431,563 old embeddings and 1,341,866 total generated Elasticsearch documents across 726 indices (including captions, detections and incidents). Cleared graph knowledge, 3 UI history records, 4 saved reports, and 27 extracted evidence cache entries. Removed old VIOS archive intervals through the storage API. Preserved all source IDs/names, original input media, monitoring rules, calibration and service configuration.

All five named sources were paused before cleanup. Verified zero generated indices before restarting collection. Started the previously stopped local `vss-vios-nvstreamer`; resumed only the traffic source using its existing traffic-monitoring profile. Verified 3 fresh embeddings with timestamps 2026-09-09T19:25:52.085Z through 19:26:02.085Z. The original footage is a looping traffic sample; these are newly collected embeddings, not a new real-world scene.

Four IsaacSim sources remain paused/offline and need their remote feeds restored before resuming. The extra unnamed sensor registration was also preserved. Runtime memory guard remains enabled at 36 GiB. Development UI remains enabled.

`sources-before.json` contains connection metadata and is mode 0600. No generated content backup was made; before manifests retain counts and index names only.
