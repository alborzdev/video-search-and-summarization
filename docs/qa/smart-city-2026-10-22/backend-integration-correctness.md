# Smart City backend integration correction receipt

Date: 2026-10-22. CPU-only qualification against the final source bundle. No live gateway, controller, Agent, source, publisher, model or GPU mutation was performed for these corrections. Runtime rollout remains a separate operator action after the active sources are paused.

## Corrected behavior

1. **Stopped detector recovery:** Agent inventory reconciliation now distinguishes owned resources from running resources. Explicit stopped, failed, paused, completed and terminated statuses are retried rather than counted as active. Full ownership inventories remain available for paused-source and previous-profile cleanup; a selected detector gets a separate running-status lookup. Healthy peers are not restarted, and missing/unknown legacy status vocabulary retains the previous behavior. Focused tests include one failed city registration beside one healthy peer, and removal of a stopped previous-profile registration without removing its healthy peer.
2. **Manual calibration revocation:** the controller now archives explicit null homography, valid polygon and calibration revision values. Removing and re-adding a camera cannot restore geometry that the operator cleared. Archived dependent metric rules remain disabled until calibration is reviewed.
3. **Queue measurements:** the queue metric `count` includes only occupants meeting the stopped-speed condition, matching its event trigger count. `occupancy` still reports all objects in the zone. Current and recorded-history regressions cover two stopped vehicles plus one moving vehicle (`count=2`, `occupancy=3`).
4. **Unknown historical state:** configuration replacement, source loss, restart and track retirement stamp an explicit unknown boundary using the last known source clock, or the last durable event clock if the source is unavailable. They do not fabricate a departure or clear time, and do not use wall time for historical recordings. A rule replacement remains unknown when reviewed at a later same-session frame.
5. **Reset retries:** repeated delivery of the same explicit reset frame is rejected without another epoch or event. The cache is bounded to 32 reset identities per source. A genuinely new producer session still accepts sequence zero; producers must change the session ID to distinguish a new reset with otherwise identical identity.
6. **Direct calibration changes:** changing a ground transform, its valid region or its revision through the canonical site API disables dependent metric rules. Image-only rules remain enabled. Stale optional revision bindings are removed so the saved GET-rules payload remains valid for PUT-rules; metric rules still require review before reactivation.
7. **Transient observation gaps in replay:** each event record persists at most 32 state transitions with source-clock time and reason. A recovered event's earlier gap remains unknown when reviewed later, including after it clears or SQLite is reopened. When the cap removes older transitions, a request before the retained boundary explicitly reports unknown with `state-history-truncated`; legacy records without the required history use `state-history-unavailable`. Historical responses exclude future transitions. Tests cover repeated gaps, resume, clear, truncation and legacy records.

Implementation: `tools/smart-city/controller.py`, Agent `source_cleanup.py` / `rtsp_ingest.py`, and `apps/city/engine.py`, each with focused regressions.

## Executed validation

From repository root:

```bash
/tmp/vss-city-backend-test-env/bin/python -m pytest -q \
  tools/smart-city/test_manage.py tools/smart-city/test_controller.py \
  services/analytics/behavior-analytics/apps/city/tests
```

Result after the final transition-history correction: **86 passed** (50 gateway/fixture tests plus controller/manage checks).

From `services/agent`:

```bash
PYTHONPATH=packages/vss_agents/src \
  /tmp/vss-city-backend-test-env/bin/python -m pytest -q \
  packages/vss_agents/tests/unit_test/api/test_source_cleanup.py \
  packages/vss_agents/tests/unit_test/api/test_rtsp_ingest.py \
  packages/vss_agents/tests/unit_test/api/test_analysis_profiles.py \
  packages/vss_agents/tests/unit_test/api/test_analysis_profile_capacity.py

/tmp/vss-city-backend-test-env/bin/mypy --follow-imports=silent \
  packages/vss_agents/src/vss_agents/api/source_cleanup.py \
  packages/vss_agents/src/vss_agents/api/rtsp_ingest.py \
  packages/vss_agents/src/vss_agents/api/analysis_profiles.py
```

Result: **140 passed**; mypy passed for all three source files. Ruff and format checks passed for the controller and changed Agent files/tests. The gateway passes Ruff's `E9,F63,F7,F82` correctness checks; the broader existing style diagnostics were not rewritten as part of this bounded correction.

The prepared private test environment additionally installed `elasticsearch==8.19.3`, `tenacity==9.2.1`, and `aiohttp==3.14.5` for the Agent's existing imports. These are test-environment installations, not deployment or project dependency changes.

The complete synthetic qualification was executed again after the engine changes:

```bash
PYTHONPATH=services/analytics/behavior-analytics \
  /tmp/vss-city-backend-test-env/bin/python -m apps.city.qualify_fixture_loops \
  --loops 30 \
  --receipt docs/qa/smart-city-2026-10-22/synthetic-30-loop-rules-transition-history.json
```

The [latest final-source receipt](synthetic-30-loop-rules-transition-history.json) passed **30 complete loops**, **6,060 observations**, **330 events across all seven rule families**, **990 historical transition checks**, and durable JSON/CSV counts before/after SQLite reopen. It rejected 120 duplicate frames and 58 retired-session frames, and separately proved reset-to-unknown without fabricated clears. Final source hashes are included. The earlier [initial receipt](synthetic-30-loop-rules.json) and [pre-transition-history receipt](synthetic-30-loop-rules-final.json) are retained.

This qualifies synthetic geometry and rule execution only. It does not establish detector accuracy, physical camera calibration, global identity fusion, RTSP clock mapping, browser rendering or endurance.

## Read-only original RTSP resolution review

The actual VIOS PostgreSQL `sensor_streams.stream_live_url` retains the original registered RTSP URI, keyed by `sensor_id` / `stream_id`. A read-only query confirmed that the two current main-stream rows exactly match the controlled replay publisher URIs; only Boolean comparisons and UUIDs were printed. Public sensor inventory/info and proxy-stream APIs expose metadata or proxy URLs rather than these original values.

The controller therefore cannot currently resolve an original URI through its supported HTTP inventory contract. A future narrowly scoped VIOS resolver or Agent-owned persisted registration registry can provide that capability. This review did not grant DB credentials to the controller, add a URI bypass, open another RTSP reader or alter the selected input path.

## Source freeze

The gateway, controller and Agent changes covered by this receipt are frozen pending the parent operator's coordinated rollout. Historical receipt hashes remain the evidence for the executed bundle; a future code change requires the relevant checks again. Live source state and all runtime restarts remain owned by the parent operator.
